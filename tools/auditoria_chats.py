"""Auditoría de chats: muestras aleatorias de Chatwoot auditadas con IA y revisadas por una persona."""

import logging
from datetime import date, datetime

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for

from utils import auditoria_chats_motor as motor
from utils.auditoria_chats_store import AuditoriaChatsConfigError, AuditoriaChatsError, obtener_store
from utils.chatwoot_reportes import ChatwootClient, _timezone
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
        return datetime.fromtimestamp(int(epoch)).strftime("%d/%m/%Y")
    except (TypeError, ValueError, OSError):
        return ""


def _quiere_json():
    mejor = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return mejor == "application/json" and request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]


@auditoria_chats_bp.route("/auditoria-chats/", methods=["GET"])
def index():
    store, error_store = _store_o_error()
    config_ia = obtener_config_ia()
    chatwoot, error_chatwoot = _chatwoot_o_error()

    agentes, avisos = [], []
    if chatwoot:
        try:
            agentes = sorted(
                motor.resolver_agentes("todos", {}, chatwoot.listar_agentes(), obtener_turnos_configurados())[0],
                key=lambda a: motor._normalizar_nombre(a["nombre"]),
            )
        except Exception as exc:
            logger.warning("No se pudieron listar los agentes de Chatwoot: %s", exc)
            error_chatwoot = mensaje_error_publico(exc, "No se pudieron listar los agentes de Chatwoot")

    lotes = []
    if store:
        try:
            lotes = store.listar_lotes()
        except AuditoriaChatsError as exc:
            avisos.append(mensaje_error_publico(exc, "No se pudieron leer los lotes guardados"))

    inicio, fin = motor.rango_semana_anterior(date.today(), _timezone())
    return render_template(
        "auditoria_chats.html",
        agentes=agentes,
        turnos=list(obtener_turnos_configurados().keys()),
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
