"""Incidencias de chats: revisa los chats de un rango de horas y resalta reportes de clientes y mala atención."""

import csv
import io
import logging
from datetime import date, datetime, time

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for

from tools.auditoria_chats import _listar_bandejas
from utils import incidencias_chats_motor as motor
from utils.chatwoot_reportes import HORARIOS_TURNOS_CHATWOOT, ChatwootClient, _obtener_timezone, _timezone
from utils.errores import mensaje_error_publico
from utils.ia_chat import obtener_config_ia
from utils.incidencias_chats_store import IncidenciasConfigError, IncidenciasError, obtener_store

incidencias_chats_bp = Blueprint("incidencias_chats", __name__)
logger = logging.getLogger(__name__)

MAX_HORAS_PRUEBA = 12
MAX_CHATS_PRUEBA = motor.MAX_CHATS_PRUEBA
MAX_POR = 80
MAX_NOTA = 500
# «No es incidencia» se guarda como `falso_positivo` (valor estable para entrenar un modelo).
DECISIONES = {"atendida": "Atendida", "falso_positivo": "No es incidencia"}
COOKIE_POR = "ic_por"
DIAS_COOKIE_POR = 180
ESTADOS_REVISION = {
    "listando": "Listando chats",
    "evaluando": "Evaluando",
    "completado": "Completada",
    "con_errores": "Completada con errores",
}
TEXTOS_IA = {
    "pendiente": "IA pendiente",
    "procesando": "IA en curso",
    "sin_cupo": "Sin cupo de IA",
    "error": "IA con error",
    "hecha": "Sin veredicto de IA",
}


def obtener_chatwoot():
    return ChatwootClient(timeout=15)


def _store_o_error():
    try:
        return obtener_store(), ""
    except IncidenciasConfigError as exc:
        return None, str(exc)


def _chatwoot_o_error():
    try:
        return obtener_chatwoot(), ""
    except Exception as exc:
        return None, mensaje_error_publico(exc, "Chatwoot no está configurado")


def _quiere_json():
    mejor = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return mejor == "application/json" and request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]


def _tz():
    return _obtener_timezone(_timezone())


def _instante(fecha, hora):
    """Epoch del día y la hora locales del formulario, o None si no son válidos."""
    try:
        dia = date.fromisoformat(str(fecha or "").strip())
        momento = time.fromisoformat(str(hora or "").strip())
    except ValueError:
        return None
    return int(datetime.combine(dia, momento, tzinfo=_tz()).timestamp())


def _fecha_hora(epoch):
    try:
        return datetime.fromtimestamp(int(epoch), _tz()).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _cargar_revision_o_404(store, review_id):
    try:
        revision = store.obtener_revision(review_id)
    except IncidenciasError:
        revision = None
    if not revision:
        abort(404)
    return revision


def _chats_y_decisiones(store, review_id):
    chats = store.listar_chats(review_id)
    con_incidencias = [c["conversation_id"] for c in chats if c.get("incidencias")]
    return chats, (store.decisiones(con_incidencias) if con_incidencias else {})


def _texto_ia(fila):
    confirmada = fila.get("ia_confirmada")
    if confirmada is True:
        return "Confirmada por IA"
    if confirmada is False:
        return "La IA la descarta"
    return TEXTOS_IA.get(fila.get("ia_estado"), "")


def _contexto_revision(revision, chats, decisiones, agente="", clave=""):
    listas = motor.listas_revision(chats, decisiones, agente=agente, clave=clave)
    return {
        "revision": revision,
        "listas": listas,
        "progreso": motor._progreso(chats),
        "estado_texto": ESTADOS_REVISION.get(revision.get("estado"), revision.get("estado") or ""),
        "terminado": revision.get("estado") in motor.ESTADOS_TERMINALES,
        "error_listado": (revision.get("contadores") or {}).get("error_listado") or "",
        "aviso_listado": (revision.get("contadores") or {}).get("aviso_listado") or "",
        "fecha_hora": _fecha_hora,
        "texto_ia": _texto_ia,
        "decisiones_texto": DECISIONES,
        "agente": agente,
        "clave": clave,
    }


