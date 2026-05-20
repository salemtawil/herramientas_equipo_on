import io
import os
import sys
import unittest

from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.archivos import leer_csv_subido
from utils.archivos import leer_bytes_archivo_csv


class LeerCsvSubidoTests(unittest.TestCase):
    def test_lee_csv_utf8_con_comas(self):
        contenido = (
            "First Name,Last Name,Calls,Outgoing calls,Missed calls,Call seconds,Outgoing call seconds\n"
            "Ana,Perez,3,1,0,120,60\n"
        ).encode("utf-8")
        archivo = FileStorage(stream=io.BytesIO(contenido), filename="reporte.csv")

        df = leer_csv_subido(archivo)

        self.assertIn("First Name", df.columns)
        self.assertIn("Outgoing calls", df.columns)
        self.assertEqual(1, len(df))
        self.assertEqual("Ana", df.iloc[0]["First Name"])

    def test_lee_csv_cp1252_con_punto_y_coma(self):
        contenido = (
            "First Name;Last Name;Calls;Outgoing calls;Missed calls;Call seconds;Outgoing call seconds\n"
            "José;Pérez;5;2;1;300;120\n"
        ).encode("cp1252")
        archivo = FileStorage(stream=io.BytesIO(contenido), filename="reporte.csv")

        df = leer_csv_subido(archivo)

        self.assertIn("First Name", df.columns)
        self.assertIn("Call seconds", df.columns)
        self.assertEqual("José", df.iloc[0]["First Name"])
        self.assertEqual(5, int(df.iloc[0]["Calls"]))

    def test_normaliza_worktime_si_viene_en_csv(self):
        contenido = (
            "First Name,Last Name,Calls,Outgoing calls,Missed calls,Call seconds,Outgoing call seconds,Tiempo de trabajo\n"
            "Ana,Perez,3,1,0,120,60,01:15:00\n"
        ).encode("utf-8")
        archivo = FileStorage(stream=io.BytesIO(contenido), filename="reporte.csv")

        df = leer_csv_subido(archivo)

        self.assertIn("Worktime", df.columns)
        self.assertEqual("01:15:00", df.iloc[0]["Worktime"])

    def test_rechaza_archivo_mayor_al_limite(self):
        contenido = b"123456"
        archivo = FileStorage(stream=io.BytesIO(contenido), filename="grande.csv")

        with self.assertRaises(ValueError) as error:
            leer_bytes_archivo_csv(archivo, max_bytes=5)

        self.assertIn("supera el limite permitido", str(error.exception))


if __name__ == "__main__":
    unittest.main()
