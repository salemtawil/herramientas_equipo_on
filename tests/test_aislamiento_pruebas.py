"""Regresión: la suite nunca usa configuración, archivos ni servicios reales."""

import os
import socket
from pathlib import Path

import pytest

from app import app
from conftest import REAL_STORE_PATH, TMP_ROOT, LlamadaExternaBloqueada
from tools import api_compinche, api_multiadmin
from utils.turnos_trabajo_store import obtener_store_path


def test_no_hay_credenciales_reales_cargadas():
    # Aunque pytest se ejecute desde la raíz, donde existe el .env real,
    # los módulos se importaron sin sus tokens.
    for nombre in (
        "MULTIADMIN_ID_TOKEN",
        "MULTIADMIN_REFRESH_TOKEN",
        "CHATWOOT_API_ACCESS_TOKEN",
        "SUPABASE_SERVICE_ROLE_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "APPS_SCRIPT_WEBHOOK_URL",
    ):
        assert os.environ.get(nombre) is None, nombre
    assert api_multiadmin.MULTIADMIN_ID_TOKEN == ""
    assert api_multiadmin.MULTIADMIN_REFRESH_TOKEN == ""
    assert api_compinche.COMPINCHE_REFRESH_TOKEN == ""


def test_no_hay_proxies_que_permitan_salir_por_localhost():
    import requests

    for nombre in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        assert os.environ.get(nombre) is None, nombre
    assert requests.utils.get_environ_proxies("https://servicio-externo.invalid") == {}


def test_dotenv_del_directorio_actual_no_se_carga(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("MULTIADMIN_REFRESH_TOKEN=token-falso-de-prueba\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MULTIADMIN_REFRESH_TOKEN", raising=False)

    from utils.env import cargar_env_local

    cargar_env_local()
    assert os.environ.get("MULTIADMIN_REFRESH_TOKEN") is None


def test_store_de_turnos_es_temporal():
    resuelto = Path(obtener_store_path()).resolve()
    assert resuelto != REAL_STORE_PATH
    assert TMP_ROOT in resuelto.parents


def test_dns_externo_bloqueado_antes_de_salir(intentos_de_red_esperados):
    with pytest.raises(LlamadaExternaBloqueada) as error:
        socket.getaddrinfo("servicio-externo.invalid", 443)
    assert "test_dns_externo_bloqueado_antes_de_salir" in str(error.value)
    intentos = intentos_de_red_esperados()
    assert [i["host"] for i in intentos] == ["servicio-externo.invalid"]


def test_conexion_a_ip_externa_bloqueada(intentos_de_red_esperados):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(LlamadaExternaBloqueada):
            sock.connect(("203.0.113.10", 443))  # TEST-NET-3: nunca enrutable
    assert intentos_de_red_esperados()[0]["operacion"] == "connect"


def test_localhost_sigue_permitido():
    assert socket.getaddrinfo("localhost", 80)


def test_actualizar_usuarios_activos_no_contacta_multiadmin(intentos_de_red_esperados, monkeypatch):
    # Simula que un .env local hubiera aportado credenciales (valores falsos).
    monkeypatch.setattr(api_multiadmin, "MULTIADMIN_ID_TOKEN", "id-token-falso")
    monkeypatch.setattr(api_multiadmin, "MULTIADMIN_REFRESH_TOKEN", "refresh-token-falso")
    monkeypatch.setattr(api_compinche, "COMPINCHE_ID_TOKEN", "id-token-falso")
    monkeypatch.setattr(api_compinche, "COMPINCHE_REFRESH_TOKEN", "refresh-token-falso")

    respuesta = app.test_client().post("/usuarios-activos/actualizar")

    assert respuesta.status_code == 200
    data = respuesta.get_json()
    assert set(data) == {"success", "data", "updated_at", "source"}

    intentos = intentos_de_red_esperados()
    assert intentos, "La actualización debió intentar contactar Multiadmin y quedar bloqueada."
    assert all("test_actualizar_usuarios_activos_no_contacta_multiadmin" in i["test"] for i in intentos)
    hosts = {i["host"] for i in intentos}
    assert any(h.endswith(("amazonaws.com", "on.aws")) for h in hosts), hosts


def test_guardia_falla_si_el_store_apunta_al_archivo_real(monkeypatch):
    import utils.turnos_trabajo_store as store
    from conftest import verificar_store_aislado

    monkeypatch.setattr(store, "obtener_store_path", lambda: str(REAL_STORE_PATH))
    with pytest.raises(AssertionError, match="archivo real del repositorio"):
        verificar_store_aislado()
