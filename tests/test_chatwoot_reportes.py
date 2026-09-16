import os
import unittest
from unittest.mock import patch

from utils.chatwoot_reportes import (
    ChatwootClient,
    construir_rango_chatwoot_fechas,
    construir_rango_chatwoot,
    construir_rango_diario,
    construir_rango_media_noche,
    obtener_dataframe_reporte_chatwoot,
    resolver_fechas_periodo,
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
        return []

    def mensajes_salientes_por_agente(self, rango):
        self.rangos.append(rango)
        return []

    def estadisticas_llamadas(self, rango, group_by="agent"):
        self.rangos.append(rango)
        return {
            "rows": [
                {
                    "id": 10,
                    "name": "Ana Perez",
                    "callsAnswered": 8,
                    "missedCalls": 2,
                    "callMinutes": 30.5,
                    "outboundCalls": 5,
                    "outboundCallMinutes": 12.25,
                    "notes": 4,
                    "resolvedConversations": 6,
                },
                {
                    "id": 20,
                    "name": "Luis Gomez",
                    "callsAnswered": 0,
                    "missedCalls": 0,
                    "callMinutes": 0,
                    "outboundCalls": 3,
                    "outboundCallMinutes": 2.5,
                    "notes": 1,
                    "resolvedConversations": 0,
                },
            ],
            "totals": {
                "receivedCalls": 10,
                "callsAnswered": 8,
                "missedCalls": 2,
                "outboundCalls": 8,
            },
        }


class FakeSnakeCaseChatwootClient(FakeChatwootClient):
    def estadisticas_llamadas(self, rango, group_by="agent"):
        self.rangos.append(rango)
        return {
            "rows": [
                {
                    "agent_id": 10,
                    "name": "Ana Perez",
                    "calls_answered": 4,
                    "missed_calls": 1,
                    "call_minutes": 9.5,
                    "outbound_calls": 2,
                    "outbound_call_minutes": 3.25,
                }
            ],
            "totals": {
                "received_calls": 5,
                "calls_answered": 4,
                "missed_calls": 1,
                "outbound_calls": 2,
            },
        }


class FakeAlternateMissedChatwootClient(FakeChatwootClient):
    def estadisticas_llamadas(self, rango, group_by="agent"):
        self.rangos.append(rango)
        return {
            "rows": [
                {
                    "agent_id": 10,
                    "name": "Ana Perez",
                    "calls_answered": 4,
                    "calls_missed": 2,
                    "call_minutes": 9.5,
                    "outbound_calls": 2,
                    "outbound_call_minutes": 3.25,
                },
                {
                    "agent_id": 20,
                    "name": "Luis Gomez",
                    "calls_answered": 3,
                    "unattended_calls": 1,
                    "call_minutes": 8,
                    "outbound_calls": 1,
                    "outbound_call_minutes": 1.5,
                },
            ],
        }


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
        self.assertEqual(1, len(cliente.rangos))
        self.assertEqual(2, len(df))

        ana = df[df["First Name"] == "Ana"].iloc[0]
        self.assertEqual("Perez", ana["Last Name"])
        self.assertEqual(8, ana["Calls"])
        self.assertEqual(5, ana["Outgoing calls"])
        self.assertEqual(2, ana["Missed calls"])
        self.assertEqual(1830, ana["Call seconds"])
        self.assertEqual(735, ana["Outgoing call seconds"])
        self.assertEqual("00:00:01", ana["Worktime"])

        luis = df[df["First Name"] == "Luis"].iloc[0]
        self.assertEqual(0, luis["Calls"])
        self.assertEqual(3, luis["Outgoing calls"])
        self.assertEqual(150, luis["Outgoing call seconds"])

    def test_construye_dataframe_con_respuesta_snake_case_de_chatwoot(self):
        cliente = FakeSnakeCaseChatwootClient()
        df, _metadata = obtener_dataframe_reporte_chatwoot(
            "2026-09-15",
            cliente=cliente,
        )

        self.assertEqual(1, len(df))
        ana = df.iloc[0]
        self.assertEqual("Ana", ana["First Name"])
        self.assertEqual("Perez", ana["Last Name"])
        self.assertEqual(4, ana["Calls"])
        self.assertEqual(2, ana["Outgoing calls"])
        self.assertEqual(1, ana["Missed calls"])
        self.assertEqual(570, ana["Call seconds"])
        self.assertEqual(195, ana["Outgoing call seconds"])

    def test_dataframe_chatwoot_reconoce_variantes_de_perdidas_sin_sumarlas_a_llamadas(self):
        cliente = FakeAlternateMissedChatwootClient()
        df, _metadata = obtener_dataframe_reporte_chatwoot(
            "2026-09-15",
            cliente=cliente,
        )

        ana = df[df["First Name"] == "Ana"].iloc[0]
        self.assertEqual(4, ana["Calls"])
        self.assertEqual(2, ana["Missed calls"])

        luis = df[df["First Name"] == "Luis"].iloc[0]
        self.assertEqual(3, luis["Calls"])
        self.assertEqual(1, luis["Missed calls"])

    def test_rango_diario_usa_timezone_venezuela(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_diario("2026-09-14")

        self.assertEqual((24 * 60 * 60) - 1, rango.until - rango.since)
        self.assertEqual("America/Caracas", rango.timezone)

    def test_rango_respeta_horas_especificas(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_chatwoot("2026-09-15", "08:30", "16:45")

        self.assertEqual("2026-09-15 08:30:00", rango.inicio_local)
        self.assertEqual("2026-09-15 16:45:59", rango.fin_local)
        self.assertEqual((8 * 60 * 60) + (15 * 60) + 59, rango.until - rango.since)

    def test_rango_fechas_diario_usa_inicio_y_fin(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_chatwoot_fechas(
                "2026-09-14",
                "2026-09-16",
                "08:00",
                "17:00",
            )

        self.assertEqual("2026-09-14 08:00:00", rango.inicio_local)
        self.assertEqual("2026-09-16 17:00:59", rango.fin_local)

    def test_periodo_rango_respeta_fechas_elegidas(self):
        inicio, fin = resolver_fechas_periodo("rango", "2026-09-10", "2026-09-12")

        self.assertEqual("2026-09-10", inicio)
        self.assertEqual("2026-09-12", fin)

    def test_rango_media_noche_usa_ventana_del_turno(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_media_noche("2026-09-15")

        self.assertEqual("2026-09-14 21:00:00", rango.inicio_local)
        self.assertEqual("2026-09-15 06:30:59", rango.fin_local)
        self.assertEqual((9 * 60 * 60) + (30 * 60) + 59, rango.until - rango.since)

    def test_rango_media_noche_permite_fin_corto(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            rango = construir_rango_media_noche("2026-09-15", "05:30")

        self.assertEqual("2026-09-14 21:00:00", rango.inicio_local)
        self.assertEqual("2026-09-15 05:30:59", rango.fin_local)

    def test_dataframe_chatwoot_puede_usar_rango_media_noche(self):
        cliente = FakeChatwootClient()
        _df, metadata = obtener_dataframe_reporte_chatwoot(
            "2026-09-15",
            cliente=cliente,
            tipo_rango="media_noche",
        )

        self.assertEqual("media_noche", metadata["tipo_rango"])
        self.assertEqual("2026-09-14 21:00:00", cliente.rangos[0].inicio_local)
        self.assertEqual("2026-09-15 06:30:59", cliente.rangos[0].fin_local)

    def test_dataframe_diario_ignora_hora_fin_de_media_noche(self):
        cliente = FakeChatwootClient()
        _df, _metadata = obtener_dataframe_reporte_chatwoot(
            "2026-09-14",
            cliente=cliente,
            tipo_rango="diario",
            periodo_fechas="rango",
            fecha_fin_texto="2026-09-14",
            hora_fin_texto="05:30",
        )

        self.assertEqual("2026-09-14 00:00:00", cliente.rangos[0].inicio_local)
        self.assertEqual("2026-09-14 23:59:59", cliente.rangos[0].fin_local)

    def test_dataframe_chatwoot_rango_media_noche_consulta_cada_fecha(self):
        cliente = FakeChatwootClient()
        df, metadata = obtener_dataframe_reporte_chatwoot(
            "2026-09-14",
            cliente=cliente,
            tipo_rango="media_noche",
            fecha_fin_texto="2026-09-15",
        )

        self.assertEqual(2, len(cliente.rangos))
        self.assertEqual(2, metadata["cantidad_rangos"])
        self.assertEqual("2026-09-13 21:00:00", cliente.rangos[0].inicio_local)
        self.assertEqual("2026-09-15 06:30:59", cliente.rangos[1].fin_local)
        self.assertEqual(4, len(df))

    def test_rango_rechaza_fin_antes_de_inicio(self):
        with patch.dict(os.environ, {"CHATWOOT_TIMEZONE": "UTC"}):
            with self.assertRaises(ValueError):
                construir_rango_chatwoot("2026-09-15", "18:00", "08:00")

    def test_call_stats_usa_endpoint_custom(self):
        class CapturingClient(ChatwootClient):
            def __init__(self):
                super().__init__(
                    base_url="https://chat.mybrandpatch.com",
                    account_id="2",
                    api_token="token",
                )
                self.path = None

            def get(self, path, params=None):
                self.path = path
                return {"rows": []}

        cliente = CapturingClient()
        rango = construir_rango_chatwoot("2026-09-14", "08:00", "09:00")
        cliente.estadisticas_llamadas(rango)

        self.assertEqual("/custom/api/v1/accounts/2/call_stats", cliente.path)


if __name__ == "__main__":
    unittest.main()
