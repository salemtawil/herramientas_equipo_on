import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for

from utils.turnos_trabajo_store import (
    cargar_estado,
    construir_tablero,
    importar_agents_csv,
    mover_agente,
    obtener_turnos_ordenados,
    set_agente_activo,
)


turnos_trabajo_bp = Blueprint("turnos_trabajo", __name__)
logger = logging.getLogger(__name__)


def limpiar_texto(valor):
    return str(valor or "").strip()


@turnos_trabajo_bp.route("/turnos-trabajo", methods=["GET"])
def turnos_trabajo():
    estado = cargar_estado()
    tablero = construir_tablero(estado)
    turnos = obtener_turnos_ordenados(estado)
    agentes = estado.get("agents", {})
    activos = sum(1 for agente in agentes.values() if agente.get("active", True))
    inactivos = len(agentes) - activos

    return render_template(
        "turnos_trabajo.html",
        tablero=tablero,
        turnos=turnos,
        history=estado.get("history", [])[:15],
        updated_at=estado.get("updated_at", ""),
        total_agentes=len(agentes),
        activos=activos,
        inactivos=inactivos,
    )


@turnos_trabajo_bp.route("/turnos-trabajo/importar", methods=["POST"])
def importar_agentes():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Selecciona un archivo CSV de agentes.", "warning")
        return redirect(url_for("turnos_trabajo.turnos_trabajo"))

    try:
        resultado = importar_agents_csv(archivo)
        flash(
            "CSV importado: "
            f"{resultado['nuevos']} nuevos, "
            f"{resultado['vinculados']} vinculados, "
            f"{resultado['actualizados']} actualizados, "
            f"{resultado['sin_user_id']} sin User ID.",
            "success",
        )
    except Exception as exc:
        logger.exception("Error importando agents.csv")
        flash(f"No se pudo importar el CSV: {exc}", "warning")

    return redirect(url_for("turnos_trabajo.turnos_trabajo"))


@turnos_trabajo_bp.route("/turnos-trabajo/mover", methods=["POST"])
def mover():
    agent_id = limpiar_texto(request.form.get("agent_id"))
    shift_id = limpiar_texto(request.form.get("shift_id"))

    try:
        mover_agente(agent_id, shift_id)
        flash("Agente movido correctamente.", "success")
    except Exception as exc:
        logger.exception("Error moviendo agente")
        flash(f"No se pudo mover el agente: {exc}", "warning")

    return redirect(url_for("turnos_trabajo.turnos_trabajo"))


@turnos_trabajo_bp.route("/turnos-trabajo/agentes/<agent_id>/estado", methods=["POST"])
def cambiar_estado_agente(agent_id):
    active = request.form.get("active") == "1"

    try:
        set_agente_activo(agent_id, active)
        flash("Estado del agente actualizado.", "success")
    except Exception as exc:
        logger.exception("Error actualizando agente")
        flash(f"No se pudo actualizar el agente: {exc}", "warning")

    return redirect(url_for("turnos_trabajo.turnos_trabajo"))
