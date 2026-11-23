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
    # Las pruebas históricas usan la pauta v1; las de la pauta QA-1.1 usan `entorno_qa`.
    monkeypatch.setattr(herramienta, "PAUTA_LOTES_NUEVOS", "1")
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


def test_diagnostico_qa_sin_textos_del_cliente_ni_del_manual(entorno, cliente):
    lote = entorno.crear_lote({"etiqueta": "QA", "estado": "completado", "pauta_version": "QA-1.1", "since": BASE_TS, "until": BASE_TS})
    entorno.insertar_chats([{
        "batch_id": lote["id"], "conversation_id": 555, "agente_id": 1, "agente_nombre": "Ana Pérez",
        "estado": "auditado", "ia_qa": 82.5, "ia_estado": "necesita_mejorar",
        "ia_resultado": {
            "pauta_version": "QA-1.1", "pct_verificable": 70.0, "secciones": ["1.1.1"],
            "criterios": {"A1": {"resultado": "cumple", "evidencias": ["m1"], "comentario": "El cliente Pedro dijo X"}},
            "fallas_criticas": [{"codigo": "CR01", "evidencias": [], "descripcion": "Dio el correo de Pedro", "estado": "sospechosa"}],
        },
        "detalle": {"clasificacion": {"motivo_principal": "Pausa", "procedimientos": ["P03"]}},
    }])
    texto = cliente.get(f"/auditoria-chats/lote/{lote['id']}/diagnostico").get_data(as_text=True)
    assert '"ia_qa": 82.5' in texto and '"ia_estado": "necesita_mejorar"' in texto
    assert '"A1": "cumple"' in texto and '"CR01"' in texto and '"P03"' in texto
    assert "Pedro" not in texto


# --- Revisión humana QA-1.1 ---

from utils.auditoria_chats_rubrica import CRITERIOS_QA  # noqa: E402


def _chat_qa_guardado(store, fallas=()):
    lote = store.crear_lote({"etiqueta": "QA", "estado": "completado", "pauta_version": "QA-1.1", "since": BASE_TS, "until": BASE_TS})
    criterios = {c: {"resultado": "cumple", "evidencias": ["m2"], "comentario": f"Comentario {c}"} for c, _, _ in CRITERIOS_QA}
    criterios["B2"]["resultado"] = "no_cumple"
    store.insertar_chats([{
        "batch_id": lote["id"], "conversation_id": 777, "agente_id": 1, "agente_nombre": "Ana Pérez",
        "estado": "auditado", "ia_qa": 90.0, "ia_estado": "pendiente" if fallas else "aprobado",
        "ia_satisfaccion": "satisfecho", "por_revisar": True, "motivo_revision": "marcado",
        "ia_resultado": {
            "pauta_version": "QA-1.1", "qa": 90.0, "pct_verificable": 100.0, "estado": "aprobado",
            "criterios": criterios, "resumen": "Resumen QA", "confianza": "alta",
            "fallas_criticas": [{"codigo": f, "evidencias": ["m2"], "descripcion": "Desc", "estado": "sospechosa"} for f in fallas],
            "cumplimientos": ["Saluda"], "incumplimientos": ["No ofrece solución"], "recomendaciones": ["Ofrecer alternativa"],
            "estado_resolucion": "parcial", "responsabilidad": "agente", "satisfaccion_cliente": "satisfecho",
        },
        "detalle": {"clasificacion": {"motivo_principal": "Pausa de días", "procedimientos": ["P03"]}},
    }])
    return store.listar_chats(lote["id"])[0]


def _form_qa(**extra):
    datos = {"revisor": "Sofía", "satisfaccion_final": "satisfecho", "estado_final": "aprobado", "comentario_revisor": ""}
    datos.update({f"criterio_{c}": "cumple" for c, _, _ in CRITERIOS_QA})
    datos.update(extra)
    return datos


def test_ver_chat_qa_muestra_criterios_qa_y_motivo(entorno, cliente):
    chat = _chat_qa_guardado(entorno)
    html = cliente.get(f"/auditoria-chats/chat/{chat['id']}").get_data(as_text=True)
    assert "A1" in html and "Identificación del problema" in html and "Comentario B1" in html
    assert "90,0" in html and "Pausa de días" in html and "P03" in html
    assert 'href="#m2"' in html and 'id="m2"' in html
    assert 'name="criterio_A1"' in html and 'name="estado_final"' in html
    assert 'name="nota_final"' not in html


def test_revisar_qa_corrige_criterio_y_recalcula(entorno, cliente):
    chat = _chat_qa_guardado(entorno)
    respuesta = cliente.post(f"/auditoria-chats/chat/{chat['id']}", data=_form_qa(criterio_B2="cumple", criterio_D4="no_cumple"))
    assert respuesta.status_code == 302
    guardado = entorno.obtener_chat(chat["id"])
    assert guardado["estado"] == "revisado" and guardado["revisor"] == "Sofía"
    assert guardado["qa_final"] == 97.0 and guardado["estado_final"] == "aprobado"
    assert guardado["revision"]["criterios"] == {"B2": "cumple", "D4": "no_cumple"}


