import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.auditoria_salientes import (
    ESTADO_COMPLETO,
    ESTADO_CONTESTADA,
    ESTADO_NO_CUMPLE,
    ESTADO_SEGUNDO_INTENTO,
    analizar_casos,
    preparar_dataframe_historial,
)


class AuditoriaSalientesTests(unittest.TestCase):
    def test_clasifica_caso_por_contestada(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "80",
                    "dateAnswered": "2026-05-10 09:00:10",
                    "ticketId": "T1",
                }
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(1, len(df_casos))
        self.assertEqual(ESTADO_CONTESTADA, df_casos.iloc[0]["Estado final"])

    def test_clasifica_caso_completo_por_voicemail_probable(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "8",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:06:00",
                    "Duracion": "22",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(ESTADO_COMPLETO, df_casos.iloc[0]["Estado final"])
        self.assertEqual("Si", df_casos.iloc[0]["Voicemail probable"])

    def test_clasifica_caso_segundo_intento_sin_voicemail(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "5",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:05:00",
                    "Duracion": "7",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(ESTADO_SEGUNDO_INTENTO, df_casos.iloc[0]["Estado final"])

    def test_clasifica_caso_no_cumple_con_un_solo_intento_corto(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "9",
                }
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(ESTADO_NO_CUMPLE, df_casos.iloc[0]["Estado final"])

    def test_clasifica_caso_no_cumple_con_un_solo_intento_intermedio(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "20",
                }
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(ESTADO_NO_CUMPLE, df_casos.iloc[0]["Estado final"])

    def test_cierra_caso_contestado_y_abre_uno_nuevo_despues(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "10",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:03:00",
                    "Duracion": "80",
                    "dateAnswered": "2026-05-10 09:03:15",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:14:00",
                    "Duracion": "7",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(2, len(df_casos))
        self.assertEqual(ESTADO_CONTESTADA, df_casos.iloc[0]["Estado final"])
        self.assertEqual(ESTADO_NO_CUMPLE, df_casos.iloc[1]["Estado final"])


if __name__ == "__main__":
    unittest.main()
