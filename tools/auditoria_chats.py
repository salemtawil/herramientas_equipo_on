"""Auditoría de chats: muestras aleatorias de Chatwoot auditadas con IA y revisadas por una persona."""

import csv
import io
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for

from utils import auditoria_chats_motor as motor
from utils.auditoria_chats_pauta import CRITERIOS, SATISFACCION
from utils.auditoria_chats_rubrica import (
    CRITERIOS_QA,
    ESTADOS_QA,
    ETIQUETAS_RESULTADOS,
    FALLAS_CRITICAS,
    PAUTA_VERSION_QA,
    PROCEDIMIENTOS,
    RESULTADOS,
    calcular_qa,
    resultados_criterios,
)
from utils.auditoria_chats_manual import version_manual
from utils.auditoria_chats_store import AuditoriaChatsConfigError, AuditoriaChatsError, obtener_store
from utils.auditoria_chats_transcripcion import _etiquetas_adjuntos, _mensajes_v2, mensajes_utiles
from utils.chatwoot_reportes import ChatwootClient, _obtener_timezone, _timezone
from utils.errores import mensaje_error_publico
from utils.ia_chat import obtener_config_ia
from utils.turnos_trabajo_store import obtener_turnos_configurados

auditoria_chats_bp = Blueprint("auditoria_chats", __name__)
logger = logging.getLogger(__name__)

ESTADOS_LOTE = {
    "muestreando": "Eligiendo chats",
    "auditando": "Auditando",
    "limite_diario": "Límite diario de la IA alcanzado; retoma mañana",
    "completado": "Completado",
    "con_errores": "Completado con errores",
}


def obtener_chatwoot():
    return ChatwootClient(timeout=15)


@auditoria_chats_bp.app_template_filter("decimal_es")
def decimal_es(valor, decimales=1):
    if valor is None or valor == "":
        return "—"
    return f"{float(valor):.{decimales}f}".replace(".", ",")


def _store_o_error():
    try:
        return obtener_store(), ""
    except AuditoriaChatsConfigError as exc:
        return None, str(exc)


def _chatwoot_o_error():
    try:
        return obtener_chatwoot(), ""
    except Exception as exc:
        return None, mensaje_error_publico(exc, "Chatwoot no está configurado")


def _parsear_fecha(valor):
    try:
        return date.fromisoformat(str(valor or "").strip())
    except ValueError:
        return None


def _fecha_lote(epoch):
    try:
        return datetime.fromtimestamp(int(epoch), _obtener_timezone(_timezone())).strftime("%d/%m/%Y")
    except (TypeError, ValueError, OSError):
        return ""


def _quiere_json():
    mejor = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return mejor == "application/json" and request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]


SIN_TURNO = "Sin turno asignado"
PAUTA_LOTES_NUEVOS = PAUTA_VERSION_QA
LLAMADAS_IA_POR_CHAT = {PAUTA_VERSION_QA: 2}
CUPO_DIARIO_DEFAULT = 20


def _cupo_diario():
    try:
        return max(0, int(os.getenv("AUDITORIA_CHATS_AI_CUPO_DIARIO", CUPO_DIARIO_DEFAULT)))
    except ValueError:
        return CUPO_DIARIO_DEFAULT


PALABRAS_LLAMADAS = ("llamad", "voz", "voice", "call", "telefon", "phone")


def _es_bandeja_de_llamadas(bandeja):
    campos = ("name", "channel_type", "medium", "provider", "channel_name")
    texto = motor._normalizar_nombre(" ".join(str(bandeja.get(campo) or "") for campo in campos))
    return any(palabra in texto for palabra in PALABRAS_LLAMADAS)