def test_revisar_qa_falla_confirmada_fuerza_no_aprobado(entorno, cliente):
    chat = _chat_qa_guardado(entorno, fallas=["CR04"])
    cliente.post(f"/auditoria-chats/chat/{chat['id']}", data=_form_qa(falla_CR04="confirmada"))
    guardado = entorno.obtener_chat(chat["id"])
    assert guardado["estado_final"] == "no_aprobado"
    assert guardado["revision"]["fallas"] == {"CR04": "confirmada"}


def test_revisar_qa_exige_decidir_fallas_y_nombre(entorno, cliente):
    chat = _chat_qa_guardado(entorno, fallas=["CR04"])
    cliente.post(f"/auditoria-chats/chat/{chat['id']}", data=_form_qa())
    assert entorno.obtener_chat(chat["id"])["estado"] == "auditado"
    cliente.post(f"/auditoria-chats/chat/{chat['id']}", data=_form_qa(revisor="", falla_CR04="descartada"))
    assert entorno.obtener_chat(chat["id"])["estado"] == "auditado"
    cliente.post(f"/auditoria-chats/chat/{chat['id']}", data=_form_qa(falla_CR04="descartada", estado_final="necesita_mejorar"))
    guardado = entorno.obtener_chat(chat["id"])
    assert guardado["estado"] == "revisado" and guardado["estado_final"] == "necesita_mejorar"


# --- Páginas con la pauta QA-1.1 ---


def _evaluacion_qa_ruta(resultado="cumple"):
    return {
        "criterios": {c: {"resultado": resultado, "evidencias": ["m2"], "comentario": "ok"} for c, _, _ in CRITERIOS_QA},
        "fallas_criticas": [], "cumplimientos": ["Saluda con su nombre"], "incumplimientos": ["No deja nota"],
        "recomendaciones": ["Documentar la gestión"], "estado_resolucion": "resuelto", "responsabilidad": "agente",
        "satisfaccion_cliente": "satisfecho", "resumen": "Atención QA correcta.", "confianza": "alta",
    }


def _ia_qa_ruta(mensajes, config, **kwargs):
    if "coach de calidad" in mensajes[0]["content"]:
        return {"puntos_fuertes": [{"texto": "Atiende con calma", "tickets": [7001]}],
                "areas_mejora": [{"texto": "Resumir los pasos", "tickets": [7001]}], "recomendaciones": [],
                "buzon_voz": {"evaluacion": "Deja un mensaje claro", "tickets": [7002]}, "resumen": "Buen trato."}
    if "INSTRUCCIONES DE RESPUESTA" in mensajes[0]["content"]:
        return _evaluacion_qa_ruta()
    return {"motivo_principal": "Consulta de pausa", "procedimientos": ["P03"], "secciones_extra": [], "servicio": "Compinche"}


class MultiadminRuta:
    """Una llamada normal de Ana y un buzón de voz; Luis no aparece (otro nombre en Multiadmin)."""

    dias = 0

    def listar_llamadas(self, desde_ms, hasta_ms):
        MultiadminRuta.dias += 1
        if MultiadminRuta.dias > 1:
            return []
        base = {"callId": "compinche1", "customerNumber": "+15559876543", "createdAt": desde_ms + 1000,
                "metadata": {"callType": "inbound"}, "analytics": {"issueType": "Consulta de llegada"},
                "sentiment": {"agent": "positivo", "customer": "neutral"}}
        return [
            dict(base, recordKey="r1", ticketId="7001", agentNumber="Ana Pérez", durationSec=300, scores={"overall": 82.5}),
            dict(base, recordKey="r2", ticketId="7002", agentNumber="Ana Pérez", durationSec=35, scores={"overall": 100},
                 metadata={"callType": "outbound", "isVoicemail": True}),
            dict(base, recordKey="r3", ticketId="7003", agentNumber="Luis G.", durationSec=200, scores={"overall": 70}),
        ]

    def detalle_llamada(self, call_id, record_key):
        return {"rubric": {"items": [{"name": "Claridad", "percentScore": 50, "weightPct": 10, "notes": "repetitivo"}]},
                "coaching": {"topWins": ["Cordial"], "topImprovements": ["Pasos"], "nextActions": []}, "keyPoints": []}


@pytest.fixture
def entorno_qa(entorno, monkeypatch):
    MultiadminRuta.dias = 0
    monkeypatch.setattr(herramienta, "PAUTA_LOTES_NUEVOS", "QA-1.1")
    monkeypatch.setattr(herramienta.motor, "completar_json", _ia_qa_ruta)
    monkeypatch.setattr(herramienta, "obtener_multiadmin", lambda: MultiadminRuta())
    monkeypatch.delenv("AUDITORIA_CHATS_MANUAL_VERSION", raising=False)
    entorno.guardar_manual("3.0", [
        {"codigo": c, "titulo": f"Sección {c}", "texto": f"Texto {c}", "orden": i}
        for i, c in enumerate(["1.1.1", "1.1.3", "1.1.8", "1.2.5", "1.4.1"])
    ])
    return entorno


