import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app


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
