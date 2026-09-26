"""Aislamiento obligatorio de la suite de pruebas.

Este archivo se importa antes de que pytest recolecte los módulos de ``tests/``
(y, por lo tanto, antes de importar ``app.py`` o ``tools/*``). Todo lo que sigue
se aplica a nivel de módulo por ese motivo; un fixture llegaría tarde, porque
varias herramientas leen variables de entorno al importarse.

Garantías durante ``pytest``:

1. Configuración: se eliminan del entorno las variables de integraciones reales
   y nunca se carga el ``.env`` del repositorio ni el del directorio actual.
2. Archivos: el almacén de turnos apunta a un archivo temporal; si llegara a
   resolverse al ``data/turnos_trabajo.json`` real, la prueba falla.
3. Red: cualquier resolución DNS o conexión a un host que no sea local se
   bloquea al instante, se registra con el test que la originó y hace fallar
   ese test aunque la aplicación capture la excepción.

Nada de esto cambia el comportamiento de la aplicación fuera de pytest.
"""

import hashlib
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import pytest

sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_STORE_PATH = (REPO_ROOT / "data" / "turnos_trabajo.json").resolve()
REPO_DOTENV_PATH = (REPO_ROOT / ".env").resolve()

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Entorno: solo valores de prueba explícitos
# ---------------------------------------------------------------------------

PREFIJOS_DE_CONFIGURACION_REAL = (
    "APPS_SCRIPT_",
    "AWS_",
    "CHATWOOT_",
    "COMPINCHE_",
    "CSAT_",
    "FLASK_",
    "GEMINI_",
    "MULTIADMIN_",
    "OLLAMA_",
    "OPENAI_",
    "SUPABASE_",
    "TURNOS_TRABAJO_",
    "VERCEL",
    "WEEKLY_REPORT_",
)

# Un proxy HTTP en localhost (habitual en redes corporativas o entornos
# gestionados) haría que las bibliotecas salieran a Internet a través de una
# conexión "local" que el bloqueo de red permitiría. Se eliminan todas las
# variables *_PROXY (urllib/requests interpretan cualquiera con ese sufijo).
for _nombre in list(os.environ):
    if _nombre.startswith(PREFIJOS_DE_CONFIGURACION_REAL) or _nombre.upper().endswith("_PROXY"):
        del os.environ[_nombre]

TMP_ROOT = Path(tempfile.mkdtemp(prefix="herramientas-pytest-"))
(TMP_ROOT / "temp").mkdir()
TEST_STORE_PATH = TMP_ROOT / "turnos_trabajo.json"

VALORES_DE_PRUEBA = {
    "FLASK_SECRET_KEY": "clave-solo-para-pruebas",
    "TURNOS_TRABAJO_STORAGE": "local",
    "TURNOS_TRABAJO_STORE_PATH": str(TEST_STORE_PATH),
    # utils/estado_temporal.py usa TEMP/TMP para sus archivos temporales.
    "TEMP": str(TMP_ROOT / "temp"),
    "TMP": str(TMP_ROOT / "temp"),
    # boto3 no debe leer credenciales locales ni consultar el servicio de metadatos.
    "AWS_EC2_METADATA_DISABLED": "true",
    "AWS_SHARED_CREDENTIALS_FILE": str(TMP_ROOT / "aws-credentials-inexistente"),
    "AWS_CONFIG_FILE": str(TMP_ROOT / "aws-config-inexistente"),
}
os.environ.update(VALORES_DE_PRUEBA)


# ---------------------------------------------------------------------------
# 1b. .env: app.py llama a cargar_env_local() al importarse
# ---------------------------------------------------------------------------

import utils.env as _utils_env  # noqa: E402

_cargar_env_local_original = _utils_env.cargar_env_local


def _es_dotenv_real(ruta):
    destino = Path(ruta)
    if not destino.is_absolute():
        destino = Path.cwd() / destino
    destino = destino.resolve()
    return destino == REPO_DOTENV_PATH or destino == (Path.cwd() / ".env").resolve()


def cargar_env_local_en_pruebas(ruta=".env"):
    """Igual que utils.env.cargar_env_local, pero nunca lee el .env real."""
    if _es_dotenv_real(ruta):
        return
    return _cargar_env_local_original(ruta)


_utils_env.cargar_env_local = cargar_env_local_en_pruebas


# ---------------------------------------------------------------------------
# 3. Red: bloqueo de toda conexión no local
# ---------------------------------------------------------------------------

HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}
INTENTOS_DE_RED = []


class LlamadaExternaBloqueada(RuntimeError):
    """Se lanza cuando código bajo prueba intenta salir a la red."""