# ---------------------------------------------------------------------------
# Inicio y creación
# ---------------------------------------------------------------------------


@incidencias_chats_bp.route("/incidencias-chats/", methods=["GET"])
def index():
    store, error_store = _store_o_error()
    chatwoot, error_chatwoot = _chatwoot_o_error()
    avisos, revisiones, bandejas = [], [], []

    if store:
        try:
            revisiones = store.listar_revisiones(limite=20)
        except IncidenciasError as exc:
            avisos.append(mensaje_error_publico(exc, "No se pudieron leer las revisiones guardadas"))
    preferidas = next((r.get("bandejas") for r in revisiones if r.get("bandejas")), None)

    if chatwoot:
        try:
            bandejas = _listar_bandejas(chatwoot, preferidas=preferidas)
        except Exception as exc:
            logger.warning("No se pudieron listar las bandejas de Chatwoot: %s", exc)
            error_chatwoot = mensaje_error_publico(exc, "No se pudieron listar las bandejas de Chatwoot")

    ahora = datetime.now(_tz())
    return render_template(
        "incidencias_chats.html",
        revisiones=revisiones,
        bandejas=bandejas,
        turnos=HORARIOS_TURNOS_CHATWOOT,
        hoy=ahora.date().isoformat(),
        hora_actual=ahora.strftime("%H:%M"),
        max_horas=motor.MAX_HORAS,
        max_horas_prueba=MAX_HORAS_PRUEBA,
        max_chats_prueba=MAX_CHATS_PRUEBA,
        estados_revision=ESTADOS_REVISION,
        fecha_hora=_fecha_hora,
        creado_por=request.cookies.get(COOKIE_POR, "")[:MAX_POR],
        error_store=error_store,
        error_chatwoot=error_chatwoot,
        ia_activa=obtener_config_ia()["activa"],
        avisos=avisos,
        puede_crear=bool(chatwoot and not error_chatwoot),
    )


def _volver_al_inicio(mensaje):
    flash(mensaje, "warning")
    return redirect(url_for("incidencias_chats.index"))


@incidencias_chats_bp.route("/incidencias-chats/revisiones", methods=["POST"])
def crear():
    prueba = bool(request.form.get("prueba"))
    since = _instante(request.form.get("desde_fecha"), request.form.get("desde_hora"))
    until = _instante(request.form.get("hasta_fecha"), request.form.get("hasta_hora"))
    if since is None or until is None:
        return _volver_al_inicio("Revisa las fechas y horas del rango.")
    if until <= since:
        return _volver_al_inicio("La fecha de fin debe ser posterior a la de inicio.")
    if prueba and until - since > MAX_HORAS_PRUEBA * 3600:
        return _volver_al_inicio(f"En Modo prueba el rango no puede superar las {MAX_HORAS_PRUEBA} horas.")

    chatwoot, error_chatwoot = _chatwoot_o_error()
    if not chatwoot:
        return _volver_al_inicio(error_chatwoot)
    try:
        disponibles = {b["id"] for b in _listar_bandejas(chatwoot)}
    except Exception as exc:
        logger.warning("No se pudieron listar las bandejas de Chatwoot: %s", exc)
        return _volver_al_inicio(mensaje_error_publico(exc, "No se pudieron listar las bandejas de Chatwoot"))
    bandejas = []
    if disponibles:
        bandejas = sorted({int(b) for b in request.form.getlist("bandejas") if str(b).isdigit()} & disponibles)
        if not bandejas:
            return _volver_al_inicio("Marca al menos una bandeja de entrada de chats.")

    if prueba:
        try:
            resultado = motor.revision_en_memoria(
                chatwoot, since=since, until=until, bandejas=bandejas, maximo=MAX_CHATS_PRUEBA
            )
        except ValueError as exc:
            return _volver_al_inicio(str(exc))
        except Exception as exc:
            logger.warning("Falló la revisión en Modo prueba: %s", exc)
            return _volver_al_inicio(mensaje_error_publico(exc, "No se pudieron listar los chats de Chatwoot"))
        return render_template(
            "incidencias_chats_revision.html",
            modo_prueba=True,
            parcial=resultado["parcial"],
            vistos=resultado["vistos"],
            cortado_por_tiempo=resultado["cortado_por_tiempo"],
            evaluados=resultado["evaluados"],
            max_chats_prueba=MAX_CHATS_PRUEBA,
            url_conversacion=chatwoot.url_conversacion,
            por_guardado="",
            **_contexto_revision(resultado["revision"], resultado["chats"], {}),
        )

    store, error_store = _store_o_error()
    if not store:
        return _volver_al_inicio(f"{error_store} Usa el Modo prueba para revisar sin guardar.")
    try:
        revision = motor.crear_revision(
            store,
            since=since,
            until=until,
            bandejas=bandejas,
            usar_ia=bool(request.form.get("usar_ia")),
            creado_por=(request.form.get("creado_por") or "").strip()[:MAX_POR],
        )
    except ValueError as exc:
        return _volver_al_inicio(str(exc))
    except IncidenciasError as exc:
        return _volver_al_inicio(mensaje_error_publico(exc, "No se pudo crear la revisión"))
    return redirect(url_for("incidencias_chats.ver", review_id=revision["id"]))


