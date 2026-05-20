import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.break_admin_store import BreakAdminStore, BreakAdminValidationError


class _FakeUpdateQuery:
    def __init__(self, table_name, values):
        self.table_name = table_name
        self.values = values
        self.filters = {}

    def eq(self, key, value):
        self.filters[key] = value
        return self


class _FakeTable:
    def __init__(self, table_name):
        self.table_name = table_name

    def update(self, values):
        return _FakeUpdateQuery(self.table_name, values)


class _FakeClient:
    def table(self, table_name):
        return _FakeTable(table_name)


class FakeBreakAdminStore(BreakAdminStore):
    def __init__(self, reservation, slots, reservations_before, reservations_after=None):
        super().__init__(_FakeClient())
        self._reservation = dict(reservation)
        self._slots = {slot["id"]: dict(slot) for slot in slots}
        self._reservations_before = [dict(item) for item in reservations_before]
        self._reservations_after = [
            dict(item) for item in (reservations_after if reservations_after is not None else reservations_before)
        ]
        self.update_calls = []

    def get_reservation(self, reservation_id):
        if self._reservation["id"] != reservation_id:
            return None
        return dict(self._reservation)

    def get_slot(self, slot_id):
        slot = self._slots.get(slot_id)
        return dict(slot) if slot else None

    def list_reservations(self, reservation_date, shift_id):
        if self.update_calls:
            return [dict(item) for item in self._reservations_after]
        return [dict(item) for item in self._reservations_before]

    def _execute(self, query):
        self.update_calls.append(
            {
                "table": query.table_name,
                "values": dict(query.values),
                "filters": dict(query.filters),
            }
        )
        if query.values.get("slot_id") and query.filters.get("id") == self._reservation["id"]:
            self._reservation["slot_id"] = query.values["slot_id"]
        return None


class BreakAdminStoreTests(unittest.TestCase):
    def test_move_reservation_revierte_si_aparece_sobrecupo_en_post_validacion(self):
        reservation = {
            "id": "res-1",
            "reservation_date": "2026-05-14",
            "shift_id": "shift-1",
            "slot_id": "slot-1",
            "agent_name": "Ana Perez",
        }
        slots = [
            {"id": "slot-1", "shift_id": "shift-1", "max_agents": 2, "is_active": True},
            {"id": "slot-2", "shift_id": "shift-1", "max_agents": 1, "is_active": True},
        ]
        reservations_before = [
            dict(reservation),
        ]
        reservations_after = [
            {**reservation, "slot_id": "slot-2"},
            {
                "id": "res-2",
                "reservation_date": "2026-05-14",
                "shift_id": "shift-1",
                "slot_id": "slot-2",
                "agent_name": "Beto Ruiz",
            },
        ]
        store = FakeBreakAdminStore(
            reservation=reservation,
            slots=slots,
            reservations_before=reservations_before,
            reservations_after=reservations_after,
        )

        with self.assertRaises(BreakAdminValidationError) as error:
            store.move_reservation("res-1", "slot-2")

        self.assertIn("cambió mientras se procesaba", str(error.exception))
        self.assertEqual(
            [
                {
                    "table": "agent_break_reservations",
                    "values": {"slot_id": "slot-2"},
                    "filters": {"id": "res-1"},
                },
                {
                    "table": "agent_break_reservations",
                    "values": {"slot_id": "slot-1"},
                    "filters": {"id": "res-1"},
                },
            ],
            store.update_calls,
        )

    def test_move_reservation_revierte_si_aparece_duplicado_del_agente(self):
        reservation = {
            "id": "res-1",
            "reservation_date": "2026-05-14",
            "shift_id": "shift-1",
            "slot_id": "slot-1",
            "agent_name": "Ana Perez",
        }
        slots = [
            {"id": "slot-1", "shift_id": "shift-1", "max_agents": 2, "is_active": True},
            {"id": "slot-2", "shift_id": "shift-1", "max_agents": 3, "is_active": True},
        ]
        reservations_after = [
            {**reservation, "slot_id": "slot-2"},
            {
                "id": "res-3",
                "reservation_date": "2026-05-14",
                "shift_id": "shift-1",
                "slot_id": "slot-1",
                "agent_name": " ANA   PEREZ ",
            },
        ]
        store = FakeBreakAdminStore(
            reservation=reservation,
            slots=slots,
            reservations_before=[dict(reservation)],
            reservations_after=reservations_after,
        )

        with self.assertRaises(BreakAdminValidationError) as error:
            store.move_reservation("res-1", "slot-2")

        self.assertIn("cambió mientras se procesaba", str(error.exception))
        self.assertEqual("slot-1", store._reservation["slot_id"])


if __name__ == "__main__":
    unittest.main()
