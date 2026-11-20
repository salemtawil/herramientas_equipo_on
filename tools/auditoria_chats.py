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
from utils.auditoria_chats_store import AuditoriaChatsConfigError, AuditoriaChatsError, obtener_store
from utils.auditoria_chats_transcripcion import _etiquetas_adjuntos, mensajes_utiles
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
CUPO_DIARIO_DEFAULT = 20


def _cupo_diario():
    try:
        return max(0, int(os.getenv("AUDITORIA_CHATS_AI_CUPO_DIARIO", CUPO_DIARIO_DEFAULT)))
    except ValueError:
        return CUPO_DIARIO_DEFAULT


PALABRAS_LLAMADAS = ("llamad", "voz", "voice", "call", "telefon", "phone")


def _es_bandeja_de_llamadas(bandeja):
    texto = motor._normalizar_nombre(f"{bandeja.get('name', '')} {bandeja.get('channel_type', '')}")
    return any(palabra in texto for palabra in PALABRAS_LLAMADAS)


def _listar_bandejas(chatwoot):
    """Bandejas de Chatwoot con una marca de si se preseleccionan (las de llamadas no)."""
    listar = getattr(chatwoot, "listar_bandejas", None)
    if not listar:
        return []
    bandejas = []
    for bandeja in listar() or []:
        if bandeja.get("id") is None:
            continue
        tipo = str(bandeja.get("channel_type") or "").replace("Channel::", "")
        bandejas.append(
            {
                "id": int(bandeja["id"]),
                "nombre": bandeja.get("name") or f"Bandeja {bandeja['id']}",
                "tipo": tipo,
                "marcada": not _es_bandeja_de_llamadas(bandeja),
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
    if chatwoot:
        try:
            agentes = sorted(
                motor.resolver_agentes("todos", {}, chatwoot.listar_agentes(), turnos)[0],
                key=lambda a: motor._normalizar_nombre(a["nombre"]),
            )
            grupos, sin_cruce = _agrupar_por_turno(agentes, turnos)
            bandejas = _listar_bandejas(chatwoot)
        except Exception as exc:
            logger.warning("No se pudieron listar los agentes de Chatwoot: %s", exc)
            error_chatwoot = mensaje_error_publico(exc, "No se pudieron listar los agentes de Chatwoot")

    lotes = []
    if store:
        try:
            lotes = store.listar_lotes()
        except AuditoriaChatsError as exc:
            avisos.append(mensaje_error_publico(exc, "No se pudieron leer los lotes guardados"))

    hoy_local = datetime.now(_obtener_timezone(_timezone())).date()
    inicio, fin = motor.rango_semana_anterior(hoy_local, _timezone())
    return render_template(
        "auditoria_chats.html",
        agentes=agentes,
        grupos=grupos,
        sin_cruce=sin_cruce,
        bandejas=bandejas,
        cupo_diario=_cupo_diario(),
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
        puede_crear=bool(store and chatwoot and not error_chatwoot),
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
        disponibles = {b["id"] for b in _listar_bandejas(chatwoot)}
    except Exception as exc:
        flash(mensaje_error_publico(exc, "No se pudieron listar las bandejas de Chatwoot"), "warning")
        return redirect(url_for("auditoria_chats.index"))
    if disponibles:
        bandejas = sorted({int(b) for b in request.form.getlist("bandejas") if str(b).isdigit()} & disponibles)
        if not bandejas:
            flash("Marca al menos una bandeja de entrada de chats.", "warning")
            return redirect(url_for("auditoria_chats.index"))
        detalle["bandejas"] = bandejas

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


def _mensajes_para_vista(mensajes):
    tz = _obtener_timezone(_timezone())
    vista = []
    for mensaje in mensajes_utiles(mensajes):
        es_agente = mensaje.get("message_type") == 1
        remitente = mensaje.get("sender") if isinstance(mensaje.get("sender"), dict) else {}
        vista.append(
            {
                "es_agente": es_agente,
                "autor": remitente.get("name") or ("Agente" if es_agente else "Cliente"),
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

    mensajes, url_chatwoot = [], ""
    chatwoot, error_chatwoot = _chatwoot_o_error()
    if chatwoot:
        url_chatwoot = chatwoot.url_conversacion(chat["conversation_id"])
        try:
            mensajes = _mensajes_para_vista(chatwoot.mensajes_de_conversacion(chat["conversation_id"]))
        except Exception as exc:
            logger.warning("No se pudo leer el chat %s: %s", chat["conversation_id"], exc)
            error_chatwoot = mensaje_error_publico(exc, "No se pudo leer el chat en Chatwoot")

    return render_template(
        "auditoria_chats_chat.html",
        chat=chat,
        lote=lote,
        resultado=chat.get("ia_resultado") or {},
        criterios=CRITERIOS,
        satisfacciones=SATISFACCION,
        mensajes=mensajes,
        error_chatwoot=error_chatwoot,
        url_chatwoot=url_chatwoot,
        siguiente=_siguiente_por_revisar(store, lote["id"], chat["id"]),
    )


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
    flash(f"Chat #{chat['conversation_id']} revisado.", "success")
    siguiente = _siguiente_por_revisar(store, chat["batch_id"], chat_id)
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
        "chats": [chat_diagnostico(c) for c in chats],
    }
    nombre = f"diagnostico_lote_{lote_id[:8]}.json"
    return Response(
        json.dumps(datos, ensure_ascii=False, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


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
