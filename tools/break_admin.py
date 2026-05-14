import logging
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from utils.break_admin_store import (
    BreakAdminConfigError,
    BreakAdminError,
    BreakAdminStore,
    BreakAdminValidationError,
)

break_admin_bp = Blueprint("break_admin", __name__)
logger = logging.getLogger(__name__)


def obtener_store():
    return BreakAdminStore.from_env()


def limpiar_texto(valor):
    return str(valor or "").strip()


def parsear_entero(valor, nombre, minimo=None):
    texto = limpiar_texto(valor)
    try:
        numero = int(texto)
    except (TypeError, ValueError) as exc:
        raise BreakAdminValidationError(f"{nombre} debe ser un numero entero.") from exc

    if minimo is not None and numero < minimo:
        raise BreakAdminValidationError(f"{nombre} debe ser mayor o igual a {minimo}.")

    return numero


def parsear_fecha(valor):
    texto = limpiar_texto(valor)
    if not texto:
        return date.today().isoformat()

    try:
        return date.fromisoformat(texto).isoformat()
    except ValueError as exc:
        raise BreakAdminValidationError("La fecha seleccionada no es valida.") from exc


def construir_redirect(fecha=None, shift_id=None):
    args = {}
    if fecha:
        args["fecha"] = fecha
    if shift_id:
        args["turno"] = shift_id
    return redirect(url_for("break_admin.break_admin", **args))


def resolver_contexto(store, fecha_param=None, shift_param=None):
    fecha = parsear_fecha(fecha_param)
    shifts = store.list_shifts(include_inactive=True)

    selected_shift_id = limpiar_texto(shift_param)
    if not selected_shift_id and shifts:
        selected_shift_id = next(
            (shift["id"] for shift in shifts if shift.get("is_active")),
            shifts[0]["id"],
        )

    day_view = None
    if selected_shift_id:
        day_view = store.build_shift_day_view(fecha, selected_shift_id)

    slots_for_selected_shift = store.list_slots(
        shift_id=selected_shift_id,
        include_inactive=True,
    ) if selected_shift_id else []

    return {
        "fecha_seleccionada": fecha,
        "shifts": shifts,
        "selected_shift_id": selected_shift_id,
        "day_view": day_view,
        "slots_for_selected_shift": slots_for_selected_shift,
    }


def ejecutar_accion(handler):
    fecha = limpiar_texto(request.form.get("return_date"))
    shift_id = limpiar_texto(request.form.get("return_shift_id"))

    try:
        store = obtener_store()
        handler(store)
        return construir_redirect(fecha=fecha, shift_id=shift_id)
    except BreakAdminValidationError as exc:
        flash(str(exc), "warning")
        return construir_redirect(fecha=fecha, shift_id=shift_id)
    except BreakAdminConfigError as exc:
        flash(str(exc), "warning")
        return construir_redirect(fecha=fecha, shift_id=shift_id)
    except BreakAdminError as exc:
        logger.exception("Error de break_admin")
        flash(str(exc), "warning")
        return construir_redirect(fecha=fecha, shift_id=shift_id)
    except Exception as exc:
        logger.exception("Error inesperado de break_admin")
        flash(f"No se pudo completar la accion: {exc}", "warning")
        return construir_redirect(fecha=fecha, shift_id=shift_id)


@break_admin_bp.route("/break-admin", methods=["GET"])
def break_admin():
    contexto = {
        "fecha_seleccionada": date.today().isoformat(),
        "shifts": [],
        "selected_shift_id": limpiar_texto(request.args.get("turno")),
        "day_view": None,
        "slots_for_selected_shift": [],
        "config_error": "",
    }

    try:
        store = obtener_store()
        contexto.update(
            resolver_contexto(
                store,
                fecha_param=request.args.get("fecha"),
                shift_param=request.args.get("turno"),
            )
        )
    except BreakAdminConfigError as exc:
        contexto["config_error"] = str(exc)
    except BreakAdminValidationError as exc:
        contexto["config_error"] = str(exc)
    except BreakAdminError as exc:
        logger.exception("Error cargando break_admin")
        contexto["config_error"] = str(exc)
    except Exception as exc:
        logger.exception("Error inesperado cargando break_admin")
        contexto["config_error"] = f"No se pudo cargar la vista de breaks: {exc}"

    return render_template("break_admin.html", **contexto)