def test_lotes_nuevos_usan_pauta_qa_por_defecto():
    assert herramienta.PAUTA_LOTES_NUEVOS == "QA-1.1"


def test_index_sin_manual_avisa_y_no_crea(entorno, cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "PAUTA_LOTES_NUEVOS", "QA-1.1")
    html = cliente.get("/auditoria-chats/").get_data(as_text=True)
    assert "manual de procedimientos" in html.lower()
    _crear_lote(cliente)
    assert entorno.listar_lotes() == []


def test_lote_qa_procesado_muestra_estado_feedback_y_todos_los_chats(entorno_qa, cliente):
    lote_id, chats = _lote_procesado(cliente, entorno_qa)
    lote = entorno_qa.obtener_lote(lote_id)
    assert lote["pauta_version"] == "QA-1.1"
    assert all(c["estado"] == "auditado" and c["ia_qa"] == 100.0 for c in chats if c["estado"] != "descartado")
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert "APROBADO" in html and "100,0" in html
    assert "Feedback por agente" in html and "Documentar la gestión" in html
    # Cada recomendación enlaza a los chats donde se detectó
    assert re.search(r"Documentar la gestión <span class=\"small\">· <a href=\"/auditoria-chats/chat/[^\"]+\">#\d+</a>", html)
    assert "Consulta de pausa" in html
    for chat in chats:
        assert f"#{chat['conversation_id']}" in html
    contenido = html[html.index('id="contenido-principal"'):]
    assert ' style="' not in contenido


def test_csv_e_historial_qa(entorno_qa, cliente, monkeypatch):
    lote_id, _ = _lote_procesado(cliente, entorno_qa)
    texto = cliente.get(f"/auditoria-chats/lote/{lote_id}/csv").get_data().decode("utf-8-sig")
    assert "QA IA" in texto.splitlines()[0] and "APROBADO" in texto
    monkeypatch.setattr(herramienta, "_desde_historial", lambda: "2000-01-01T00:00:00+00:00")
    html = cliente.get("/auditoria-chats/historial").get_data(as_text=True)
    assert "QA 100,0" in html


def test_lote_qa_muestra_llamadas_y_feedback_por_canal(entorno_qa, cliente):
    lote_id, _ = _lote_procesado(cliente, entorno_qa)
    lote = entorno_qa.obtener_lote(lote_id)
    assert lote["llamadas_estado"] == "listo"
    html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert "Atención por mensajes" in html and "Atención por llamadas" in html
    assert "Atiende con calma" in html and "Deja un mensaje claro" in html and "Claridad" in html
    assert "https://chat.test/app/accounts/2/conversations/7001" in html
    assert "+15559876543" not in html and "5559876543" not in html
    # Luis no tiene llamadas: se ofrece emparejarlo con el nombre de Multiadmin sin emparejar
    assert "Luis G." in html and 'name="agent_number"' in html
    contenido = html[html.index('id="contenido-principal"'):]
    assert ' style="' not in contenido


def test_emparejar_y_traer_llamadas(entorno_qa, cliente):
    lote_id, _ = _lote_procesado(cliente, entorno_qa)
    respuesta = cliente.post(f"/auditoria-chats/lote/{lote_id}/emparejar", data={"agent_number": "Luis G.", "agente_id": "2"})
    assert respuesta.status_code == 302
    assert entorno_qa.emparejamientos()["Luis G."] == {"chatwoot_agente_id": 2, "manual": True}
    assert entorno_qa.obtener_lote(lote_id)["llamadas_estado"] == "trayendo"
    cliente.post(f"/auditoria-chats/lote/{lote_id}/llamadas")
    assert entorno_qa.obtener_lote(lote_id)["llamadas_estado"] == "trayendo"
    assert entorno_qa.listar_llamadas(lote_id) == []
    # Agente que no es del lote: no se guarda
    cliente.post(f"/auditoria-chats/lote/{lote_id}/emparejar", data={"agent_number": "X", "agente_id": "99"})
    assert "X" not in entorno_qa.emparejamientos()


def test_informe_pdf_del_lote_qa(entorno_qa, cliente):
    lote_id, _ = _lote_procesado(cliente, entorno_qa)
    lote_html = cliente.get(f"/auditoria-chats/lote/{lote_id}").get_data(as_text=True)
    assert f"/auditoria-chats/lote/{lote_id}/informe" in lote_html
    respuesta = cliente.get(f"/auditoria-chats/lote/{lote_id}/informe")
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Informe de auditoría de calidad" in html
    assert "system-logos/compinche_48.svg" in html or "informe-logo.svg" in html
    assert "auditoria_informe.css" in html and "data-ac-imprimir" in html
    for texto in ("Ana Pérez", "Atención por mensajes", "Atención por llamadas", "Atiende con calma", "Anexo"):
        assert texto in html
    assert "5559876543" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    assert ' style="' not in html and " onclick=" not in html


def test_informe_no_existe_para_lotes_v1(entorno, cliente):
    _crear_lote(cliente)
    lote_id = entorno.listar_lotes()[0]["id"]
    assert cliente.get(f"/auditoria-chats/lote/{lote_id}/informe").status_code == 404