def _listar_bandejas(chatwoot, preferidas=None):
    """Bandejas de Chatwoot y si se preseleccionan.

    Si hay un lote anterior, se marcan las mismas bandejas que se usaron en él (así una
    excepción como una bandeja Voice con SMS se elige una vez y se recuerda). Si no, se
    marcan todas menos las de llamadas o voz.
    """
    listar = getattr(chatwoot, "listar_bandejas", None)
    if not listar:
        return []
    preferidas = {int(b) for b in preferidas or []}
    bandejas = []
    for bandeja in listar() or []:
        if bandeja.get("id") is None:
            continue
        tipo = str(bandeja.get("channel_type") or "").replace("Channel::", "")
        identificador = int(bandeja["id"])
        bandejas.append(
            {
                "id": identificador,
                "nombre": bandeja.get("name") or f"Bandeja {identificador}",
                "tipo": tipo,
                "es_voz": _es_bandeja_de_llamadas(bandeja),
                "marcada": identificador in preferidas if preferidas else not _es_bandeja_de_llamadas(bandeja),
            }
        )
    return sorted(bandejas, key=lambda b: (not b["marcada"], motor._normalizar_nombre(b["nombre"])))


def _agrupar_por_turno(agentes, turnos):
    """Agentes de Chatwoot agrupados en el orden de Turnos de trabajo, más los que no tienen turno.

    Devuelve también los nombres de Turnos de trabajo que no coinciden con ningún agente de Chatwoot.
    """
    grupos = [{"nombre": nombre, "agentes": [a for a in agentes if a["turno"] == nombre]} for nombre in turnos]
    sin_turno = [a for a in agentes if not a["turno"]]
    if sin_turno:
        grupos.append({"nombre": SIN_TURNO, "agentes": sin_turno})

    en_chatwoot = {motor._normalizar_nombre(a["nombre"]) for a in agentes}
    sin_cruce = sorted(
        {n for nombres in turnos.values() for n in nombres if motor._normalizar_nombre(n) not in en_chatwoot},
        key=motor._normalizar_nombre,
    )
    return grupos, sin_cruce


@auditoria_chats_bp.route("/auditoria-chats/", methods=["GET"])
def index():
    store, error_store = _store_o_error()
    config_ia = obtener_config_ia()
    chatwoot, error_chatwoot = _chatwoot_o_error()

    turnos = obtener_turnos_configurados()
    agentes, avisos, grupos, sin_cruce, bandejas = [], [], [], [], []

    lotes = []
    if store:
        try:
            lotes = store.listar_lotes()
        except AuditoriaChatsError as exc:
            avisos.append(mensaje_error_publico(exc, "No se pudieron leer los lotes guardados"))
    bandejas_ultimo_lote = next(
        ((l.get("alcance_detalle") or {}).get("bandejas") for l in lotes if (l.get("alcance_detalle") or {}).get("bandejas")),
        None,
    )

    if chatwoot:
        try:
            agentes = sorted(
                motor.resolver_agentes("todos", {}, chatwoot.listar_agentes(), turnos)[0],
                key=lambda a: motor._normalizar_nombre(a["nombre"]),
            )
            grupos, sin_cruce = _agrupar_por_turno(agentes, turnos)
            bandejas = _listar_bandejas(chatwoot, preferidas=bandejas_ultimo_lote)
        except Exception as exc:
            logger.warning("No se pudieron listar los agentes de Chatwoot: %s", exc)
            error_chatwoot = mensaje_error_publico(exc, "No se pudieron listar los agentes de Chatwoot")

    manual_cargado = True
    if store and PAUTA_LOTES_NUEVOS == PAUTA_VERSION_QA:
        try:
            manual_cargado = bool(store.indice_manual(version_manual()))
        except AuditoriaChatsError as exc:
            manual_cargado = False
            avisos.append(mensaje_error_publico(exc, "No se pudo leer el manual de procedimientos"))
    llamadas_por_chat = LLAMADAS_IA_POR_CHAT.get(PAUTA_LOTES_NUEVOS, 1)

    hoy_local = datetime.now(_obtener_timezone(_timezone())).date()
    inicio, fin = motor.rango_semana_anterior(hoy_local, _timezone())
    return render_template(
        "auditoria_chats.html",
        agentes=agentes,
        grupos=grupos,
        sin_cruce=sin_cruce,
        bandejas=bandejas,
        cupo_diario=_cupo_diario() // llamadas_por_chat,
        llamadas_por_chat=llamadas_por_chat,
        manual_cargado=manual_cargado,
        version_manual=version_manual(),
        lotes=lotes,
        estados_lote=ESTADOS_LOTE,
        fecha_lote=_fecha_lote,
        fecha_inicio=inicio.isoformat(),
        fecha_fin=fin.isoformat(),
        chats_por_agente=motor.CHATS_POR_AGENTE_DEFAULT,
        chats_por_agente_max=motor.CHATS_POR_AGENTE_MAX,
        error_store=error_store,
        error_chatwoot=error_chatwoot,
        ia_activa=config_ia["activa"],
        ia_modelo=config_ia["model"],
        ia_respaldo=config_ia["model_respaldo"],
        avisos=avisos,
        puede_crear=bool(store and chatwoot and not error_chatwoot and manual_cargado),
    )


