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


# ---------------------------------------------------------------------------
# Revisión humana, historial, CSV y borrado
# ---------------------------------------------------------------------------


def _lote_procesado(cliente, store):
    _crear_lote(cliente)
    lote_id = store.listar_lotes()[0]["id"]
    for _ in range(30):
        datos = cliente.post(f"/auditoria-chats/lote/{lote_id}/paso", headers={"Accept": "application/json"}).get_json()
        if datos["accion"] == "fin":
            break
    return lote_id, store.listar_chats(lote_id)


def test_ver_chat_muestra_resultado_ia_y_formulario(entorno, cliente):
    _, chats = _lote_procesado(cliente, entorno)
    html = cliente.get(f"/auditoria-chats/chat/{chats[0]['id']}").get_data(as_text=True)
    assert "Atención correcta." in html
    assert "Hola, necesito ayuda" in html
    assert "Buenos días, cuéntame" in html
    assert 'name="nota_final"' in html and 'name="revisor"' in html
    assert f"https://chat.test/app/accounts/2/conversations/{chats[0]['conversation_id']}" in html


def test_lote_muestra_cola_de_revision(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    control = [c for c in chats if c.get("motivo_revision") == "control"]
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert len(control) == 1
    assert f"/auditoria-chats/chat/{control[0]['id']}" in html


def test_revisar_guarda_y_redirige_al_siguiente(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    for chat in chats[:2]:
        entorno.actualizar_chat(chat["id"], {"por_revisar": True, "motivo_revision": "marcado"})
    respuesta = cliente.post(
        f"/auditoria-chats/chat/{chats[0]['id']}",
        data={"revisor": "Sara", "nota_final": "2", "satisfaccion_final": "insatisfecho", "comentario_revisor": "No resolvió"},
    )
    revisado = entorno.obtener_chat(chats[0]["id"])
    assert revisado["estado"] == "revisado"
    assert revisado["nota_final"] == 2
    assert revisado["revisor"] == "Sara"
    assert revisado["revisado_at"]
    assert respuesta.status_code == 302
    assert "/auditoria-chats/chat/" in respuesta.headers["Location"]
    assert chats[0]["id"] not in respuesta.headers["Location"]


def test_revisar_rechaza_nota_fuera_de_rango(entorno, cliente):
    _, chats = _lote_procesado(cliente, entorno)
    cliente.post(f"/auditoria-chats/chat/{chats[0]['id']}", data={"revisor": "Sara", "nota_final": "9", "satisfaccion_final": "satisfecho"})
    assert entorno.obtener_chat(chats[0]["id"])["estado"] == "auditado"


def test_reintentar_solo_en_error(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    cliente.post(f"/auditoria-chats/chat/{chats[0]['id']}/reintentar")
    assert entorno.obtener_chat(chats[0]["id"])["estado"] == "auditado"

    entorno.actualizar_chat(chats[1]["id"], {"estado": "error", "ia_error": "x", "intentos": 2})
    cliente.post(f"/auditoria-chats/chat/{chats[1]['id']}/reintentar")
    chat = entorno.obtener_chat(chats[1]["id"])
    assert chat["estado"] == "pendiente" and chat["intentos"] == 0 and chat["ia_error"] is None
    assert entorno.obtener_lote(lote_id)["estado"] == "auditando"


def test_csv_columnas_y_bom(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    respuesta = cliente.get(f"/auditoria-chats/lote/{lote_id}/csv")
    contenido = respuesta.get_data()
    assert respuesta.status_code == 200
    assert contenido.startswith("\ufeff".encode("utf-8"))
    texto = contenido.decode("utf-8-sig")
    assert texto.splitlines()[0].startswith("Conversación,Enlace,Agente")
    assert len(texto.strip().splitlines()) == 1 + len(chats)
    assert "attachment" in respuesta.headers["Content-Disposition"]
    assert "auditoria_chats_" in respuesta.headers["Content-Disposition"]


def test_borrar_lote_libera_conversaciones(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    respuesta = cliente.post(f"/auditoria-chats/lote/{lote_id}/borrar")
    assert respuesta.status_code == 302
    assert entorno.obtener_lote(lote_id) is None
    assert entorno.conversaciones_auditadas([c["conversation_id"] for c in chats]) == set()


def test_borrar_tiene_confirmacion(entorno, cliente):
    lote_id, _ = _lote_procesado(cliente, entorno)
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert re.search(rf'action="/auditoria-chats/lote/{lote_id}/borrar"[^>]*data-confirm=', html)


def test_historial_usa_nota_efectiva(entorno, cliente, monkeypatch):
    lote_id, chats = _lote_procesado(cliente, entorno)
    monkeypatch.setattr(herramienta, "_desde_historial", lambda: "2000-01-01T00:00:00+00:00")
    ana = [c for c in chats if c["agente_id"] == 1]
    entorno.actualizar_chat(ana[0]["id"], {"estado": "revisado", "nota_final": 2})
    html = cliente.get("/auditoria-chats/historial").get_data(as_text=True)
    assert "Ana Pérez" in html
    assert "3,0" in html  # (2 + 4) / 2
    assert "2025-11-10" in html or "10/11/2025" in html


def test_fecha_lote_usa_zona_de_chatwoot(monkeypatch):
    monkeypatch.setenv("CHATWOOT_TIMEZONE", "Asia/Tokyo")
    epoch = 1763236800  # 2025-11-15 20:00 UTC = 2025-11-16 05:00 en Tokio
    assert herramienta._fecha_lote(epoch) == "16/11/2025"


def test_reintentar_todos_los_errores(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    for chat in chats[:3]:
        entorno.actualizar_chat(chat["id"], {"estado": "error", "ia_error": "404", "intentos": 2, "por_revisar": True, "motivo_revision": "marcado"})
    entorno.actualizar_lote(lote_id, {"estado": "con_errores"})

    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert f'action="/auditoria-chats/lote/{lote_id}/reintentar-errores"' in html
    assert "Reintentar los 3 chats con error" in html

    respuesta = cliente.post(f"/auditoria-chats/lote/{lote_id}/reintentar-errores")
    assert respuesta.status_code == 302
    for chat in chats[:3]:
        actual = entorno.obtener_chat(chat["id"])
        assert actual["estado"] == "pendiente" and actual["intentos"] == 0 and actual["ia_error"] is None
        assert actual["por_revisar"] is False
    assert entorno.obtener_lote(lote_id)["estado"] == "auditando"


# ---------------------------------------------------------------------------
# Selector de agentes agrupado por turno
# ---------------------------------------------------------------------------


def _seccion_turno(html, nombre):
    inicio = html.index(f'data-ac-grupo-nombre="{nombre}"')
    fin = html.find("data-ac-grupo-nombre=", inicio + 1)
    return html[inicio : fin if fin != -1 else len(html)]


def test_selector_agrupa_agentes_por_turno(entorno, cliente, monkeypatch):
    monkeypatch.setattr(
        herramienta, "obtener_turnos_configurados", lambda: {"Mañana": ["Ana Pérez"], "Noche": ["Nadie Existe"]}
    )
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)

    assert '<select id="ac-alcance"' not in html
    assert 'name="alcance" value="agentes"' in html
    manana = _seccion_turno(html, "Mañana")
    assert "Ana Pérez" in manana and "Luis Gómez" not in manana
    sin_turno = _seccion_turno(html, "Sin turno asignado")
    assert "Luis Gómez" in sin_turno
    assert 'name="agentes" value="1"' in manana
    noche = _seccion_turno(html, "Noche")
    assert "data-ac-grupo-vacio" in noche
    assert "Nadie Existe" in html  # aviso de nombres que no cruzan con Chatwoot
    assert 'id="ac-buscar"' in html and "data-ac-resumen" in html


def test_selector_crea_lote_con_agentes_marcados(entorno, cliente):
    respuesta = cliente.post(
        "/auditoria-chats/lotes",
        data={"fecha_inicio": "2025-11-09", "fecha_fin": "2025-11-15", "alcance": "agentes",
              "agentes": ["1", "2"], "chats_por_agente": "4"},
    )
    assert respuesta.status_code == 302
    lote = entorno.listar_lotes()[0]
    assert sorted(a["id"] for a in lote["agentes"]) == [1, 2]
    assert lote["chats_por_agente"] == 4


def test_selector_muestra_cupo_diario(entorno, cliente, monkeypatch):
    monkeypatch.setenv("AUDITORIA_CHATS_AI_CUPO_DIARIO", "20")
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)
    assert 'data-ac-cupo="20"' in html


# ---------------------------------------------------------------------------
# Bandejas de entrada y diagnóstico
# ---------------------------------------------------------------------------


class ChatwootConBandejasWeb(ChatwootFalso):
    def listar_bandejas(self):
        return [
            {"id": 3, "name": "WhatsApp Soporte", "channel_type": "Channel::Whatsapp"},
            {"id": 9, "name": "Llamadas", "channel_type": "Channel::Api"},
            {"id": 11, "name": "Voz", "channel_type": "Channel::Voice"},
        ]

    def conversaciones_de_agente(self, agente_id, since, until, page=1, inbox_ids=None):
        return super().conversaciones_de_agente(agente_id, since, until, page=page)


def test_formulario_muestra_bandejas_y_desmarca_llamadas(entorno, cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootConBandejasWeb())
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)
    assert re.search(r'name="bandejas" value="3"[^>]*checked', html)
    assert not re.search(r'name="bandejas" value="9"[^>]*checked', html)
    assert not re.search(r'name="bandejas" value="11"[^>]*checked', html)
    assert "WhatsApp Soporte" in html and "Llamadas" in html


def test_crear_lote_guarda_bandejas(entorno, cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootConBandejasWeb())
    cliente.post("/auditoria-chats/lotes", data={"fecha_inicio": "2025-11-09", "fecha_fin": "2025-11-15",
                 "alcance": "agentes", "agentes": ["1"], "bandejas": ["3"], "chats_por_agente": "2"})
    lote = entorno.listar_lotes()[0]
    assert lote["alcance_detalle"]["bandejas"] == [3]


def test_crear_lote_sin_bandejas_no_crea(entorno, cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootConBandejasWeb())
    cliente.post("/auditoria-chats/lotes", data={"fecha_inicio": "2025-11-09", "fecha_fin": "2025-11-15",
                 "alcance": "agentes", "agentes": ["1"], "chats_por_agente": "2"})
    assert entorno.listar_lotes() == []


def test_diagnostico_json_del_lote(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    entorno.actualizar_chat(chats[0]["id"], {"estado": "error", "ia_error": "El proveedor de IA respondió 404", "intentos": 2})
    respuesta = cliente.get(f"/auditoria-chats/lote/{lote_id}/diagnostico")
    assert respuesta.status_code == 200
    assert "attachment" in respuesta.headers["Content-Disposition"]
    datos = respuesta.get_json()
    assert datos["lote"]["id"] == lote_id
    assert datos["configuracion"]["ia_modelo"]
    assert datos["progreso"]["total"] == len(chats)
    errores = [c for c in datos["chats"] if c["estado"] == "error"]
    assert errores[0]["ia_error"] == "El proveedor de IA respondió 404"
    texto = respuesta.get_data(as_text=True)
    assert "clave-secreta-prueba" not in texto
    assert "transcripcion_tmp" not in texto and "evidencias" not in texto
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert f"/auditoria-chats/lote/{lote_id}/diagnostico" in html


def test_diagnostico_y_revision_muestran_modelo_usado(entorno, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno)
    datos = cliente.get(f"/auditoria-chats/lote/{lote_id}/diagnostico").get_json()
    assert all(c["ia_modelo"] for c in datos["chats"] if c["estado"] == "auditado")
    assert "model_respaldo" in str(datos["configuracion"]) or "ia_modelo_respaldo" in datos["configuracion"]
    html = cliente.get(f"/auditoria-chats/chat/{chats[0]['id']}").get_data(as_text=True)
    assert f"Auditado con {datos['chats'][0]['ia_modelo']}" in html


def test_bandejas_por_defecto_son_las_del_ultimo_lote(entorno, cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootConBandejasWeb())
    cliente.post("/auditoria-chats/lotes", data={"fecha_inicio": "2025-11-09", "fecha_fin": "2025-11-15",
                 "alcance": "agentes", "agentes": ["1"], "bandejas": ["9", "11"], "chats_por_agente": "2"})
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)
    assert re.search(r'name="bandejas" value="9"[^>]*checked', html)
    assert re.search(r'name="bandejas" value="11"[^>]*checked', html)
    assert not re.search(r'name="bandejas" value="3"[^>]*checked', html)


def test_diagnostico_incluye_bandejas_y_descartes(entorno, cliente, monkeypatch):
    lote_id, chats = _lote_procesado(cliente, entorno)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootConBandejasWeb())
    entorno.actualizar_chat(chats[0]["id"], {"estado": "descartado", "detalle": {"motivo_descarte": "llamada", "forma": []}})
    datos = cliente.get(f"/auditoria-chats/lote/{lote_id}/diagnostico").get_json()
    assert {"id": 11, "nombre": "Voz", "tipo": "Voice"}.items() <= next(b for b in datos["bandejas"] if b["id"] == 11).items()
    assert datos["descartes_por_motivo"] == {"llamada": 1}
    assert datos["chats"][0]["detalle"]["motivo_descarte"] == "llamada"


def test_lote_muestra_todos_los_chats_con_valoracion_y_feedback(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    for _ in range(30):
        datos = cliente.post(f"/auditoria-chats/lote/{lote_id}/paso", headers={"Accept": "application/json"}).get_json()
        if datos["accion"] == "fin":
            break
    chats = [c for c in entorno.listar_chats(lote_id) if c["estado"] != "descartado"]
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert "Todos los chats" in html
    assert "Feedback por agente" in html
    assert "Buena atención" in html
    for chat in chats:
        assert f"#{chat['conversation_id']}" in html
