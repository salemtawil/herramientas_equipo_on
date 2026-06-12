import io
import os
import sys
import unittest
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from tools.informe_semanal_cs import (
    REPORT_SECTIONS,
    build_weekly_report_prompt,
    extract_text_from_files,
    extraer_texto_respuesta_gemini,
    generate_weekly_report_gemini,
    generate_weekly_report_openai,
)


class InformeSemanalCsTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_prompt_incluye_estructura_obligatoria(self):
        prompt = build_weekly_report_prompt(
            {
                "nombre_informe": "Informe demo",
                "periodo": "Semana 1",
                "informe_anterior": "",
                "bitacora": "Se atendieron incidencias de usuarios.",
                "archivos_adicionales": "",
                "notas": "",
            }
        )

        for section in REPORT_SECTIONS:
            self.assertIn(section, prompt)
        self.assertIn("No inventes datos", prompt)
        self.assertIn("La sección \"CSAT", prompt)

    def test_post_genera_base_editable_sin_ia(self):
        with patch.dict(os.environ, {"WEEKLY_REPORT_AI_PROVIDER": "none"}, clear=False):
            response = self.client.post(
                "/informe-semanal-cs",
                data={
                    "nombre_informe": "Informe semanal",
                    "periodo": "03 al 09 de junio",
                    "bitacora": "Se atendieron solicitudes operativas y quedó pendiente revisar NPS.",
                    "informe_anterior": "",
                    "notas": "",
                },
            )

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Informe generado", html)
        self.assertIn("Actividades en la semana", html)
        self.assertIn("Conclusión ejecutiva", html)

    def test_post_acepta_archivo_de_bitacora(self):
        contenido = "Incidencia desde archivo de bitacora para organizar en el informe."

        with patch.dict(os.environ, {"WEEKLY_REPORT_AI_PROVIDER": "none"}, clear=False):
            response = self.client.post(
                "/informe-semanal-cs",
                data={
                    "nombre_informe": "Informe semanal",
                    "periodo": "03 al 09 de junio",
                    "bitacora": "",
                    "bitacora_archivo": (
                        io.BytesIO(contenido.encode("utf-8")),
                        "bitacora.txt",
                    ),
                    "informe_anterior": "",
                    "notas": "",
                },
                content_type="multipart/form-data",
            )

        html = response.get_data(as_text=True)
        self.assertEqual(200, response.status_code)
        self.assertIn("Informe generado", html)
        self.assertIn("Incidencia desde archivo", html)

    def test_extrae_archivo_de_bitacora_mayor_a_veinte_mb(self):
        contenido = ("Dato operativo de bitacora.\n" * 900000).encode("utf-8")

        texto, warnings = extract_text_from_files(
            [
                FileStorage(
                    stream=io.BytesIO(contenido),
                    filename="bitacora.txt",
                )
            ]
        )

        self.assertFalse(warnings)
        self.assertIn("Dato operativo de bitacora", texto)

    def test_openai_429_devuelve_error_funcional(self):
        class FakeResponse:
            status_code = 429

            def raise_for_status(self):
                raise AssertionError("No debe llegar a raise_for_status")

        with patch("tools.informe_semanal_cs.requests.post", return_value=FakeResponse()):
            with self.assertRaises(ValueError) as error:
                generate_weekly_report_openai(
                    "prompt de prueba",
                    {
                        "api_key": "sk-proj-test",
                        "openai_model": "gpt-4.1-mini",
                    },
                )

        self.assertIn("cuota", str(error.exception))

    def test_extrae_texto_respuesta_gemini(self):
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Informe generado"},
                            {"text": " con Gemini"},
                        ]
                    }
                }
            ]
        }

        self.assertEqual("Informe generado\n con Gemini", extraer_texto_respuesta_gemini(data))

    def test_gemini_429_devuelve_error_funcional(self):
        class FakeResponse:
            status_code = 429

            def raise_for_status(self):
                raise AssertionError("No debe llegar a raise_for_status")

        with patch("tools.informe_semanal_cs.requests.post", return_value=FakeResponse()):
            with self.assertRaises(ValueError) as error:
                generate_weekly_report_gemini(
                    "prompt de prueba",
                    {
                        "gemini_api_key": "gemini-test",
                        "gemini_model": "gemini-2.5-flash",
                    },
                )

        self.assertIn("cuota", str(error.exception))


if __name__ == "__main__":
    unittest.main()