@auditoria_chats_bp.route("/auditoria-chats/lotes", methods=["POST"])
def crear():
    store, error_store = _store_o_error()
    chatwoot, error_chatwoot = _chatwoot_o_error()
    if not store or not chatwoot:
        flash(error_store or error_chatwoot, "warning")
        return redirect(url_for("auditoria_chats.index"))

    since = _parsear_fecha(request.form.get("fecha_inicio"))
    until = _parsear_fecha(request.form.get("fecha_fin"))
    if not since or not until or since > until:
        flash("Revisa el rango de fechas: la fecha inicial debe ser anterior o igual a la final.", "warning")
        return redirect(url_for("auditoria_chats.index"))

    alcance = request.form.get("alcance", "todos")
    if alcance not in ("todos", "turno", "agentes"):
        alcance = "todos"
    detalle = {}
    if alcance == "turno":
        detalle = {"turno": request.form.get("turno", "")}
    elif alcance == "agentes":
        detalle = {"agentes": request.form.getlist("agentes")}

    try:
        agentes, sin_cruce = motor.resolver_agentes(
            alcance, detalle, chatwoot.listar_agentes(), obtener_turnos_configurados()
        )
    except Exception as exc:
        flash(mensaje_error_publico(exc, "No se pudieron listar los agentes de Chatwoot"), "warning")
        return redirect(url_for("auditoria_chats.index"))

    if not agentes:
        flash("No hay agentes de Chatwoot para ese alcance. Elige un turno con agentes o marca al menos uno.", "warning")
        return redirect(url_for("auditoria_chats.index"))

    try:
        disponibles = {b["id"]: b["nombre"] for b in _listar_bandejas(chatwoot)}
    except Exception as exc:
        flash(mensaje_error_publico(exc, "No se pudieron listar las bandejas de Chatwoot"), "warning")
        return redirect(url_for("auditoria_chats.index"))
    if disponibles:
        bandejas = sorted({int(b) for b in request.form.getlist("bandejas") if str(b).isdigit()} & set(disponibles))
        if not bandejas:
            flash("Marca al menos una bandeja de entrada de chats.", "warning")
            return redirect(url_for("auditoria_chats.index"))
        detalle["bandejas"] = bandejas
        detalle["bandejas_nombres"] = {str(b): disponibles[b] for b in bandejas}

    try:
        lote = motor.crear_lote(
            store,
            since=since,
            until=until,
            alcance=alcance,
            detalle=detalle,
            chats_por_agente=request.form.get("chats_por_agente"),
            agentes=agentes,
            config_ia=obtener_config_ia(),
            pauta_version=PAUTA_LOTES_NUEVOS,
        )
    except AuditoriaChatsError as exc:
        flash(mensaje_error_publico(exc, "No se pudo crear el lote"), "warning")
        return redirect(url_for("auditoria_chats.index"))

    if sin_cruce:
        flash(
            "Estos integrantes del turno no se encontraron en Chatwoot y no se auditarán: " + ", ".join(sin_cruce),
            "warning",
        )
    return redirect(url_for("auditoria_chats.ver_lote", lote_id=lote["id"]))


def _cargar_lote_o_404(store, lote_id):
    try:
        lote = store.obtener_lote(lote_id)
    except AuditoriaChatsError:
        lote = None
    if not lote:
        abort(404)
    return lote


