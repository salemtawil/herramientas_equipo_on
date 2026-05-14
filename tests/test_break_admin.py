import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app


class FakeBreakAdminStore:
    def __init__(self):
        self.move_calls = []

    def list_shifts(self, include_inactive=True):
        return [
            {
                "id": "shift-1",
                "shift_key": "morning",
                "label": "Turno manana",
                "is_active": True,
                "display_order": 0,
            }
        ]

    def build_shift_day_view(self, reservation_date, shift_id):
        return {
            "shift": {
                "id": "shift-1",
                "shift_key": "morning",
                "label": "Turno manana",
                "is_active": True,
                "display_order": 0,
            },
            "slots": [
                {
                    "id": "slot-1",
                    "shift_id": "shift-1",
                    "time_slot": "10:30 AM",
                    "max_agents": 2,
                    "is_active": True,
                    "display_order": 0,
                }
            ],
            "reservations": [
                {
                    "id": "res-1",
                    "reservation_date": reservation_date,
                    "shift_id": shift_id,
                    "slot_id": "slot-1",
                    "agent_name": "Ana Perez",
                    "created_at": "2026-05-14T10:00:00+00:00",
                }
            ],
            "rows": [
                {
                    "slot": {
                        "id": "slot-1",
                        "shift_id": "shift-1",
                        "time_slot": "10:30 AM",
                        "max_agents": 2,
                        "is_active": True,
                        "display_order": 0,
                    },
                    "reservations": [
                        {
                            "id": "res-1",
                            "reservation_date": reservation_date,
                            "shift_id": shift_id,
                            "slot_id": "slot-1",
                            "agent_name": "Ana Perez",
                            "created_at": "2026-05-14T10:00:00+00:00",
                        }
                    ],
                    "taken": 1,
                    "remaining": 1,
                    "is_full": False,
                }
            ],
        }

    def list_slots(self, shift_id=None, include_inactive=True):
        return [
            {
                "id": "slot-1",
                "shift_id": "shift-1",
                "time_slot": "10:30 AM",
                "max_agents": 2,
                "is_active": True,
                "display_order": 0,
            },
            {
                "id": "slot-2",
                "shift_id": "shift-1",
                "time_slot": "11:00 AM",
                "max_agents": 2,
                "is_active": True,
                "display_order": 1,
            },
        ]

    def move_reservation(self, reservation_id, new_slot_id):
        self.move_calls.append((reservation_id, new_slot_id))


class BreakAdminTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_break_admin_renderiza_vista_principal(self):
        fake_store = FakeBreakAdminStore()

        with patch("tools.break_admin.obtener_store", return_value=fake_store):
            response = self.client.get("/break-admin?fecha=2026-05-14&turno=shift-1")

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Admin de breaks reservables", html)
        self.assertIn("Turno manana", html)
        self.assertIn("Ana Perez", html)
        self.assertIn("10:30 AM", html)

    def test_move_reservation_redirige_y_ejecuta_accion(self):
        fake_store = FakeBreakAdminStore()

        with patch("tools.break_admin.obtener_store", return_value=fake_store):
            response = self.client.post(
                "/break-admin/reservations/res-1/move",
                data={
                    "return_date": "2026-05-14",
                    "return_shift_id": "shift-1",
                    "new_slot_id": "slot-2",
                },
            )

        self.assertEqual(302, response.status_code)
        self.assertEqual([("res-1", "slot-2")], fake_store.move_calls)
        self.assertIn("/break-admin?fecha=2026-05-14&turno=shift-1", response.location)


if __name__ == "__main__":
    unittest.main()
