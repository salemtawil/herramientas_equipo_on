import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tools.auditoria_csat as csat
from tools.auditoria_csat import (
    aceptar_propuestas_ia,
    actualizar_estado_desde_formulario,
    aplicar_resultado_ia,
    auditar_estado_con_ia,
    cargar_analisis,
    guardar_analisis,
)
from utils.estado_temporal import limpiar_estados_temporales_expirados


class AuditoriaCsatStateTests(unittest.TestCase):
    def tearDown(self):
        limpiar_estados_temporales_expirados("auditoria_csat", ttl_hours=0)

    def test_guardar_analisis_asigna_analysis_id_y_persiste_estado(self):
        estado = {
            "analysis_id": "",
            "source_filename": "csat.csv",
            "rows": [],
            "warnings": [],
            "original_columns": [],
        }

        analysis_id = guardar_analisis(estado)
        cargado = cargar_analisis(analysis_id)

        self.assertTrue(analysis_id)
        self.assertEqual(analysis_id, estado["analysis_id"])
        self.assertEqual("csat.csv", cargado["source_filename"])
        self.assertEqual(analysis_id, cargado["analysis_id"])


def fila_negativa(**extra):
    fila = {
        "row_id": "0",
        "tipo_rating": "Negativo",
        "justificable": "",
        "comentario_auditor": "",
        "motivo_inconformidad": "",
        "estado_auditoria": "pendiente",
        "csat_flag": "contabiliza",
        "ia_justificable": "",
        "ia_motivo": "",
        "origen_decision": "",
    }
    fila.update(extra)
    return fila


def fila_con_propuesta(valor):
    return fila_negativa(ia_justificable=valor, ia_motivo="CAPTCHA", ia_estado="sugerida")


class AuditoriaCsatPropuestaIaTests(unittest.TestCase):
    def test_ia_no_cambia_decision_ni_csat(self):
        fila = fila_negativa()
        aplicar_resultado_ia(
            fila,
            {"justificable": "SI", "motivo_inconformidad": "CAPTCHA", "confianza": 0.9, "explicacion": "x", "evidencia": "y"},
            "m",
        )
        self.assertEqual("SÍ", fila["ia_justificable"])
        self.assertEqual("CAPTCHA", fila["ia_motivo"])
        self.assertEqual("", fila["justificable"])
        self.assertEqual("", fila["comentario_auditor"])
        self.assertEqual("pendiente", fila["estado_auditoria"])
        self.assertEqual("contabiliza", fila["csat_flag"])

    def test_ia_fuente_chatwoot_si_hay_survey_id_y_transcripcion(self):
        fila = fila_negativa(survey_id="9", transcripcion_conversacion="hola")
        aplicar_resultado_ia(fila, {"justificable": "NO"}, "m")
        self.assertEqual("transcripcion_chatwoot", fila["ia_fuente"])

    def test_aceptar_propuestas_marca_origen(self):
        estado = {"rows": [fila_con_propuesta("SÍ")]}
        self.assertEqual(1, aceptar_propuestas_ia(estado))
        fila = estado["rows"][0]
        self.assertEqual("SÍ", fila["justificable"])
        self.assertEqual("CAPTCHA", fila["motivo_inconformidad"])
        self.assertEqual("ia_aceptada", fila["origen_decision"])
        self.assertEqual("excluida_por_justificable_si", fila["csat_flag"])

    def test_guardar_form_sin_cambios_no_vuelve_humana(self):
        estado = {"rows": [fila_con_propuesta("SÍ")]}
        actualizar_estado_desde_formulario(
            estado, {"justificable__0": "", "motivo_inconformidad__0": "", "comentario_auditor__0": ""}
        )
        self.assertEqual("", estado["rows"][0]["origen_decision"])
        self.assertEqual("", estado["rows"][0]["justificable"])

    def test_cambio_en_form_es_humana_y_la_ia_no_la_toca(self):
        estado = {"rows": [fila_negativa()]}
        actualizar_estado_desde_formulario(
            estado, {"justificable__0": "NO", "motivo_inconformidad__0": "OTRO", "comentario_auditor__0": "nota"}
        )
        self.assertEqual("humana", estado["rows"][0]["origen_decision"])

        llamadas = []

        def falso(filas, config):
            llamadas.append(filas)
            return []

        with mock.patch.object(csat, "auditar_lote_con_proveedor", falso), mock.patch.object(
            csat, "obtener_ia_config",
            return_value={"provider": "ollama", "api_key": "", "model": "m", "max_cases": 10, "ollama_base_url": ""},
        ):
            auditadas, _ = auditar_estado_con_ia(estado)
        self.assertEqual(0, auditadas)
        self.assertEqual([], llamadas)


if __name__ == "__main__":
    unittest.main()
