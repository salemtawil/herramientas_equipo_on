import unittest

import pandas as pd

from tools.reporte_agentes import preparar_dataframe


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


if __name__ == "__main__":
    unittest.main()
