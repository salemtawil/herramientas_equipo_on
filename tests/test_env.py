import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.env import cargar_env_local


class EnvLocalTests(unittest.TestCase):
    def test_carga_env_local_sin_sobrescribir_existentes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "TEST_ENV_LOADER_NUEVA=valor\n"
                "TEST_ENV_LOADER_EXISTENTE=nuevo\n",
                encoding="utf-8",
            )

            old_new = os.environ.pop("TEST_ENV_LOADER_NUEVA", None)
            old_existing = os.environ.get("TEST_ENV_LOADER_EXISTENTE")
            os.environ["TEST_ENV_LOADER_EXISTENTE"] = "actual"

            try:
                cargar_env_local(env_path)

                self.assertEqual("valor", os.environ.get("TEST_ENV_LOADER_NUEVA"))
                self.assertEqual("actual", os.environ.get("TEST_ENV_LOADER_EXISTENTE"))
            finally:
                if old_new is None:
                    os.environ.pop("TEST_ENV_LOADER_NUEVA", None)
                else:
                    os.environ["TEST_ENV_LOADER_NUEVA"] = old_new

                if old_existing is None:
                    os.environ.pop("TEST_ENV_LOADER_EXISTENTE", None)
                else:
                    os.environ["TEST_ENV_LOADER_EXISTENTE"] = old_existing


if __name__ == "__main__":
    unittest.main()
