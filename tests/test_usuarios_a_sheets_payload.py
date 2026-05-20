import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from tools.usuarios_a_sheets import cargar_desde_payload, serializar_resultado


class UsuariosASheetsPayloadTests(unittest.TestCase):
    def test_payload_firmado_se_recupera(self):
        with app.app_context():
            payload = serializar_resultado(
                df=pd.DataFrame([{"Nombre": "Ana", "Telefono": "123"}]),
                resumen={"Filas originales": 1},
                regiones_sin_tz=["Region X"],
                sistema="compinche",
            )

            df, resumen, regiones, sistema = cargar_desde_payload(payload)

            self.assertEqual(1, len(df))
            self.assertEqual({"Filas originales": 1}, resumen)
            self.assertEqual(["Region X"], regiones)
            self.assertEqual("compinche", sistema)

    def test_payload_tampered_se_invalida(self):
        with app.app_context():
            payload = serializar_resultado(
                df=pd.DataFrame([{"Nombre": "Ana"}]),
                resumen={"Filas originales": 1},
                regiones_sin_tz=[],
                sistema="compinche",
            )

            df, resumen, regiones, sistema = cargar_desde_payload(f"{payload}tampered")

            self.assertIsNone(df)
            self.assertIsNone(resumen)
            self.assertEqual([], regiones)
            self.assertEqual("compinche", sistema)


if __name__ == "__main__":
    unittest.main()