def _test_actual():
    valor = os.environ.get("PYTEST_CURRENT_TEST", "")
    return valor.rsplit(" (", 1)[0] if valor else "<fuera de un test>"


def _es_local(host):
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host).strip("[]").lower()
    return host in HOSTS_LOCALES or host.startswith("127.")


def _bloquear(operacion, host, puerto=None):
    test = _test_actual()
    INTENTOS_DE_RED.append({"test": test, "operacion": operacion, "host": str(host), "puerto": puerto})
    raise LlamadaExternaBloqueada(
        f"Llamada externa bloqueada durante pytest: {operacion} {host}:{puerto} "
        f"desde {test}. Simula el servicio con un mock."
    )


_socket_connect_original = socket.socket.connect
_socket_connect_ex_original = socket.socket.connect_ex
_getaddrinfo_original = socket.getaddrinfo
_gethostbyname_original = socket.gethostbyname
_gethostbyname_ex_original = socket.gethostbyname_ex


def _destino(sock, address):
    if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
        return None, None
    if isinstance(address, tuple):
        return address[0], (address[1] if len(address) > 1 else None)
    return address, None


def _connect_protegido(self, address):
    host, puerto = _destino(self, address)
    if not _es_local(host):
        _bloquear("connect", host, puerto)
    return _socket_connect_original(self, address)


def _connect_ex_protegido(self, address):
    host, puerto = _destino(self, address)
    if not _es_local(host):
        _bloquear("connect_ex", host, puerto)
    return _socket_connect_ex_original(self, address)


def _getaddrinfo_protegido(host, port, *args, **kwargs):
    if not _es_local(host):
        _bloquear("getaddrinfo", host, port)
    return _getaddrinfo_original(host, port, *args, **kwargs)


def _gethostbyname_protegido(host):
    if not _es_local(host):
        _bloquear("gethostbyname", host)
    return _gethostbyname_original(host)


def _gethostbyname_ex_protegido(host):
    if not _es_local(host):
        _bloquear("gethostbyname_ex", host)
    return _gethostbyname_ex_original(host)


socket.socket.connect = _connect_protegido
socket.socket.connect_ex = _connect_ex_protegido
socket.getaddrinfo = _getaddrinfo_protegido
socket.gethostbyname = _gethostbyname_protegido
socket.gethostbyname_ex = _gethostbyname_ex_protegido


# ---------------------------------------------------------------------------
# 2. Archivos: el store nunca puede ser el real
# ---------------------------------------------------------------------------


def _huella(ruta):
    if not ruta.exists():
        return None
    stat = ruta.stat()
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), stat.st_mtime_ns, stat.st_size


def verificar_store_aislado():
    from utils.turnos_trabajo_store import obtener_store_path, usar_supabase

    resuelto = Path(obtener_store_path()).resolve()
    if resuelto == REAL_STORE_PATH:
        raise AssertionError(
            f"El store de turnos apunta al archivo real del repositorio ({REAL_STORE_PATH}). "
            "Las pruebas deben usar TURNOS_TRABAJO_STORE_PATH temporal."
        )
    if usar_supabase():
        raise AssertionError("Las pruebas no deben usar Supabase para el store de turnos.")
    return resuelto


verificar_store_aislado()
HUELLA_STORE_REAL_INICIAL = _huella(REAL_STORE_PATH)


@pytest.fixture
def intentos_de_red_esperados():
    """Para tests que comprueban el bloqueo.

    Devuelve una función que lista los intentos de red hechos durante el test;
    esos intentos no hacen fallar el test (siguen bloqueados igualmente).
    """
    inicio = len(INTENTOS_DE_RED)
    yield lambda: list(INTENTOS_DE_RED[inicio:])


@pytest.fixture(autouse=True)
def _aislamiento_por_test(request):
    verificar_store_aislado()
    inicio = len(INTENTOS_DE_RED)
    yield
    nuevos = INTENTOS_DE_RED[inicio:]
    if nuevos and "intentos_de_red_esperados" not in request.fixturenames:
        detalle = "; ".join(f"{i['operacion']} {i['host']}:{i['puerto']}" for i in nuevos)
        pytest.fail(f"{request.node.nodeid} intentó salir a la red: {detalle}", pytrace=False)
    verificar_store_aislado()


def pytest_sessionfinish(session, exitstatus):
    if _huella(REAL_STORE_PATH) != HUELLA_STORE_REAL_INICIAL:
        session.exitstatus = 1
        print(f"\nERROR: la suite modificó {REAL_STORE_PATH}.")
    shutil.rmtree(TMP_ROOT, ignore_errors=True)
