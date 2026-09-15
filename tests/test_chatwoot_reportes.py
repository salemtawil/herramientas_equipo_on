import os
import unittest
from unittest.mock import patch

from utils.chatwoot_reportes import (
    construir_rango_chatwoot,
    construir_rango_diario,
    obtener_dataframe_reporte_chatwoot,
)


class FakeChatwootClient:
    def __init__(self):
        self.rangos = []

    def listar_agentes(self):
        return [
            {"id": 10, "name": "Ana Perez"},
            {"id": 20, "name": "Luis Gomez"},
        ]

    def resumen_por_agente(self, rango):
        self.rangos.append(rango)
        return [
            {
                "id": 10,
                "conversations_count": 8,
                "resolved_conversations_count": 6,
                "avg_resolution_time": 1800,
            }
        ]

    def mensajes_salientes_por_agente(self, rango):
        self.rangos.append(rango)
        return [
            {"id": 10, "name": "Ana Perez", "outgoing_messages_count": 5},
            {"id": 20, "name": "Luis Gomez", "outgoing_messages_count": 3},
        ]


class ChatwootReportesTests(unittest.TestCase):
    def test_construye_dataframe_compatible_con_reporte_agentes(self):
        cliente = FakeChatwootClient()
        df, metadata = obtener_dataframe_reporte_chatwoot(
            "2026-09-15",
            cliente=cliente,
        )

        self.assertEqual("2026-09-15", metadata["fecha"])
        self.assertEqual("Chatwoot", metadata["fuente"])
        self.assertEqual("2026-09-15 00:00:00", metadata["inicio_local"])
        self.assertEqual(2, len(cliente.rangos))
        self.assertEqual(2, len(df))

        ana = df[df["First Name"] == "Ana"].iloc[0]
        self.assertEqual("Perez", ana["Last Name"])
        self.assertEqual(8, ana["Calls"])
        self.assertEqual(5, ana["Outgoing calls"])
        self.assertEqual(2, ana["Missed calls"])
        self.assertEqual(1800, ana["Call seconds"])
        self.assertEqual("00:00:01", ana["Worktime"])

        luis = df[df["First Name"] == "Luis"].iloc[0]
        self.assertEqual(0, luis["Calls"])
        self.assertEqual(3, luis["Outgoing calls"])

    def test_rango_diario_usa_timezone_configurado(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_diario("2026-09-14")

        self.assertEqual((24 * 60 * 60) - 1, rango.until - rango.since)
        self.assertEqual("UTC", rango.timezone)

    def test_rango_respeta_horas_especificas(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_chatwoot("2026-09-15", "08:30", "16:45")

        self.assertEqual("2026-09-15 08:30:00", rango.inicio_local)
        self.assertEqual("2026-09-15 16:45:59", rango.fin_local)
        self.assertEqual((8 * 60 * 60) + (15 * 60) + 59, rango.until - rango.since)

    def test_rango_rechaza_fin_antes_de_inicio(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            with self.assertRaises(ValueError):
                construir_rango_chatwoot("2026-09-15", "18:00", "08:00")


if __name__ == "__main__":
    unittest.main()