@break_admin_bp.route("/break-admin/shifts/create", methods=["POST"])
def create_shift():
    def handler(store):
        shift_key = limpiar_texto(request.form.get("shift_key"))
        label = limpiar_texto(request.form.get("label"))
        display_order = parsear_entero(request.form.get("display_order"), "Orden", minimo=0)
        is_active = request.form.get("is_active") == "1"

        if not shift_key:
            raise BreakAdminValidationError("Debes indicar una clave interna para el turno.")
        if not label:
            raise BreakAdminValidationError("Debes indicar un nombre visible para el turno.")

        store.create_shift(
            shift_key=shift_key,
            label=label,
            display_order=display_order,
            is_active=is_active,
        )
        flash("Turno creado correctamente.", "success")

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/shifts/<shift_id>/update", methods=["POST"])
def update_shift(shift_id):
    def handler(store):
        label = limpiar_texto(request.form.get("label"))
        display_order = parsear_entero(request.form.get("display_order"), "Orden", minimo=0)

        if not label:
            raise BreakAdminValidationError("Debes indicar un nombre visible para el turno.")

        store.update_shift(shift_id=shift_id, label=label, display_order=display_order)
        flash("Turno actualizado correctamente.", "success")

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/shifts/<shift_id>/toggle", methods=["POST"])
def toggle_shift(shift_id):
    def handler(store):
        activar = request.form.get("activate") == "1"
        store.set_shift_active(shift_id=shift_id, is_active=activar)
        flash(
            "Turno activado correctamente." if activar else "Turno desactivado correctamente.",
            "success",
        )

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/slots/create", methods=["POST"])
def create_slot():
    def handler(store):
        shift_id = limpiar_texto(request.form.get("shift_id"))
        time_slot = limpiar_texto(request.form.get("time_slot"))
        max_agents = parsear_entero(request.form.get("max_agents"), "Cupo", minimo=1)
        display_order = parsear_entero(request.form.get("display_order"), "Orden", minimo=0)
        is_active = request.form.get("is_active") == "1"

        if not shift_id:
            raise BreakAdminValidationError("Debes seleccionar un turno para crear el horario.")
        if not time_slot:
            raise BreakAdminValidationError("Debes indicar un horario.")

        shift = store.get_shift(shift_id)
        if not shift:
            raise BreakAdminValidationError("El turno seleccionado no existe.")

        store.create_slot(
            shift_id=shift_id,
            time_slot=time_slot,
            max_agents=max_agents,
            display_order=display_order,
            is_active=is_active,
        )
        flash("Horario creado correctamente.", "success")

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/slots/<slot_id>/update", methods=["POST"])
def update_slot(slot_id):
    def handler(store):
        time_slot = limpiar_texto(request.form.get("time_slot"))
        max_agents = parsear_entero(request.form.get("max_agents"), "Cupo", minimo=1)
        display_order = parsear_entero(request.form.get("display_order"), "Orden", minimo=0)

        if not time_slot:
            raise BreakAdminValidationError("Debes indicar un horario.")

        store.update_slot(
            slot_id=slot_id,
            time_slot=time_slot,
            max_agents=max_agents,
            display_order=display_order,
        )
        flash("Horario actualizado correctamente.", "success")

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/slots/<slot_id>/toggle", methods=["POST"])
def toggle_slot(slot_id):
    def handler(store):
        activar = request.form.get("activate") == "1"
        store.set_slot_active(slot_id=slot_id, is_active=activar)
        flash(
            "Horario activado correctamente." if activar else "Horario desactivado correctamente.",
            "success",
        )

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/reservations/<reservation_id>/delete", methods=["POST"])
def delete_reservation(reservation_id):
    def handler(store):
        store.delete_reservation(reservation_id)
        flash("Reserva eliminada correctamente.", "success")

    return ejecutar_accion(handler)


@break_admin_bp.route("/break-admin/reservations/<reservation_id>/move", methods=["POST"])
def move_reservation(reservation_id):
    def handler(store):
        new_slot_id = limpiar_texto(request.form.get("new_slot_id"))
        if not new_slot_id:
            raise BreakAdminValidationError("Debes seleccionar un horario destino.")

        store.move_reservation(reservation_id=reservation_id, new_slot_id=new_slot_id)
        flash("Reserva movida correctamente.", "success")

    return ejecutar_accion(handler)
