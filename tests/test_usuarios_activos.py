import os
import sys
import time
import unittest
from unittest.mock import Mock
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from tools import api_multiadmin
from tools import api_compinche
from tools.servicios_usuarios_activos import _aplicar_metricas_multiadmin
from tools.servicios_usuarios_activos import _estado_base
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
            "tools.servicios_usuarios_activos.obtener_metricas_multiadmin",
        ) as multiadmin_api:
            response = self.client.get("/usuarios-activos/")

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn('"source": "base"', html.replace("&#34;", '"'))
        multiadmin_api.assert_not_called()

    def test_multiadmin_resta_offset_admins_a_compinche(self):
        self.assertEqual(5709, api_multiadmin._restar_admins_compinche(5753))
        self.assertEqual(0, api_multiadmin._restar_admins_compinche(12))

    def test_multiadmin_preserva_sistemas_nuevos_con_active_running(self):
        payload = {
            "compinche": {"active": 5753, "running": 717},
            "riderx": {"active": 42, "running": 9},
            "nuevo": {"active": 0, "running": 0},
        }

        with patch("tools.api_multiadmin.requests.get") as request_get:
            response = Mock()
            response.json.return_value = payload
            request_get.return_value = response

            metricas = api_multiadmin.obtener_metricas_multiadmin()

        self.assertEqual(42, metricas["riderx"]["active_users"])
        self.assertEqual(9, metricas["riderx"]["running_users"])
        self.assertEqual("Riderx", metricas["riderx"]["display_name"])
        self.assertEqual(0, metricas["nuevo"]["active_users"])
        self.assertEqual(0, metricas["nuevo"]["running_users"])

    def test_multiadmin_directo_calcula_metricas_desde_usuarios(self):
        ahora_ms = int(time.time() * 1000)
        payloads = {
            "/projects/compinche/users": {
                "Items": [
                    {"goodStanding": True, "status": "start", "standingType": "paid"},
                    {"goodStanding": True, "status": "stop", "standingType": "promo_trial"},
                    {"goodStanding": True, "status": "start", "isAdmin": True},
                    {"goodStanding": False, "status": "start"},
                ]
            },
            "/projects/paripe/users": {"Items": [{"goodStanding": True}, {"goodStanding": False}]},
            "/projects/ready4drive/users": {"Items": [{"goodStanding": True, "status": "start"}]},
            "/projects/shipt/users": {"Items": [{"goodStanding": "true", "status": "START"}]},
            "/projects/veho/users": {"items": [{"goodStanding": True, "status": "stop"}]},
            "/projects/zifty/users": {"Items": [{"goodStanding": 1, "status": "start"}]},
            "/projects/chispita/users": {
                "Items": [
                    {
                        "goodStanding": True,
                        "status": "start",
                        "statusLastTimestampUpdate": ahora_ms,
                        "dexVersion": "1.0",
                        "icEnrolled": True,
                        "services": {"instacart": {"billing": {"goodStanding": True}}},
                    },
                    {
                        "goodStanding": True,
                        "status": "stop",
                        "icEnrolled": True,
                        "services": {"instacart": {"billing": {"goodStanding": False}}},
                    },
                    {
                        "goodStanding": True,
                        "status": "stop",
                        "icEnrolled": True,
                        "services": {"instacart": {"billing": {"goodStanding": True}}},
                    },
                    {
                        "goodStanding": False,
                        "status": "start",
                        "icEnrolled": True,
                        "services": {"instacart": {"billing": {"goodStanding": False}}},
                    },
                ]
            },
            "/projects/chispita/offers/won?period=today": {
                "items": [
                    {"status": "got", "phoneNumber": "1"},
                    {"status": "got", "phoneNumber": "2"},
                    {"status": "lost", "phoneNumber": "3"},
                ]
            },
            "/projects/chispita/offers/won?period=today&app=spark": {
                "items": [{"status": "got", "phoneNumber": "1"}]
            },
            "/projects/chispita/offers/won?period=today&app=instacart": {
                "items": [{"status": "got", "phoneNumber": "2"}]
            },
            "/projects/compinche/bonus": {
                "totalGrossRevenue": 100,
                "goalForBonus": 200,
                "percentageCompleted": 50,
            },
        }

        def request_json(path, _token):
            if path in payloads:
                return payloads[path]
            for key, value in payloads.items():
                if path.startswith(key):
                    return value
            return {}

        with patch("tools.api_multiadmin._obtener_token_multiadmin", return_value="token"), patch(
            "tools.api_multiadmin._request_json_multiadmin",
            side_effect=request_json,
        ), patch(
            "tools.api_multiadmin._obtener_metricas_multiadmin_legacy",
            return_value={"Paripe": {"photo_pool": 12}},
        ):
            metricas = api_multiadmin._obtener_metricas_multiadmin_directo()

        self.assertEqual(2, metricas["Compinche"]["active_users"])
        self.assertEqual(1, metricas["Compinche"]["running_users"])
        self.assertEqual(1, metricas["Compinche"]["active_by_promo_users"])
        self.assertEqual(12, metricas["Paripe"]["photo_pool"])
        self.assertEqual(3, metricas["chispita"]["active_users"])
        self.assertEqual(1, metricas["chispita"]["running_users"])
        self.assertEqual(3, metricas["chispita"]["spark_users"])
        self.assertEqual(1, metricas["chispita"]["spark_running_users"])
        self.assertEqual(1, metricas["chispita"]["spark_disconnected_users"])
        self.assertEqual(2, metricas["chispita"]["instacart_users"])
        self.assertEqual(0, metricas["chispita"]["instacart_running_users"])
        self.assertEqual(2, metricas["chispita"]["instacart_disconnected_users"])
        self.assertEqual(2, metricas["chispita"]["offers_won_today"])
        self.assertEqual(2, metricas["chispita"]["offers_won_today_users"])
        self.assertEqual(1, metricas["chispita"]["spark_offers_won_today"])
        self.assertEqual(1, metricas["chispita"]["spark_offers_won_today_users"])
        self.assertEqual(1, metricas["chispita"]["instacart_offers_won_today"])
        self.assertEqual(1, metricas["chispita"]["instacart_offers_won_today_users"])
        self.assertEqual(
            [
                {"label": "Spark activos", "value": 3},
                {"label": "Instacart activos", "value": 2},
                {"label": "Spark ofertas ganadas hoy", "value": 1},
                {"label": "Instacart ofertas ganadas hoy", "value": 1},
            ],
            metricas["chispita"]["breakdown"],
        )
        self.assertEqual(50.0, metricas["Compinche"]["bonus_stats"]["percentage_completed"])

    def test_multiadmin_actualiza_compinche_con_activos_ajustados(self):
        estado = _estado_base()
        metricas = {
            "Compinche": {"active_users": 5709, "running_users": 717},
            "Paripe": {"good_standing_users": 2873, "photo_pool": 59448},
            "riderx": {"display_name": "Rider X", "active_users": 42, "running_users": 9},
            "chispita": {
                "display_name": "Chispita",
                "active_users": 10,
                "running_users": 4,
                "spark_running_users": 2,
                "instacart_running_users": 1,
                "offers_won_today": 8,
                "offers_won_today_users": 3,
                "breakdown": [
                    {"label": "Spark activos", "value": 6},
                    {"label": "Instacart activos", "value": 4},
                    {"label": "Spark ofertas ganadas hoy", "value": 7},
                    {"label": "Instacart ofertas ganadas hoy", "value": 1},
                ],
            },
        }

        _aplicar_metricas_multiadmin(estado, metricas, "2026-07-11 10:00:00")

        self.assertEqual(5709, estado["Compinche"]["active_users"])
        self.assertEqual(717, estado["Compinche"]["running_users"])
        self.assertIsNone(estado["Compinche"]["active_by_promo_users"])
        self.assertEqual("Completado", estado["Compinche"]["progress"])
        self.assertIsNone(estado["Compinche"]["error"])
        self.assertEqual("Rider X", estado["riderx"]["display_name"])
        self.assertEqual(42, estado["riderx"]["active_users"])
        self.assertEqual(9, estado["riderx"]["running_users"])
        self.assertEqual("Completado", estado["riderx"]["progress"])
        self.assertEqual(
            [
                {"label": "Spark activos", "value": 6},
                {"label": "Instacart activos", "value": 4},
                {"label": "Spark ofertas ganadas hoy", "value": 7},
                {"label": "Instacart ofertas ganadas hoy", "value": 1},
            ],
            estado["chispita"]["breakdown"],
        )
        self.assertEqual(2, estado["chispita"]["spark_running_users"])
        self.assertEqual(1, estado["chispita"]["instacart_running_users"])
        self.assertEqual(8, estado["chispita"]["offers_won_today"])
        self.assertEqual(3, estado["chispita"]["offers_won_today_users"])

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

    def test_compinche_normaliza_good_standing_status_y_telefonos(self):
        usuarios = [
            {
                "phoneNumber": "+58 412-000-0001",
                "goodStanding": "false",
                "status": "start",
                "standingType": "paid",
            },
            {
                "phoneNumber": "+58 412-000-0002",
                "goodStanding": "true",
                "status": " START ",
                "standingType": "promo_trial",
            },
            {
                "phoneNumber": "+58 412-000-0003",
                "goodStanding": "true",
                "status": "start",
                "standingType": "paid",
            },
        ]
        admins = [{"phoneNumber": "584120000003"}]

        with patch("tools.api_compinche._obtener_data_compinche", return_value=(usuarios, admins)), patch(
            "tools.api_compinche._obtener_bonus_stats_compinche",
            return_value=None,
        ):
            metricas = obtener_metricas_compinche_api()

        self.assertEqual(1, metricas["active_users"])
        self.assertEqual(1, metricas["running_users"])
        self.assertEqual(1, metricas["active_by_promo_users"])

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

    def test_compinche_cliente_publico_no_requiere_credenciales_aws(self):
        with patch("tools.api_compinche.boto3.client") as boto_client:
            api_compinche._cliente_cognito()

        kwargs = boto_client.call_args.kwargs
        self.assertEqual("cognito-idp", boto_client.call_args.args[0])
        self.assertEqual(api_compinche.UNSIGNED, kwargs["config"].signature_version)

    def test_compinche_admin_sin_credenciales_muestra_error_accionable(self):
        cognito = Mock()
        cognito.admin_initiate_auth.side_effect = api_compinche.NoCredentialsError()

        with patch.object(api_compinche, "COMPINCHE_USERNAME", "usuario"), patch.object(
            api_compinche,
            "COMPINCHE_PASSWORD",
            "password",
        ), patch.object(
            api_compinche,
            "COMPINCHE_USER_POOL_ID",
            "pool-id",
        ), patch(
            "tools.api_compinche._cliente_cognito",
            return_value=cognito,
        ) as cliente_cognito:
            with self.assertRaisesRegex(RuntimeError, "AWS_ACCESS_KEY_ID"):
                api_compinche._iniciar_sesion_compinche_admin()

        cliente_cognito.assert_called_once_with(requiere_credenciales=True)

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
