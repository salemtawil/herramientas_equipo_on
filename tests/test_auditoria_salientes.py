import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.auditoria_salientes import (
    ESTADO_COMPLETO,
    ESTADO_CONTESTADA,
    ESTADO_NO_AUDITABLE,
    ESTADO_NO_CUMPLE,
    ESTADO_SEGUNDO_INTENTO,
    analizar_casos,
    asignar_turnos_a_casos,
    construir_advertencias_calidad,
    construir_advertencias_columnas,
    construir_reconciliacion,
    dataframe_reconciliacion,
    obtener_turno_auditoria,
    construir_resumen_general,
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
        self.assertEqual("2026-05-10 09:00:00", df_casos.iloc[0]["Hora primera llamada"])

    def test_respeta_fecha_iso_sin_invertir_mes_y_dia(self):
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

        self.assertEqual("2026-05-10 09:00:00", df_casos.iloc[0]["Hora primera llamada"])

    def test_parsea_timestamp_iso_con_zona_horaria(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-08-21T23:59:59Z",
                    "Duracion": "9",
                }
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual("2026-08-21 23:59:59", df_casos.iloc[0]["Hora primera llamada"])

    def test_date_answered_clasifica_contestada_aunque_duracion_sea_corta(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "10",
                    "dateAnswered": "2026-05-10 09:00:05",
                }
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

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
                    "Duracion": "10",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(ESTADO_SEGUNDO_INTENTO, df_casos.iloc[0]["Estado final"])

    def test_segundo_intento_demasiado_corto_no_cumple_con_umbral_default(self):
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

        self.assertEqual(ESTADO_NO_CUMPLE, df_casos.iloc[0]["Estado final"])

    def test_segundo_intento_corto_cumple_si_se_baja_umbral(self):
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
                    "Duracion": "10",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado, min_segundo_intento_sin_vm=7)

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

    def test_cierra_caso_contestado_aunque_siguiente_este_en_ventana(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "80",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:05:00",
                    "Duracion": "10",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = analizar_casos(df_preparado)

        self.assertEqual(2, len(df_casos))
        self.assertEqual(ESTADO_CONTESTADA, df_casos.iloc[0]["Estado final"])
        self.assertEqual(ESTADO_NO_CUMPLE, df_casos.iloc[1]["Estado final"])

    def test_csv_vacio_con_columnas_no_rompe_resumen(self):
        df = pd.DataFrame(columns=["Agente", "Numero llamado", "Fecha llamada", "Duracion"])

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = asignar_turnos_a_casos(analizar_casos(df_preparado))
        resumen = construir_resumen_general(df_casos)

        self.assertEqual(0, resumen["Total de casos evaluados"])
        self.assertEqual(0.0, resumen["Porcentaje general de cumplimiento"])
        self.assertIn("_estado", df_casos.columns)

    def test_datos_insuficientes_quedan_no_auditables_y_fuera_del_denominador(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "",
                }
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = asignar_turnos_a_casos(analizar_casos(df_preparado))
        resumen = construir_resumen_general(df_casos)

        self.assertEqual(ESTADO_NO_AUDITABLE, df_casos.iloc[0]["Estado final"])
        self.assertEqual("Datos insuficientes", df_casos.iloc[0]["Observacion"])
        self.assertEqual(0, resumen["Total de casos evaluados"])
        self.assertEqual(1, resumen["No auditable"])
        self.assertEqual(0.0, resumen["Porcentaje general de cumplimiento"])

    def test_duplicado_exacto_no_crea_segundo_intento_falso(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "8",
                    "ticketId": "T1",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "8",
                    "ticketId": "T1",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = asignar_turnos_a_casos(analizar_casos(df_preparado))
        resumen = construir_resumen_general(df_casos)
        estados = df_casos["Estado final"].tolist()

        self.assertEqual(2, len(df_casos))
        self.assertIn(ESTADO_NO_CUMPLE, estados)
        self.assertIn(ESTADO_NO_AUDITABLE, estados)
        self.assertEqual(1, resumen["Total de casos evaluados"])
        self.assertEqual(1, resumen["No cumple"])
        self.assertEqual(1, resumen["No auditable"])

    def test_reconciliacion_cuadra_filas_validas_no_auditables_y_casos(self):
        df = pd.DataFrame(
            [
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:00:00",
                    "Duracion": "8",
                    "ticketId": "T1",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:05:00",
                    "Duracion": "22",
                    "ticketId": "T2",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "5551112222",
                    "Fecha llamada": "2026-05-10 09:05:00",
                    "Duracion": "22",
                    "ticketId": "T2",
                },
                {
                    "Agente": "Ana Perez",
                    "Numero llamado": "",
                    "Fecha llamada": "2026-05-10 09:06:00",
                    "Duracion": "12",
                    "ticketId": "T3",
                },
            ]
        )

        df_preparado, _ = preparar_dataframe_historial(df)
        df_casos = asignar_turnos_a_casos(analizar_casos(df_preparado))
        reconciliacion = construir_reconciliacion(df_preparado, df_casos)

        self.assertEqual(4, reconciliacion["Filas recibidas"])
        self.assertEqual(2, reconciliacion["Filas validas usadas"])
        self.assertEqual(1, reconciliacion["Datos insuficientes"])
        self.assertEqual(1, reconciliacion["Duplicados exactos"])
        self.assertEqual(2, reconciliacion["No auditables"])
        self.assertEqual(1, reconciliacion["Casos evaluados"])
        self.assertEqual(3, reconciliacion["Casos finales totales"])

    def test_advertencias_calidad_describen_datos_no_auditables(self):
        reconciliacion = {
            "Filas recibidas": 4,
            "Filas validas usadas": 2,
            "Datos insuficientes": 1,
            "Duplicados exactos": 1,
            "No auditables": 2,
            "Casos evaluados": 1,
            "Casos finales totales": 3,
        }

        advertencias = construir_advertencias_calidad(reconciliacion)

        self.assertEqual(2, len(advertencias))
        self.assertIn("datos insuficientes", advertencias[0])
        self.assertIn("duplicado", advertencias[1])

    def test_dataframe_reconciliacion_incluye_metricas_y_advertencias(self):
        reconciliacion = {
            "Filas recibidas": 4,
            "Filas validas usadas": 2,
        }
        advertencias = ["1 duplicado exacto no se uso para calcular cumplimiento."]

        df = dataframe_reconciliacion(
            reconciliacion,
            advertencias,
            {"min_segundo_intento_sin_vm": 10},
        )

        self.assertEqual(["Metrica", "Valor"], list(df.columns))
        self.assertEqual(4, len(df))
        self.assertEqual("Minimo 2do intento sin VM", df.iloc[2]["Metrica"])
        self.assertEqual("Advertencia 1", df.iloc[3]["Metrica"])

    def test_advertencias_columnas_opcionales_faltantes(self):
        advertencias = construir_advertencias_columnas(
            {
                "ticket_id": None,
                "fecha_contestada": None,
            }
        )

        self.assertEqual(2, len(advertencias))
        self.assertIn("TicketId", advertencias[0])
        self.assertIn("fecha de contestación", advertencias[1])

    def test_turno_auditoria_usa_coincidencia_flexible(self):
        turnos_config = {"Tarde/Noche": ["Ana"]}
        mapa = {"ana": "Tarde/Noche"}

        turno = obtener_turno_auditoria("Ana Perez", mapa, turnos_config)

        self.assertEqual("Tarde/Noche", turno)


if __name__ == "__main__":
    unittest.main()