@auditoria_chats_bp.route("/auditoria-chats/lote/<lote_id>", methods=["GET"])
def ver_lote(lote_id):
    store, error_store = _store_o_error()
    if not store:
        abort(404)
    lote = _cargar_lote_o_404(store, lote_id)
    chats = store.listar_chats(lote_id)
    vigentes = [c for c in chats if c.get("estado") != "descartado"]
    cola = [c for c in vigentes if c.get("por_revisar") and c.get("estado") != "revisado"]
    progreso = motor._progreso(chats)
    porcentaje = round(progreso["auditados"] * 100 / progreso["total"]) if progreso["total"] else 0
    terminado = lote.get("estado") in ("completado", "con_errores") and not progreso["pendientes"]

    return render_template(
        "auditoria_chats_lote.html",
        lote=lote,
        estado_texto=ESTADOS_LOTE.get(lote.get("estado"), lote.get("estado")),
        fecha_lote=_fecha_lote,
        resumen=motor.resumen_por_agente(chats),
        es_qa=motor.es_lote_qa(lote),
        feedback=motor.feedback_por_agente(chats),
        feedback_qa=motor.feedback_por_agente_qa(chats) if motor.es_lote_qa(lote) else [],
        estados_qa=ESTADOS_QA,
        estado_efectivo=motor.estado_efectivo,
        qa_efectivo=motor.qa_efectivo,
        todos=sorted(vigentes, key=lambda c: (motor._normalizar_nombre(c.get("agente_nombre", "")), str(c.get("conversacion_fecha") or ""))),
        valoracion=motor.valoracion,
        valoraciones=motor.VALORACIONES,
        cola=sorted(cola, key=lambda c: (c.get("motivo_revision") != "marcado", c.get("ia_nota") or 0)),
        progreso=progreso,
        porcentaje=porcentaje,
        terminado=terminado,
        muestreados=lote.get("agentes_muestreados") or [],
        errores=[c for c in vigentes if c.get("estado") == "error"],
        ia_activa=obtener_config_ia()["activa"],
    )


@auditoria_chats_bp.route("/auditoria-chats/lote/<lote_id>/paso", methods=["POST"])
def paso(lote_id):
    store, error_store = _store_o_error()
    chatwoot, error_chatwoot = _chatwoot_o_error()
    if not store or not chatwoot:
        resultado = {"accion": "error", "estado": "", "mensaje": error_store or error_chatwoot, "esperar_segundos": 0}
    else:
        _cargar_lote_o_404(store, lote_id)
        try:
            resultado = motor.ejecutar_paso(store, lote_id, chatwoot, obtener_config_ia())
        except AuditoriaChatsError as exc:
            logger.warning("Fallo en un paso de auditoría de chats: %s", exc)
            resultado = {
                "accion": "error",
                "estado": "",
                "mensaje": mensaje_error_publico(exc, "No se pudo avanzar el lote"),
                "esperar_segundos": 0,
            }

    if _quiere_json():
        return jsonify(resultado)
    if resultado.get("mensaje"):
        flash(resultado["mensaje"], "warning" if resultado.get("accion") in ("error", "configuracion") else "success")
    return redirect(url_for("auditoria_chats.ver_lote", lote_id=lote_id))


# ---------------------------------------------------------------------------
# Revisión humana, exportación, borrado e historial
# ---------------------------------------------------------------------------

SEMANAS_HISTORIAL = 8
MAX_REVISOR = 80
MAX_COMENTARIO = 2000


def _cargar_chat_o_404(store, chat_id):
    try:
        chat = store.obtener_chat(chat_id)
    except AuditoriaChatsError:
        chat = None
    if not chat:
        abort(404)
    return chat


def _siguiente_por_revisar(store, lote_id, excluir_id):
    for chat in store.listar_chats(lote_id):
        if chat["id"] != excluir_id and chat.get("por_revisar") and chat.get("estado") not in ("revisado", "descartado"):
            return chat
    return None