# ---------------------------------------------------------------------------
# Revisión, pasos y decisiones
# ---------------------------------------------------------------------------


@incidencias_chats_bp.route("/incidencias-chats/revision/<review_id>", methods=["GET"])
def ver(review_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    revision = _cargar_revision_o_404(store, review_id)
    try:
        chats, decisiones = _chats_y_decisiones(store, review_id)
    except IncidenciasError as exc:
        logger.warning("No se pudo leer la revisión de incidencias %s: %s", review_id, exc)
        return _volver_al_inicio(mensaje_error_publico(exc, "No se pudo leer la revisión"))
    chatwoot, _ = _chatwoot_o_error()
    agente = (request.args.get("agente") or "").strip()
    clave = (request.args.get("clave") or "").strip()
    return render_template(
        "incidencias_chats_revision.html",
        modo_prueba=False,
        url_conversacion=chatwoot.url_conversacion if chatwoot else None,
        por_guardado=request.cookies.get(COOKIE_POR, "")[:MAX_POR],
        **_contexto_revision(revision, chats, decisiones, agente=agente, clave=clave),
    )


@incidencias_chats_bp.route("/incidencias-chats/revision/<review_id>/paso", methods=["POST"])
def paso(review_id):
    store, error_store = _store_o_error()
    chatwoot, error_chatwoot = _chatwoot_o_error()
    if not store or not chatwoot:
        resultado = {"accion": "configuracion", "estado": "", "mensaje": error_store or error_chatwoot, "esperar_segundos": 0}
    else:
        try:
            existe = bool(store.obtener_revision(review_id))
        except IncidenciasError:
            existe = False
        if not existe:
            if _quiere_json():
                # «configuracion» detiene el bucle del navegador de inmediato.
                return jsonify({"accion": "configuracion", "estado": "", "mensaje": "La revisión no existe.", "esperar_segundos": 0}), 404
            abort(404)
        try:
            resultado = motor.ejecutar_paso(store, review_id, chatwoot, obtener_config_ia())
        except IncidenciasError as exc:
            logger.warning("Fallo en un paso de incidencias de chats: %s", exc)
            resultado = {
                "accion": "error",
                "estado": "",
                "mensaje": mensaje_error_publico(exc, "No se pudo avanzar la revisión"),
                "esperar_segundos": 10,
            }

    if _quiere_json():
        return jsonify(resultado)
    if resultado.get("mensaje"):
        flash(resultado["mensaje"], "warning" if resultado.get("accion") in ("error", "configuracion") else "success")
    return redirect(url_for("incidencias_chats.ver", review_id=review_id))


def _respuesta_decision(ok, mensaje, review_id, filtros, estado_http=200):
    if _quiere_json():
        return jsonify({"ok": ok, "mensaje": mensaje}), estado_http
    flash(mensaje, "success" if ok else "warning")
    if not review_id:
        return redirect(url_for("incidencias_chats.index"))
    return redirect(url_for("incidencias_chats.ver", review_id=review_id, **filtros))


@incidencias_chats_bp.route("/incidencias-chats/conversacion/<int:conversation_id>/decision", methods=["POST"])
def decidir(conversation_id):
    review_id = (request.form.get("review_id") or "").strip()
    filtros = {k: v for k in ("agente", "clave") if (v := (request.form.get(k) or "").strip())}
    decision = request.form.get("decision") or ""
    por = (request.form.get("por") or "").strip()[:MAX_POR]
    nota = (request.form.get("nota") or "").strip()[:MAX_NOTA]

    store, error_store = _store_o_error()
    if not store:
        return _respuesta_decision(False, error_store, review_id, filtros, 503)
    try:
        revision = store.obtener_revision(review_id) if review_id else None
        pertenece = bool(revision) and any(
            int(c.get("conversation_id") or 0) == conversation_id for c in store.listar_chats(review_id)
        )
    except IncidenciasError as exc:
        return _respuesta_decision(False, mensaje_error_publico(exc, "No se pudo leer la revisión"), review_id, filtros, 503)
    if not pertenece:
        if _quiere_json():
            return jsonify({"ok": False, "mensaje": "Ese chat no pertenece a la revisión."}), 404
        abort(404)
    if decision not in DECISIONES:
        return _respuesta_decision(False, "Elige «Atendida» o «No es incidencia».", review_id, filtros, 400)
    if not por:
        return _respuesta_decision(False, "Escribe tu nombre para guardar la decisión.", review_id, filtros, 400)

    try:
        store.guardar_decision(
            conversation_id, {"decision": decision, "por": por, "nota": nota, "review_id": review_id}
        )
    except IncidenciasError as exc:
        return _respuesta_decision(False, mensaje_error_publico(exc, "No se pudo guardar la decisión"), review_id, filtros, 503)

    respuesta = _respuesta_decision(
        True, f"Chat #{conversation_id}: {DECISIONES[decision]} (por {por}).", review_id, filtros
    )
    if isinstance(respuesta, tuple):
        respuesta = respuesta[0]
    respuesta.set_cookie(COOKIE_POR, por, max_age=DIAS_COOKIE_POR * 86400, samesite="Lax", httponly=True, secure=request.is_secure)
    return respuesta


@incidencias_chats_bp.route("/incidencias-chats/revision/<review_id>/reintentar-errores", methods=["POST"])
def reintentar_errores(review_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    _cargar_revision_o_404(store, review_id)
    try:
        vueltos = motor.reintentar_errores(store, review_id)
    except IncidenciasError as exc:
        logger.warning("No se pudieron reintentar los errores de %s: %s", review_id, exc)
        return _volver_al_inicio(mensaje_error_publico(exc, "No se pudieron reintentar los chats con error"))
    if vueltos:
        flash(f"{vueltos} chats vuelven a la cola.", "success")
    else:
        flash("No hay chats con error para reintentar.", "warning")
    return redirect(url_for("incidencias_chats.ver", review_id=review_id))


@incidencias_chats_bp.route("/incidencias-chats/revision/<review_id>/csv", methods=["GET"])
def exportar_csv(review_id):
    store, _ = _store_o_error()
    if not store:
        abort(404)
    revision = _cargar_revision_o_404(store, review_id)
    try:
        chats, decisiones = _chats_y_decisiones(store, review_id)
    except IncidenciasError as exc:
        logger.warning("No se pudo exportar la revisión de incidencias %s: %s", review_id, exc)
        return _volver_al_inicio(mensaje_error_publico(exc, "No se pudo exportar la revisión"))
    chatwoot, _ = _chatwoot_o_error()
    filas = motor.filas_csv(revision, chats, decisiones, chatwoot.url_conversacion if chatwoot else None)
    salida = io.StringIO()
    csv.writer(salida).writerows(filas)

    tz = _tz()
    desde = datetime.fromtimestamp(int(revision["since"]), tz).strftime("%Y-%m-%d_%H%M")
    hasta = datetime.fromtimestamp(int(revision["until"]), tz).strftime("%Y-%m-%d_%H%M")
    return Response(
        salida.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="incidencias_{desde}_{hasta}.csv"'},
    )
