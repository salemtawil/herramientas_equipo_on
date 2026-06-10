import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from tools import api_compinche
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
                "standingType": "promo_trial",
            },
            {
                "phoneNumber": "2",
                "goodStanding": True,
                "status": "stop",
                "standingType": "paid",
            },
            {
                "phoneNumber": "3",
                "goodStanding": False,
                "status": "start",
                "standingType": "promo_trial",
            },
            {
                "phoneNumber": "4",
                "goodStanding": True,
                "status": "start",
                "standingType": "promo_trial",
            },
        ]
        admins = [{"phoneNumber": "4"}]

        bonus_stats = {"percentage_completed": 71.2}

        with patch("tools.api_compinche._obtener_data_compinche", return_value=(usuarios, admins)), patch(
            "tools.api_compinche._obtener_bonus_stats_compinche",
            return_value=bonus_stats,
        ):
            metricas = obtener_metricas_compinche_api()

        self.assertEqual(2, metricas["active_users"])
        self.assertEqual(1, metricas["running_users"])
        self.assertEqual(1, metricas["active_by_promo_users"])
        self.assertEqual(bonus_stats, metricas["bonus_stats"])

    def test_compinche_diagnostico_promo_no_expone_valores(self):
        usuarios = [
            {
                "phoneNumber": "1",
                "name": "Persona Demo",
                "goodStanding": True,
                "standingType": "promo_trial",
            }
        ]

        with patch("tools.api_compinche._obtener_data_compinche", return_value=(usuarios, [])):
            diagnostico = obtener_diagnostico_promo_compinche()

        self.assertEqual(1, diagnostico["active_by_promo_users_detectado"])
        self.assertEqual(
            [{"standingType": "promo_trial", "usuarios": 1, "usuarios_activos": 1}],
            diagnostico["standing_type_counts"],
        )
        self.assertNotIn("Persona Demo", str(diagnostico))
        self.assertNotIn("phoneNumber': '1", str(diagnostico))

    def test_compinche_renueva_con_login_si_refresh_expira(self):
        with patch(
            "tools.api_compinche.refrescar_compinche_token",
            side_effect=Exception("Refresh Token has expired"),
        ), patch(
            "tools.api_compinche.iniciar_sesion_compinche",
            return_value={"id_token": "token-nuevo"},
        ):
            token = api_compinche._renovar_token_compinche()

        self.assertEqual("token-nuevo", token)

    def test_compinche_login_usa_admin_si_user_password_auth_no_esta_habilitado(self):
        with patch.object(api_compinche, "COMPINCHE_USERNAME", "usuario"), patch.object(
            api_compinche,
            "COMPINCHE_PASSWORD",
            "password",
        ), patch(
            "tools.api_compinche._iniciar_sesion_compinche_client",
            side_effect=Exception("USER_PASSWORD_AUTH flow not enabled for this client"),
        ), patch(
            "tools.api_compinche._iniciar_sesion_compinche_admin",
            return_value={"id_token": "token-admin"},
        ) as admin_login:
            tokens = api_compinche.iniciar_sesion_compinche()

        self.assertEqual("token-admin", tokens["id_token"])
        admin_login.assert_called_once()

    def test_compinche_obtiene_token_nuevo_si_id_token_esta_vencido(self):
        header = "eyJhbGciOiJub25lIn0"
        payload = (
            api_compinche.base64.urlsafe_b64encode(
                api_compinche.json.dumps({"exp": int(time.time()) - 60}).encode("utf-8")
            )
            .decode("utf-8")
            .rstrip("=")
        )
        token_vencido = f"{header}.{payload}."

        with patch.object(api_compinche, "COMPINCHE_ID_TOKEN", token_vencido), patch.dict(
            api_compinche._TOKEN_CACHE,
            {"id_token": None, "access_token": None, "refresh_token": None},
        ), patch(
            "tools.api_compinche._renovar_token_compinche",
            return_value="token-renovado",
        ) as renovar:
            token = api_compinche._obtener_token_compinche()

        self.assertEqual("token-renovado", token)
        renovar.assert_called_once()
