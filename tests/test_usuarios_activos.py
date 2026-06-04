import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from tools.api_compinche import obtener_diagnostico_promo_compinche
from tools.api_compinche import obtener_metricas_compinche_api


class UsuariosActivosTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_index_renderiza_estado_inicial_util(self):
        estado = [
            {
                "system": "Compinche",
                "active_users": 7,
                "running_users": 4,
                "updated_at": "09:15",
                "progress": "Completado",
                "error": None,
            }
        ]

        with patch(
            "tools.usuarios_activos.obtener_estado_inicial_dashboard",
            return_value={"data": estado, "updated_at": "09:15", "source": "snapshot"},
        ):
            response = self.client.get("/usuarios-activos/")

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("window.__USUARIOS_ACTIVOS_INITIAL_STATE__", html)
        self.assertIn("09:15", html)

    def test_index_no_actualiza_si_no_hay_snapshot(self):
        with patch(
            "tools.servicios_usuarios_activos.cargar_json_temporal",
            return_value=None,
        ), patch(
            "tools.servicios_usuarios_activos.obtener_metricas_compinche_api",
        ) as compinche_api, patch(
            "tools.servicios_usuarios_activos.obtener_metricas_multiadmin",
        ) as multiadmin_api:
            response = self.client.get("/usuarios-activos/")

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('"source": "base"', html.replace("&#34;", '"'))
        compinche_api.assert_not_called()
        multiadmin_api.assert_not_called()

    def test_compinche_calcula_usuarios_activos_con_promo(self):
        usuarios = [
            {
                "phoneNumber": "1",
                "goodStanding": True,
                "status": "start",
                "promo": True,
            },
            {
                "phoneNumber": "2",
                "goodStanding": True,
                "status": "stop",
                "promo": False,
            },
            {
                "phoneNumber": "3",
                "goodStanding": False,
                "status": "start",
                "promo": True,
            },
            {
                "phoneNumber": "4",
                "goodStanding": True,
                "status": "start",
                "promo": True,
            },
        ]
        admins = [{"phoneNumber": "4"}]

        with patch("tools.api_compinche._obtener_data_compinche", return_value=(usuarios, admins)):
            metricas = obtener_metricas_compinche_api()

        self.assertEqual(2, metricas["active_users"])
        self.assertEqual(1, metricas["running_users"])
        self.assertEqual(1, metricas["active_by_promo_users"])

    def test_compinche_diagnostico_promo_no_expone_valores(self):
        usuarios = [
            {
                "phoneNumber": "1",
                "name": "Persona Demo",
                "goodStanding": True,
                "promoCode": "PROMO-SECRETA",
            }
        ]

        with patch("tools.api_compinche._obtener_data_compinche", return_value=(usuarios, [])):
            diagnostico = obtener_diagnostico_promo_compinche()

        self.assertEqual(1, diagnostico["active_by_promo_users_detectado"])
        self.assertEqual(["promoCode"], [item["campo"] for item in diagnostico["campos_promo_detectados"]])
        self.assertNotIn("PROMO-SECRETA", str(diagnostico))
