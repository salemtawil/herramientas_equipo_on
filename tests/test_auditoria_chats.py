import re

import pytest

from app import app
from tools import auditoria_chats as herramienta
from utils.auditoria_chats_store import MemoriaAuditoriaStore

CLAVES = ["saludo", "comprension", "exactitud", "resolucion", "tono", "tiempos", "cierre"]
BASE_TS = 1762783200  # 2025-11-10 14:00 UTC


def _resultado(nota=4):
    return {
        "criterios": {clave: nota for clave in CLAVES},
        "nota_global": nota,
        "satisfaccion_cliente": "satisfecho",
        "resuelto": "si",
        "resumen": "Atención correcta.",
        "fortalezas": ["Cordial"],
        "mejoras": [],
        "evidencias": ["Buenos días"],
        "confianza": "alta",
    }


class ChatwootFalso:
    base_url = "https://chat.test"

    def listar_agentes(self):
        return [{"id": 1, "name": "Ana Pérez"}, {"id": 2, "name": "Luis Gómez"}]

    def conversaciones_de_agente(self, agente_id, since, until, page=1):
        if page > 1:
            return []
        return [{"id": agente_id * 10 + i, "created_at": BASE_TS + i} for i in range(3)]

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        return [
            {"id": 1, "message_type": 0, "content": "Hola, necesito ayuda", "created_at": BASE_TS},
            {"id": 2, "message_type": 1, "content": "Buenos días, cuéntame", "created_at": BASE_TS + 30},
        ]

    def url_conversacion(self, conversation_id):
        return f"https://chat.test/app/accounts/2/conversations/{conversation_id}"


@pytest.fixture
def entorno(monkeypatch):
    store = MemoriaAuditoriaStore()
    monkeypatch.setattr(herramienta, "obtener_store", lambda: store)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    monkeypatch.setattr(herramienta, "obtener_turnos_configurados", lambda: {"Mañana": ["Ana Pérez"]})
    monkeypatch.setattr(herramienta.motor, "completar_json", lambda mensajes, config, **k: _resultado())
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-secreta-prueba")
    return store


@pytest.fixture
def cliente():
    return app.test_client()


def _crear_lote(cliente, alcance="todos", **extra):
    datos = {"fecha_inicio": "2025-11-09", "fecha_fin": "2025-11-15", "alcance": alcance, "chats_por_agente": "2"}
    datos.update(extra)
    return cliente.post("/auditoria-chats/lotes", data=datos)


def test_index_muestra_formulario_y_aviso_privacidad(entorno, cliente):
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)
    assert "Auditoría de chats" in html
    assert 'name="fecha_inicio"' in html and 'name="chats_por_agente"' in html
    assert "Ana Pérez" in html and "Mañana" in html
    assert "se envía al proveedor de IA" in html


def test_index_sin_supabase_muestra_aviso_y_no_falla(cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    respuesta = cliente.get("/auditoria-chats/")
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    assert "SUPABASE_URL" in html
    assert re.search(r"<button[^>]*type=\"submit\"[^>]*disabled", html)


def test_crear_lote_redirige_y_lo_guarda(entorno, cliente):
    respuesta = _crear_lote(cliente, alcance="turno", turno="Mañana")
    assert respuesta.status_code == 302
    lotes = entorno.listar_lotes()
    assert len(lotes) == 1
    assert respuesta.headers["Location"].endswith(f"/auditoria-chats/lote/{lotes[0]['id']}")
    assert [a["id"] for a in lotes[0]["agentes"]] == [1]
    assert lotes[0]["chats_por_agente"] == 2


def test_crear_lote_sin_agentes_no_crea(entorno, cliente):
    respuesta = _crear_lote(cliente, alcance="agentes")
    assert respuesta.status_code == 302
    assert entorno.listar_lotes() == []


def test_crear_lote_fechas_invalidas_no_crea(entorno, cliente):
    _crear_lote(cliente, fecha_inicio="2025-11-15", fecha_fin="2025-11-09")
    assert entorno.listar_lotes() == []


def test_paso_json_devuelve_progreso(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    respuesta = cliente.post(f"/auditoria-chats/lote/{lote_id}/paso", headers={"Accept": "application/json"})
    datos = respuesta.get_json()
    assert respuesta.status_code == 200
    assert datos["accion"] == "muestreo"
    assert datos["progreso"]["total"] == 2


def test_lote_se_procesa_hasta_el_fin(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    for _ in range(30):
        datos = cliente.post(f"/auditoria-chats/lote/{lote_id}/paso", headers={"Accept": "application/json"}).get_json()
        if datos["accion"] == "fin":
            break
    assert datos["accion"] == "fin"
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert "Ana Pérez" in html and "Luis Gómez" in html
    assert "4,0" in html


def test_paso_sin_js_redirige(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    respuesta = cliente.post(f"/auditoria-chats/lote/{lote_id}/paso")
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith(f"/auditoria-chats/lote/{lote_id}")


def test_lote_inexistente_404(entorno, cliente):
    assert cliente.get("/auditoria-chats/lote/no-existe").status_code == 404


def test_html_sin_scripts_en_linea_ni_style(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    for ruta in ("/auditoria-chats/", f"/auditoria-chats/lote/{lote_id}"):
        html = cliente.get(ruta).get_data(as_text=True)
        contenido = html[html.index('id="contenido-principal"'):]
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", contenido), ruta
        assert " onclick=" not in contenido and ' style="' not in contenido, ruta


def test_no_expone_clave_ia(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)
    html += cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    html += cliente.post(f"/auditoria-chats/lote/{lote_id}/paso", headers={"Accept": "application/json"}).get_data(as_text=True)
    assert "clave-secreta-prueba" not in html
