import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.auditoria_csat import cargar_analisis, guardar_analisis
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


if __name__ == "__main__":
    unittest.main()