def _mensajes_para_vista(mensajes, incluir_internos=False):
    """Mensajes para mostrar. En la pauta QA también las notas internas y los eventos del sistema,
    porque la IA puede citarlos como evidencia."""
    tz = _obtener_timezone(_timezone())
    vista = []
    for mensaje in _mensajes_v2(mensajes) if incluir_internos else mensajes_utiles(mensajes):
        es_agente = mensaje.get("message_type") == 1
        es_sistema = mensaje.get("message_type") == 2
        remitente = mensaje.get("sender") if isinstance(mensaje.get("sender"), dict) else {}
        if es_sistema:
            autor = "Sistema"
        else:
            autor = remitente.get("name") or ("Agente" if es_agente else "Cliente")
            if mensaje.get("private"):
                autor = f"Nota interna · {autor}"
        vista.append(
            {
                "id": f"m{mensaje.get('id')}",
                "es_agente": es_agente,
                "es_interno": es_sistema or bool(mensaje.get("private")),
                "autor": autor,
                "hora": datetime.fromtimestamp(int(mensaje.get("created_at") or 0), tz).strftime("%d/%m %H:%M"),
                "texto": " ".join(
                    p for p in [str(mensaje.get("content") or "").strip(), *_etiquetas_adjuntos(mensaje)] if p
                ),
            }
        )
    return vista


