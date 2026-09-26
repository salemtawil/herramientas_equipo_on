import json
import re
import unittest
from unittest.mock import patch

import requests

from app import app
from utils.errores import MENSAJE_DETALLE_EN_LOGS, mensaje_error_publico


def _html_reporte_con_ranking(valor_json):
    """Renderiza /reporte-agentes (GET real) inyectando ranking_completo_json."""
    import tools.reporte_agentes as reporte_agentes

    render_original = reporte_agentes.render_template

    def render_con_ranking(nombre, **contexto):
        contexto["ranking_completo_json"] = valor_json
        return render_original(nombre, **contexto)

    with patch.object(reporte_agentes, "render_template", side_effect=render_con_ranking):
        respuesta = app.test_client().get("/reporte-agentes")
    assert respuesta.status_code == 200
    return respuesta.get_data(as_text=True)


def _literal_ranking(html):
    linea = next(l for l in html.splitlines() if "const rankingData" in l)
    return linea, re.search(r"JSON\.parse\((.*)\);", linea).group(1)


class RankingJsonSeguroTests(unittest.TestCase):
    def test_ranking_con_cierre_de_script_no_rompe_el_bloque(self):
        payload = "</script><script>alert('xss')</script>"
        ranking = [{"agente": payload, "turno": "Mañana", "puntaje": 1}]
        html = _html_reporte_con_ranking(json.dumps(ranking, ensure_ascii=False))

        linea, literal = _literal_ranking(html)
        self.assertNotIn("</script>", linea)
        self.assertNotIn("<script>", linea)
        self.assertNotIn(payload, html)
        self.assertEqual(ranking, json.loads(json.loads(literal)))

    def test_ranking_vacio_usa_lista_vacia(self):
        _, literal = _literal_ranking(_html_reporte_con_ranking(""))
        self.assertEqual([], json.loads(json.loads(literal)))


class LimiteSubidaTests(unittest.TestCase):
    def setUp(self):
        self.limite_original = app.config["MAX_CONTENT_LENGTH"]
        app.config["MAX_CONTENT_LENGTH"] = 1024
        self.client = app.test_client()

    def tearDown(self):
        app.config["MAX_CONTENT_LENGTH"] = self.limite_original

    def test_formulario_html_devuelve_413_con_mensaje(self):
        respuesta = self.client.post(
            "/comparar-csv",
            data={"archivo": "x" * 4096},
            headers={"Accept": "text/html"},
        )
        self.assertEqual(413, respuesta.status_code)
        texto = respuesta.get_data(as_text=True)
        self.assertIn("Archivo demasiado grande", texto)
        self.assertIn("supera el límite permitido", texto)

    def test_ruta_json_devuelve_413_json(self):
        respuesta = self.client.post(
            "/comparar-csv",
            data={"archivo": "x" * 4096},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(413, respuesta.status_code)
        data = respuesta.get_json()
        self.assertFalse(data["success"])
        self.assertIn("supera el límite permitido", data["error"])

    def test_valor_por_defecto_es_50_mb(self):
        self.assertEqual(50 * 1024 * 1024, self.limite_original)


class MensajeErrorPublicoTests(unittest.TestCase):
    def test_muestra_mensajes_de_validacion_propios(self):
        texto = mensaje_error_publico(ValueError("Falta la columna Calls."), "No se pudo procesar")
        self.assertEqual("No se pudo procesar: Falta la columna Calls.", texto)

    def test_oculta_errores_de_red_con_urls(self):
        exc = requests.exceptions.ConnectionError(
            "HTTPSConnectionPool(host='script.google.com'): /macros/s/SECRETO/exec"
        )
        texto = mensaje_error_publico(exc, "No se pudo procesar")
        self.assertNotIn("SECRETO", texto)
        self.assertIn(MENSAJE_DETALLE_EN_LOGS, texto)

    def test_oculta_excepciones_inesperadas(self):
        texto = mensaje_error_publico(KeyError("service_role_key=abc"), "No se pudo procesar")
        self.assertNotIn("abc", texto)


class ErroresSinDetalleInternoTests(unittest.TestCase):
    def test_promo_diagnostico_no_expone_la_excepcion(self):
        with patch(
            "tools.usuarios_activos.obtener_diagnostico_promo_compinche",
            side_effect=RuntimeError("token=eyJ-secreto"),
        ):
            respuesta = app.test_client().get("/usuarios-activos/compinche/promo-diagnostico")
        self.assertEqual(500, respuesta.status_code)
        data = respuesta.get_json()
        self.assertEqual({"success", "error"}, set(data))
        self.assertFalse(data["success"])
        self.assertNotIn("secreto", data["error"])

    def test_apps_script_no_expone_url_del_webhook(self):
        from tools import usuarios_a_sheets

        url = "https://script.google.com/macros/s/ID-PRIVADO/exec"
        env = {"APPS_SCRIPT_WEBHOOK_URL": url, "APPS_SCRIPT_WEBHOOK_TOKEN": "tok-privado"}
        error = requests.exceptions.ConnectionError(f"Max retries exceeded with url: {url}")
        with patch.dict("os.environ", env), patch.object(
            usuarios_a_sheets.requests, "post", side_effect=error
        ), self.assertLogs(usuarios_a_sheets.logger, level="WARNING") as logs:
            with self.assertRaises(RuntimeError) as ctx:
                usuarios_a_sheets.enviar_a_apps_script(
                    usuarios_a_sheets.pd.DataFrame([{"a": 1}]),
                    "Prueba",
                )
        self.assertNotIn("ID-PRIVADO", str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)
        self.assertNotIn("ID-PRIVADO", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
