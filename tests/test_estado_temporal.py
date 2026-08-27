import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.estado_temporal import cargar_estado_temporal
from utils.estado_temporal import guardar_estado_temporal


class EstadoTemporalTests(unittest.TestCase):
    def test_roundtrip_inline(self):
        token = guardar_estado_temporal(
            {"mensaje": "ok", "items": [1, 2, 3]},
            secret_key="secret-test",
            salt="salt-test",
            namespace="estado-inline-tests",
            inline_limit_bytes=1024,
        )

        estado = cargar_estado_temporal(
            token,
            secret_key="secret-test",
            salt="salt-test",
            namespace="estado-inline-tests",
        )

        self.assertEqual({"mensaje": "ok", "items": [1, 2, 3]}, estado)

    def test_roundtrip_archivo_cuando_supera_limite_inline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"TEMP": tmpdir, "TMP": tmpdir}):
                token = guardar_estado_temporal(
                    {"payload": "x" * 5000},
                    secret_key="secret-test",
                    salt="salt-test",
                    namespace="estado-file-tests",
                    inline_limit_bytes=32,
                )

                estado = cargar_estado_temporal(
                    token,
                    secret_key="secret-test",
                    salt="salt-test",
                    namespace="estado-file-tests",
                )

        self.assertEqual({"payload": "x" * 5000}, estado)

    def test_estado_grande_pero_comprimible_permanece_inline(self):
        with patch("utils.estado_temporal.guardar_json_temporal") as guardar_archivo:
            token = guardar_estado_temporal(
                {"payload": "x" * 5000},
                secret_key="secret-test",
                salt="salt-test",
                namespace="estado-comprimido-tests",
                inline_limit_bytes=256,
            )

        estado = cargar_estado_temporal(
            token,
            secret_key="secret-test",
            salt="salt-test",
            namespace="estado-comprimido-tests",
        )

        guardar_archivo.assert_not_called()
        self.assertEqual({"payload": "x" * 5000}, estado)
