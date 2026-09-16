import unittest
from unittest.mock import patch

import pandas as pd

from app import app
from tools.reporte_agentes import preparar_dataframe
from utils.turnos import obtener_turno


class ReporteAgentesTests(unittest.TestCase):
    def test_preparar_dataframe_consolida_filas_repetidas_por_agente(self):
        df = pd.DataFrame(
            [
                {
                    "First Name": "Maria",
                    "Last Name": "",
                    "Calls": 21,
                    "Outgoing calls": 34,
                    "Missed calls": 3,
                    "Call seconds": 84 * 60,
                    "Outgoing call seconds": 21 * 60,
                    "Worktime": "00:00:01",
                },
                {
                    "First Name": "Maria",
                    "Last Name": "",
                    "Calls": 11,
                    "Outgoing calls": 0,
                    "Missed calls": 0,
                    "Call seconds": 44 * 60,
                    "Outgoing call seconds": 0,
                    "Worktime": "00:00:01",
                },
                {
                    "First Name": "Victoria",
                    "Last Name": "",
                    "Calls": 16,
                    "Outgoing calls": 44,
                    "Missed calls": 2,
                    "Call seconds": 139 * 60,
                    "Outgoing call seconds": 63 * 60,
                    "Worktime": "00:00:01",
                },
                {
                    "First Name": "Victoria",
                    "Last Name": "",
                    "Calls": 17,
                    "Outgoing calls": 23,
                    "Missed calls": 2,
                    "Call seconds": 139 * 60,
                    "Outgoing call seconds": 18 * 60,
                    "Worktime": "00:00:01",
                },
            ]
        )
        turnos = {"Madrugada": ["Maria", "Victoria"]}

        resultado = preparar_dataframe(df, turnos)

        self.assertEqual(2, len(resultado))

        maria = resultado[resultado["Agente"] == "Maria"].iloc[0]
        self.assertEqual("Madrugada", maria["Turno"])
        self.assertEqual(32, maria["Llamadas"])
        self.assertEqual(34, maria["Salientes"])
        self.assertEqual(3, maria["Perdidas"])
        self.assertEqual(128, maria["Mins llamadas"])
        self.assertEqual(21, maria["Mins salientes"])

        victoria = resultado[resultado["Agente"] == "Victoria"].iloc[0]
        self.assertEqual(33, victoria["Llamadas"])
        self.assertEqual(67, victoria["Salientes"])
        self.assertEqual(4, victoria["Perdidas"])
        self.assertEqual(278, victoria["Mins llamadas"])
        self.assertEqual(81, victoria["Mins salientes"])

    def test_turno_prioriza_coincidencia_exacta_antes_de_primer_nombre(self):
        turnos = {
            "Madrugada": ["Maria Rivas"],
            "Shift Leaders": ["Maria Teixeira"],
        }

        self.assertEqual("Madrugada", obtener_turno("Maria Rivas", turnos))
        self.assertEqual("Shift Leaders", obtener_turno("Maria Teixeira", turnos))

    def test_turno_no_usa_primer_nombre_si_es_ambiguo(self):
        turnos = {
            "Madrugada": ["Maria Rivas"],
            "Shift Leaders": ["Maria Teixeira"],
        }

        self.assertEqual("Sin asignar", obtener_turno("Maria Garcia", turnos))

    def test_reporte_chatwoot_ignora_fin_viejo_de_media_noche_sin_confirmacion(self):
        captura = {}

        def fake_obtener_dataframe(*args, **kwargs):
            captura["hora_fin"] = args[2]
            return (
                pd.DataFrame(
                    [
                        {
                            "First Name": "Antonio",
                            "Last Name": "",
                            "Calls": 16,
                            "Outgoing calls": 11,
                            "Missed calls": 1,
                            "Call seconds": 88 * 60,
                            "Outgoing call seconds": 7 * 60,
                            "Worktime": "00:00:01",
                        }
                    ]
                ),
                {
                    "fecha": "2026-09-16",
                    "fecha_fin": "2026-09-16",
                    "tipo_rango": "media_noche",
                    "periodo_fechas": "hoy",
                    "inicio_local": "2026-09-15 21:00:00",
                    "fin_local": "2026-09-16 06:30:59",
                    "fuente": "Chatwoot",
                    "timezone": "America/Caracas",
                    "cantidad_rangos": 1,
                },
            )

        with patch("tools.reporte_agentes.obtener_dataframe_reporte_chatwoot", fake_obtener_dataframe):
            respuesta = app.test_client().post(
                "/reporte-agentes",
                data={
                    "accion": "buscar_chatwoot",
                    "tipo_rango_chatwoot": "media_noche",
                    "periodo_chatwoot": "hoy",
                    "hora_fin_chatwoot": "05:30",
                },
            )

        self.assertEqual(200, respuesta.status_code)
        self.assertEqual("", captura["hora_fin"])

    def test_reporte_chatwoot_respeta_fin_corto_confirmado_en_media_noche(self):
        captura = {}

        def fake_obtener_dataframe(*args, **kwargs):
            captura["hora_fin"] = args[2]
            return (
                pd.DataFrame(
                    [
                        {
                            "First Name": "Antonio",
                            "Last Name": "",
                            "Calls": 9,
                            "Outgoing calls": 11,
                            "Missed calls": 0,
                            "Call seconds": 50 * 60,
                            "Outgoing call seconds": 7 * 60,
                            "Worktime": "00:00:01",
                        }
                    ]
                ),
                {
                    "fecha": "2026-09-16",
                    "fecha_fin": "2026-09-16",
                    "tipo_rango": "media_noche",
                    "periodo_fechas": "hoy",
                    "inicio_local": "2026-09-15 21:00:00",
                    "fin_local": "2026-09-16 05:30:59",
                    "fuente": "Chatwoot",
                    "timezone": "America/Caracas",
                    "cantidad_rangos": 1,
                },
            )

        with patch("tools.reporte_agentes.obtener_dataframe_reporte_chatwoot", fake_obtener_dataframe):
            respuesta = app.test_client().post(
                "/reporte-agentes",
                data={
                    "accion": "buscar_chatwoot",
                    "tipo_rango_chatwoot": "media_noche",
                    "periodo_chatwoot": "hoy",
                    "hora_fin_chatwoot": "05:30",
                    "media_noche_fin_confirmado": "1",
                },
            )

        self.assertEqual(200, respuesta.status_code)
        self.assertEqual("05:30", captura["hora_fin"])


if __name__ == "__main__":
    unittest.main()
