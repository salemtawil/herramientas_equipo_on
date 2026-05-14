import os
from collections import defaultdict


class BreakAdminError(Exception):
    pass


class BreakAdminConfigError(BreakAdminError):
    pass


class BreakAdminValidationError(BreakAdminError):
    pass


class BreakAdminStore:
    def __init__(self, client):
        self.client = client

    @classmethod
    def from_env(cls):
        try:
            from supabase import create_client
        except ImportError as exc:
            raise BreakAdminConfigError(
                "La dependencia 'supabase' no esta instalada en el entorno."
            ) from exc

        url = (os.getenv("SUPABASE_URL") or "").strip()
        service_role_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

        if not url:
            raise BreakAdminConfigError("No esta configurada la variable SUPABASE_URL.")
        if not service_role_key:
            raise BreakAdminConfigError(
                "No esta configurada la variable SUPABASE_SERVICE_ROLE_KEY."
            )

        return cls(create_client(url, service_role_key))

    def _execute(self, query):
        try:
            return query.execute()
        except Exception as exc:
            mensaje = str(exc)
            if self._es_error_duplicado(mensaje):
                raise BreakAdminValidationError("El registro ya existe con esos datos.") from exc
            raise BreakAdminError(f"No se pudo consultar Supabase: {mensaje}") from exc

    @staticmethod
    def _obtener_data(response):
        data = getattr(response, "data", None)
        if data is None:
            return []
        return data

    @staticmethod
    def _primer_registro(response):
        data = getattr(response, "data", None)
        if not data:
            return None
        return data[0]

    @staticmethod
    def _es_error_duplicado(mensaje):
        mensaje_norm = str(mensaje or "").lower()
        return "duplicate key" in mensaje_norm or "unique constraint" in mensaje_norm

    @staticmethod
    def _normalizar_nombre_agente(valor):
        return " ".join(str(valor or "").strip().lower().split())

    def list_shifts(self, include_inactive=True):
        query = self.client.table("agent_break_shifts").select("*").order("display_order").order("label")
        if not include_inactive:
            query = query.eq("is_active", True)
        return self._obtener_data(self._execute(query))

    def get_shift(self, shift_id):
        query = self.client.table("agent_break_shifts").select("*").eq("id", shift_id).limit(1)
        return self._primer_registro(self._execute(query))

    def create_shift(self, shift_key, label, display_order, is_active=True):
        payload = {
            "shift_key": shift_key,
            "label": label,
            "display_order": display_order,
            "is_active": is_active,
        }
        self._execute(self.client.table("agent_break_shifts").insert(payload))

    def update_shift(self, shift_id, label, display_order):
        if not self.get_shift(shift_id):
            raise BreakAdminValidationError("El turno indicado no existe.")

        query = (
            self.client.table("agent_break_shifts")
            .update({"label": label, "display_order": display_order})
            .eq("id", shift_id)
        )
        self._execute(query)

    def set_shift_active(self, shift_id, is_active):
        if not self.get_shift(shift_id):
            raise BreakAdminValidationError("El turno indicado no existe.")

        query = (
            self.client.table("agent_break_shifts")
            .update({"is_active": is_active})
            .eq("id", shift_id)
        )
        self._execute(query)

    def list_slots(self, shift_id=None, include_inactive=True):
        query = self.client.table("agent_break_slots").select("*").order("display_order").order("time_slot")
        if shift_id:
            query = query.eq("shift_id", shift_id)
        if not include_inactive:
            query = query.eq("is_active", True)
        return self._obtener_data(self._execute(query))

    def get_slot(self, slot_id):
        query = self.client.table("agent_break_slots").select("*").eq("id", slot_id).limit(1)
        return self._primer_registro(self._execute(query))

    def create_slot(self, shift_id, time_slot, max_agents, display_order, is_active=True):
        payload = {
            "shift_id": shift_id,
            "time_slot": time_slot,
            "max_agents": max_agents,
            "display_order": display_order,
            "is_active": is_active,
        }
        try:
            self._execute(self.client.table("agent_break_slots").insert(payload))
        except BreakAdminValidationError as exc:
            raise BreakAdminValidationError(
                "Ya existe un horario con ese nombre dentro del turno."
            ) from exc

    def update_slot(self, slot_id, time_slot, max_agents, display_order):
        if not self.get_slot(slot_id):
            raise BreakAdminValidationError("El horario indicado no existe.")

        query = (
            self.client.table("agent_break_slots")
            .update(
                {
                    "time_slot": time_slot,
                    "max_agents": max_agents,
                    "display_order": display_order,
                }
            )
            .eq("id", slot_id)
        )
        try:
            self._execute(query)
        except BreakAdminValidationError as exc:
            raise BreakAdminValidationError(
                "Ya existe otro horario con ese nombre dentro del turno."
            ) from exc

    def set_slot_active(self, slot_id, is_active):
        if not self.get_slot(slot_id):
            raise BreakAdminValidationError("El horario indicado no existe.")

        query = (
            self.client.table("agent_break_slots")
            .update({"is_active": is_active})
            .eq("id", slot_id)
        )
        self._execute(query)

    def list_reservations(self, reservation_date, shift_id):
        query = (
            self.client.table("agent_break_reservations")
            .select("*")
            .eq("reservation_date", reservation_date)
            .eq("shift_id", shift_id)
            .order("created_at")
        )
        return self._obtener_data(self._execute(query))

    def get_reservation(self, reservation_id):
        query = self.client.table("agent_break_reservations").select("*").eq("id", reservation_id).limit(1)
        return self._primer_registro(self._execute(query))

    def delete_reservation(self, reservation_id):
        if not self.get_reservation(reservation_id):
            raise BreakAdminValidationError("La reserva indicada no existe.")
        query = self.client.table("agent_break_reservations").delete().eq("id", reservation_id)
        self._execute(query)

    def move_reservation(self, reservation_id, new_slot_id):
        reservation = self.get_reservation(reservation_id)
        if not reservation:
            raise BreakAdminValidationError("La reserva indicada no existe.")

        slot_destino = self.get_slot(new_slot_id)
        if not slot_destino:
            raise BreakAdminValidationError("El horario destino no existe.")
        if slot_destino["shift_id"] != reservation["shift_id"]:
            raise BreakAdminValidationError("El horario destino no pertenece al mismo turno.")
        if not slot_destino.get("is_active", True):
            raise BreakAdminValidationError("El horario destino esta inactivo.")

        reservations = self.list_reservations(
            reservation_date=reservation["reservation_date"],
            shift_id=reservation["shift_id"],
        )
        ocupacion_destino = sum(
            1
            for item in reservations
            if item["slot_id"] == new_slot_id and item["id"] != reservation_id
        )
        if ocupacion_destino >= int(slot_destino.get("max_agents") or 0):
            raise BreakAdminValidationError("El horario destino ya esta lleno.")

        agente_objetivo = self._normalizar_nombre_agente(reservation.get("agent_name"))
        duplicado = any(
            item["id"] != reservation_id
            and self._normalizar_nombre_agente(item.get("agent_name")) == agente_objetivo
            for item in reservations
        )
        if duplicado:
            raise BreakAdminValidationError(
                "Ese agente ya tiene una reserva en ese turno para la fecha seleccionada."
            )

        query = (
            self.client.table("agent_break_reservations")
            .update({"slot_id": new_slot_id})
            .eq("id", reservation_id)
        )
        self._execute(query)

    def build_shift_day_view(self, reservation_date, shift_id):
        shift = self.get_shift(shift_id)
        if not shift:
            raise BreakAdminValidationError("El turno seleccionado no existe.")

        slots = self.list_slots(shift_id=shift_id, include_inactive=True)
        reservations = self.list_reservations(reservation_date=reservation_date, shift_id=shift_id)

        reservations_by_slot = defaultdict(list)
        for reservation in reservations:
            reservations_by_slot[reservation["slot_id"]].append(reservation)

        rows = []
        for slot in slots:
            asignados = reservations_by_slot.get(slot["id"], [])
            rows.append(
                {
                    "slot": slot,
                    "reservations": asignados,
                    "taken": len(asignados),
                    "remaining": max(int(slot.get("max_agents") or 0) - len(asignados), 0),
                    "is_full": len(asignados) >= int(slot.get("max_agents") or 0),
                }
            )

        return {
            "shift": shift,
            "slots": slots,
            "reservations": reservations,
            "rows": rows,
        }