@auditoria_chats_bp.route("/auditoria-chats/chat/<chat_id>", methods=["GET"])
def ver_chat(chat_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    chat = _cargar_chat_o_404(store, chat_id)
    lote = _cargar_lote_o_404(store, chat["batch_id"])

    es_qa = motor.es_lote_qa(lote)
    mensajes, url_chatwoot = [], ""
    chatwoot, error_chatwoot = _chatwoot_o_error()
    if chatwoot:
        url_chatwoot = chatwoot.url_conversacion(chat["conversation_id"])
        try:
            mensajes = _mensajes_para_vista(
                chatwoot.mensajes_de_conversacion(chat["conversation_id"]), incluir_internos=es_qa
            )
        except Exception as exc:
            logger.warning("No se pudo leer el chat %s: %s", chat["conversation_id"], exc)
            error_chatwoot = mensaje_error_publico(exc, "No se pudo leer el chat en Chatwoot")

    return render_template(
        "auditoria_chats_chat.html",
        chat=chat,
        lote=lote,
        resultado=chat.get("ia_resultado") or {},
        valoracion=motor.valoracion(chat) if chat.get("estado") in motor.ESTADOS_AUDITADOS else None,
        valoraciones=motor.VALORACIONES,
        criterios=CRITERIOS,
        satisfacciones=SATISFACCION,
        mensajes=mensajes,
        error_chatwoot=error_chatwoot,
        url_chatwoot=url_chatwoot,
        siguiente=_siguiente_por_revisar(store, lote["id"], chat["id"]),
        es_qa=es_qa,
        criterios_qa=CRITERIOS_QA,
        resultados_qa=RESULTADOS,
        etiquetas_resultados=ETIQUETAS_RESULTADOS,
        estados_qa=ESTADOS_QA,
        fallas_criticas=FALLAS_CRITICAS,
        procedimientos=PROCEDIMIENTOS,
        criterios_efectivos=motor.criterios_efectivos(chat) if es_qa else {},
        estado_precargado=_estado_precargado(chat) if es_qa else None,
    )


def _estado_precargado(chat):
    """Estado sugerido para el formulario de revisión: el del revisor, si no el recalculado."""
    if chat.get("estado_final"):
        return chat["estado_final"]
    fallas = (chat.get("revision") or {}).get("fallas") or {}
    calculo = calcular_qa(motor.criterios_efectivos(chat), sum(1 for v in fallas.values() if v == "confirmada"))
    return calculo["estado"] if calculo["estado"] in ESTADOS_FINALES_REVISION else None


ESTADOS_FINALES_REVISION = ("aprobado", "necesita_mejorar", "no_aprobado")
DECISIONES_FALLA = ("confirmada", "descartada")


def _revisar_qa(store, chat, revisor, satisfaccion, comentario):
    """Guarda la revisión de un chat QA-1.1. Devuelve un mensaje de error o None si se guardó."""
    resultado = chat.get("ia_resultado") or {}
    originales = resultados_criterios(resultado)
    criterios, corregidos = {}, {}
    for codigo, _, _ in CRITERIOS_QA:
        valor = request.form.get(f"criterio_{codigo}") or originales.get(codigo)
        if valor not in RESULTADOS:
            return f"Elige un resultado válido para el criterio {codigo}."
        criterios[codigo] = valor
        if valor != originales.get(codigo):
            corregidos[codigo] = valor

    fallas = {}
    for falla in resultado.get("fallas_criticas") or []:
        decision = request.form.get(f"falla_{falla['codigo']}", "")
        if decision not in DECISIONES_FALLA:
            return f"Confirma o descarta la falla crítica {falla['codigo']}."
        fallas[falla["codigo"]] = decision

    estado_final = request.form.get("estado_final", "")
    if estado_final not in ESTADOS_FINALES_REVISION:
        return "Elige el estado final del chat."
    confirmadas = sum(1 for v in fallas.values() if v == "confirmada")
    if confirmadas:
        estado_final = "no_aprobado"

    store.actualizar_chat(
        chat["id"],
        {
            "estado": "revisado",
            "revisor": revisor,
            "qa_final": calcular_qa(criterios, confirmadas)["qa"],
            "estado_final": estado_final,
            "revision": {"criterios": corregidos, "fallas": fallas},
            "satisfaccion_final": satisfaccion,
            "comentario_revisor": comentario,
            "revisado_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return None


@auditoria_chats_bp.route("/auditoria-chats/chat/<chat_id>", methods=["POST"])
def revisar(chat_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    chat = _cargar_chat_o_404(store, chat_id)
    if chat.get("estado") not in ("auditado", "error", "revisado"):
        flash("Este chat todavía no se ha auditado.", "warning")
        return redirect(url_for("auditoria_chats.ver_chat", chat_id=chat_id))

    revisor = " ".join(str(request.form.get("revisor") or "").split())[:MAX_REVISOR]
    satisfaccion = request.form.get("satisfaccion_final", "")
    comentario = str(request.form.get("comentario_revisor") or "").strip()[:MAX_COMENTARIO]
    if (chat.get("ia_resultado") or {}).get("pauta_version") == PAUTA_VERSION_QA:
        if not revisor or satisfaccion not in SATISFACCION:
            error = "Indica tu nombre y la satisfacción del cliente."
        else:
            error = _revisar_qa(store, chat, revisor, satisfaccion, comentario)
        if error:
            flash(error, "warning")
            return redirect(url_for("auditoria_chats.ver_chat", chat_id=chat_id))
        return _tras_revisar(store, chat)
    try:
        nota = int(request.form.get("nota_final", ""))
    except ValueError:
        nota = 0

    if not revisor or not 1 <= nota <= 5 or satisfaccion not in SATISFACCION:
        flash("Indica tu nombre, una nota final de 1 a 5 y la satisfacción del cliente.", "warning")
        return redirect(url_for("auditoria_chats.ver_chat", chat_id=chat_id))

    store.actualizar_chat(
        chat_id,
        {
            "estado": "revisado",
            "revisor": revisor,
            "nota_final": nota,
            "satisfaccion_final": satisfaccion,
            "comentario_revisor": comentario,
            "revisado_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return _tras_revisar(store, chat)


def _tras_revisar(store, chat):
    flash(f"Chat #{chat['conversation_id']} revisado.", "success")
    siguiente = _siguiente_por_revisar(store, chat["batch_id"], chat["id"])
    if siguiente:
        return redirect(url_for("auditoria_chats.ver_chat", chat_id=siguiente["id"]))
    return redirect(url_for("auditoria_chats.ver_lote", lote_id=chat["batch_id"]))


@auditoria_chats_bp.route("/auditoria-chats/chat/<chat_id>/reintentar", methods=["POST"])
def reintentar(chat_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    chat = _cargar_chat_o_404(store, chat_id)
    if chat.get("estado") != "error":
        flash("Solo se pueden reintentar chats con error.", "warning")
    else:
        store.actualizar_chat(
            chat_id,
            {"estado": "pendiente", "intentos": 0, "ia_error": None, "por_revisar": False, "motivo_revision": None},
        )
        store.actualizar_lote(chat["batch_id"], {"estado": "auditando"})
        flash(f"Chat #{chat['conversation_id']} vuelve a la cola.", "success")
    return redirect(url_for("auditoria_chats.ver_lote", lote_id=chat["batch_id"]))


@auditoria_chats_bp.route("/auditoria-chats/lote/<lote_id>/reintentar-errores", methods=["POST"])
def reintentar_errores(lote_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    _cargar_lote_o_404(store, lote_id)
    errores = [c for c in store.listar_chats(lote_id) if c.get("estado") == "error"]
    for chat in errores:
        store.actualizar_chat(
            chat["id"],
            {"estado": "pendiente", "intentos": 0, "ia_error": None, "por_revisar": False, "motivo_revision": None},
        )
    if errores:
        store.actualizar_lote(lote_id, {"estado": "auditando"})
        flash(f"{len(errores)} chats vuelven a la cola. Pulsa «Procesar lote» para auditarlos.", "success")
    return redirect(url_for("auditoria_chats.ver_lote", lote_id=lote_id))


CAMPOS_DIAGNOSTICO_CHAT = (
    "conversation_id", "agente_id", "agente_nombre", "turno", "conversacion_fecha", "estado", "intentos",
    "ia_error", "ia_nota", "ia_satisfaccion", "por_revisar", "motivo_revision", "nota_final", "created_at", "updated_at",
    "detalle", "ia_qa", "ia_estado", "qa_final", "estado_final",
)


@auditoria_chats_bp.route("/auditoria-chats/lote/<lote_id>/diagnostico", methods=["GET"])
def diagnostico(lote_id):
    """JSON para depurar un lote: estados, errores y configuración, sin textos de clientes ni claves."""
    store, _ = _store_o_error()
    if not store:
        abort(404)
    lote = _cargar_lote_o_404(store, lote_id)
    chats = store.listar_chats(lote_id)
    config_ia = obtener_config_ia()

    def chat_diagnostico(chat):
        fila = {campo: chat.get(campo) for campo in CAMPOS_DIAGNOSTICO_CHAT}
        resultado = chat.get("ia_resultado") or {}
        fila["ia_criterios"] = resultado.get("criterios")
        fila["ia_confianza"] = resultado.get("confianza")
        fila["ia_modelo"] = resultado.get("modelo")
        if resultado.get("pauta_version") == PAUTA_VERSION_QA:
            # Solo resultados y códigos: los comentarios de la IA pueden citar al cliente.
            fila["ia_criterios"] = resultados_criterios(resultado)
            fila["ia_fallas"] = [f.get("codigo") for f in resultado.get("fallas_criticas") or []]
            fila["ia_pct_verificable"] = resultado.get("pct_verificable")
            fila["ia_secciones_manual"] = resultado.get("secciones")
            fila["revision"] = chat.get("revision")
        return fila

    datos = {
        "generado_at": datetime.now(timezone.utc).isoformat(),
        "lote": {
            "id": lote.get("id"),
            "etiqueta": lote.get("etiqueta"),
            "desde": _fecha_lote(lote.get("since")),
            "hasta": _fecha_lote(lote.get("until")),
            "estado": lote.get("estado"),
            "modelo_al_crear": lote.get("modelo"),
            "pauta_version": lote.get("pauta_version"),
            "chats_por_agente": lote.get("chats_por_agente"),
            "alcance": lote.get("alcance"),
            "alcance_detalle": lote.get("alcance_detalle"),
            "agentes": lote.get("agentes"),
            "agentes_muestreados": lote.get("agentes_muestreados"),
            "reservas_restantes": {k: len(v or []) for k, v in (lote.get("reservas") or {}).items()},
        },
        "configuracion": {
            "ia_base_url": config_ia["base_url"],
            "ia_modelo": config_ia["model"],
            "ia_modelo_respaldo": config_ia["model_respaldo"],
            "ia_razonamiento": config_ia["razonamiento"],
            "ia_activa": config_ia["activa"],
            "cupo_diario": _cupo_diario(),
            "zona_horaria": _timezone(),
        },
        "progreso": motor._progreso(chats),
        "errores_por_mensaje": _contar_errores(chats),
        "descartes_por_motivo": _contar_descartes(chats),
        "bandejas": _bandejas_para_diagnostico(lote),
        "chats": [chat_diagnostico(c) for c in chats],
    }
    nombre = f"diagnostico_lote_{lote_id[:8]}.json"
    return Response(
        json.dumps(datos, ensure_ascii=False, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


def _contar_descartes(chats):
    conteo = {}
    for chat in chats:
        if chat.get("estado") == "descartado":
            motivo = (chat.get("detalle") or {}).get("motivo_descarte") or "sin_motivo_registrado"
            conteo[motivo] = conteo.get(motivo, 0) + 1
    return conteo


def _bandejas_para_diagnostico(lote):
    """Id, nombre y tipo de cada bandeja (sin teléfonos, tokens ni URLs) y si se usó en el lote."""
    chatwoot, _ = _chatwoot_o_error()
    if not chatwoot:
        return []
    usadas = {int(b) for b in (lote.get("alcance_detalle") or {}).get("bandejas") or []}
    try:
        bandejas = _listar_bandejas(chatwoot)
    except Exception as exc:
        logger.warning("No se pudieron listar las bandejas para el diagnóstico: %s", exc)
        return []
    return [
        {"id": b["id"], "nombre": b["nombre"], "tipo": b["tipo"], "parece_voz": b["es_voz"], "en_lote": b["id"] in usadas}
        for b in bandejas
    ]


def _contar_errores(chats):
    conteo = {}
    for chat in chats:
        if chat.get("ia_error"):
            clave = str(chat["ia_error"])[:160]
            conteo[clave] = conteo.get(clave, 0) + 1
    return conteo


@auditoria_chats_bp.route("/auditoria-chats/lote/<lote_id>/csv", methods=["GET"])
def exportar_csv(lote_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    lote = _cargar_lote_o_404(store, lote_id)
    chatwoot, _ = _chatwoot_o_error()
    columnas, filas = motor.filas_csv(
        lote, store.listar_chats(lote_id), url_conversacion=chatwoot.url_conversacion if chatwoot else None
    )
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(columnas)
    escritor.writerows(filas)

    tz = _obtener_timezone(_timezone())
    desde = datetime.fromtimestamp(int(lote["since"]), tz).date().isoformat()
    hasta = datetime.fromtimestamp(int(lote["until"]), tz).date().isoformat()
    return Response(
        "﻿" + salida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="auditoria_chats_{desde}_{hasta}.csv"'},
    )


@auditoria_chats_bp.route("/auditoria-chats/lote/<lote_id>/borrar", methods=["POST"])
def borrar_lote(lote_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    lote = _cargar_lote_o_404(store, lote_id)
    try:
        store.borrar_lote(lote_id)
        flash(f"Lote «{lote.get('etiqueta')}» borrado. Sus chats podrán volver a elegirse.", "success")
    except AuditoriaChatsError as exc:
        flash(mensaje_error_publico(exc, "No se pudo borrar el lote"), "warning")
    return redirect(url_for("auditoria_chats.index"))


def _desde_historial():
    return (datetime.now(timezone.utc) - timedelta(weeks=SEMANAS_HISTORIAL)).isoformat()


@auditoria_chats_bp.route("/auditoria-chats/historial", methods=["GET"])
def historial():
    store, aviso = _store_o_error()
    filas = []
    if store:
        try:
            filas = motor.historial_semanal(store.chats_para_historial(_desde_historial()), _timezone())
        except AuditoriaChatsError as exc:
            aviso = mensaje_error_publico(exc, "No se pudo leer el historial")

    semanas = sorted({f["semana"] for f in filas})
    agentes = {}
    for fila in filas:
        agentes.setdefault(fila["agente_nombre"], {})[fila["semana"]] = fila
    return render_template(
        "auditoria_chats_historial.html",
        semanas=semanas,
        agentes=sorted(agentes.items(), key=lambda par: motor._normalizar_nombre(par[0])),
        aviso=aviso,
        semanas_historial=SEMANAS_HISTORIAL,
    )
