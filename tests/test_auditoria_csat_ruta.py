"""Ruta /auditoria-csat en modo Chatwoot: traer, guardar/prueba, reabrir y ver conversación."""
import io
import re

import pytest

from app import app
from tools import auditoria_csat as herramienta
from utils.auditoria_csat_store import AuditoriaCsatConfigError, MemoriaCsatStore

BASE_TS = 1762783200  # 2025-11-10 14:00 UTC


def enc(id_, rating=1, conversation_id=None, feedback="Mal servicio"):
    return {
        "id": id_,
        "rating": rating,
        "feedback_message": feedback,
        "conversation_id": conversation_id or 500 + id_,
        "assigned_agent": {"id": 7, "name": "Ana Perez", "available_name": "Ana P."},
        "contact": {"name": "Cliente Uno", "email": "c@x.com", "phone_number": "+58412"},
        "created_at": BASE_TS + id_,
    }


class ChatwootFalso:
    def __init__(self, encuestas=None):
        self.encuestas = encuestas if encuestas is not None else [enc(1, rating=1), enc(2, rating=5), enc(3, rating=4)]
        self.mensajes_pedidos = []
        self.rangos = []

    def respuestas_csat(self, since, until):
        self.rangos.append((since, until))
        return [dict(e) for e in self.encuestas]

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        self.mensajes_pedidos.append(conversation_id)
        return [
            {"id": 1, "message_type": 0, "content": "Hola, mi correo es cliente@correo.com", "created_at": BASE_TS},
            {"id": 2, "message_type": 1, "content": "Buen día, ya lo reviso", "created_at": BASE_TS + 60},
        ]

    def url_conversacion(self, conversation_id):
        return f"https://chat.test/app/accounts/2/conversations/{int(conversation_id)}"


class ChatwootQueFalla(ChatwootFalso):
    def respuestas_csat(self, since, until):
        raise RuntimeError("Chatwoot respondio 500 en https://chat.test/api")

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        raise RuntimeError("Chatwoot respondio 500 en https://chat.test/api")


@pytest.fixture
def chatwoot(monkeypatch):
    falso = ChatwootFalso()
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: falso)
    return falso


@pytest.fixture
def store(monkeypatch):
    memoria = MemoriaCsatStore()
    monkeypatch.setattr(herramienta, "obtener_store_csat", lambda: memoria)
    return memoria


@pytest.fixture
def cliente(chatwoot):
    return app.test_client()


@pytest.fixture
def chatwoot_vacio(chatwoot):
    chatwoot.encuestas = []
    return chatwoot


@pytest.fixture
def chatwoot_que_falla(monkeypatch):
    falso = ChatwootQueFalla()
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: falso)
    return falso


def _traer(cliente, **extra):
    datos = {"accion": "traer_chatwoot", "tipo_periodo": "semana_pasada"}
    datos.update(extra)
    return cliente.post("/auditoria-csat", data=datos)


def _hidden(html, nombre):
    encontrado = re.search(rf'name="{nombre}" value="([^"]*)"', html)
    return encontrado.group(1) if encontrado else ""


def test_get_muestra_formulario_chatwoot_y_csv_en_details(cliente, store):
    html = cliente.get("/auditoria-csat").get_data(as_text=True)
    assert 'value="traer_chatwoot"' in html
    assert 'name="tipo_periodo"' in html and "Semana pasada (lun–dom)" in html
    assert 'type="date"' in html and 'name="prueba"' in html
    assert "Modo prueba (no se guarda)" in html
    assert "Cargar CSV manualmente" in html and "<details" in html
    assert "Auditorías guardadas" in html


def test_traer_chatwoot_guarda_periodo(cliente, store):
    r = _traer(cliente)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and len(store.listar_periodos()) == 1
    periodo = store.listar_periodos()[0]
    assert periodo["tipo_periodo"] == "semana_pasada"
    assert periodo["total_encuestas"] == 3 and periodo["negativos_pendientes"] == 1
    assert [n["survey_id"] for n in store.negativos(periodo["id"])] == [1]
    assert _hidden(html, "period_id") == periodo["id"]
    assert "1 negativos sin confirmar — el ajustado aún no es definitivo" in html
    assert "Auditados a mano: 0 · Aceptados de la IA: 0" in html
    assert "/auditoria-csat/conversacion/501" in html and "Ver conversación" in html
    assert "Modo prueba — nada de esto se guarda" not in html


def test_modo_prueba_no_toca_store(cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_store_csat", lambda: pytest.fail("no debe usarse"))
    r = _traer(cliente, prueba="1")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Modo prueba — nada de esto se guarda" in html
    assert _hidden(html, "period_id") == ""
    analysis_id = _hidden(html, "analysis_id")
    r2 = cliente.post(
        "/auditoria-csat",
        data={"accion": "guardar_auditoria", "analysis_id": analysis_id, "justificable__1": "SÍ"},
    )
    assert r2.status_code == 200 and "Modo prueba — nada de esto se guarda" in r2.get_data(as_text=True)


def test_modo_prueba_sin_temporal_muestra_aviso(cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_store_csat", lambda: pytest.fail("no debe usarse"))
    # El formulario de la tabla reenvía prueba=1 cuando la auditoría es de prueba.
    r = cliente.post("/auditoria-csat", data={"accion": "guardar_auditoria", "analysis_id": "inexistente", "prueba": "1"})
    assert r.status_code == 200 and "ya no está disponible" in r.get_data(as_text=True)


def test_periodo_sin_encuestas(cliente, store, chatwoot_vacio):
    r = _traer(cliente)
    assert "No hay encuestas en el período" in r.get_data(as_text=True) and store.listar_periodos() == []


def test_personalizado_usa_las_fechas(cliente, store, chatwoot):
    _traer(cliente, tipo_periodo="personalizado", fecha_inicio="2025-11-03", fecha_fin="2025-11-09")
    periodo = store.listar_periodos()[0]
    assert (periodo["fecha_inicio"], periodo["fecha_fin"]) == ("2025-11-03", "2025-11-09")
    since, until = chatwoot.rangos[0]
    assert until > since


def test_personalizado_sin_fechas_avisa(cliente, store):
    r = _traer(cliente, tipo_periodo="personalizado")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Falta la fecha de inicio" in html and store.listar_periodos() == []


def test_guardar_decision_sincroniza_y_cuenta_origen(cliente, store):
    html = _traer(cliente).get_data(as_text=True)
    period_id = _hidden(html, "period_id")
    r = cliente.post(
        "/auditoria-csat",
        data={
            "accion": "guardar_auditoria",
            "analysis_id": _hidden(html, "analysis_id"),
            "period_id": period_id,
            "justificable__1": "SÍ",
            "motivo_inconformidad__1": herramienta.MOTIVOS_INCONFORMIDAD[0],
        },
    )
    html2 = r.get_data(as_text=True)
    negativo = store.negativos(period_id)[0]
    assert negativo["decision_final"] == "SÍ" and negativo["origen_decision"] == "humana"
    periodo = store.obtener_periodo(period_id)
    assert periodo["negativos_pendientes"] == 0 and periodo["csat_ajustado"] == 100.0
    assert "Auditados a mano: 1 · Aceptados de la IA: 0" in html2
    assert "negativos sin confirmar" not in html2


def test_reabrir_guardada_sin_temporal_reconstruye_decisiones(cliente, store, monkeypatch):
    html = _traer(cliente).get_data(as_text=True)
    period_id = _hidden(html, "period_id")
    cliente.post(
        "/auditoria-csat",
        data={
            "accion": "guardar_auditoria",
            "analysis_id": _hidden(html, "analysis_id"),
            "period_id": period_id,
            "justificable__1": "SÍ",
        },
    )
    monkeypatch.setattr(herramienta, "cargar_analisis", lambda analysis_id: None)
    r = cliente.get(f"/auditoria-csat?period_id={period_id}")
    html2 = r.get_data(as_text=True)
    assert r.status_code == 200
    select = re.search(r'<select name="justificable__1".*?</select>', html2, re.S).group(0)
    assert re.search(r'<option value="SÍ"\s+selected', select)
    assert _hidden(html2, "period_id") == period_id


def test_lista_guardadas_con_enlace_abrir(cliente, store):
    _traer(cliente)
    periodo = store.listar_periodos()[0]
    html = cliente.get("/auditoria-csat").get_data(as_text=True)
    assert f"period_id={periodo['id']}" in html and "Abrir" in html


def test_store_no_configurado_pantalla_funciona(cliente, monkeypatch):
    def sin_config():
        raise AuditoriaCsatConfigError("Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY para guardar las auditorías CSAT.")

    monkeypatch.setattr(herramienta, "obtener_store_csat", sin_config)
    r = cliente.get("/auditoria-csat")
    assert r.status_code == 200 and "SUPABASE_URL" in r.get_data(as_text=True)
    r2 = _traer(cliente)
    html = r2.get_data(as_text=True)
    assert r2.status_code == 200 and "Modo prueba" in html and "SUPABASE_URL" in html


def test_chatwoot_caido_muestra_aviso(cliente, store, chatwoot_que_falla):
    r = _traer(cliente)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Traceback" not in html
    assert "No se pudieron traer las encuestas de Chatwoot" in html
    assert store.listar_periodos() == []


def test_retraer_borra_negativo_que_subio(cliente, store, chatwoot):
    _traer(cliente)
    period_id = store.listar_periodos()[0]["id"]
    assert len(store.negativos(period_id)) == 1
    chatwoot.encuestas = [enc(1, rating=4), enc(2, rating=5), enc(3, rating=4)]
    _traer(cliente)
    assert len(store.listar_periodos()) == 1
    assert store.negativos(period_id) == []
    periodo = store.obtener_periodo(period_id)
    assert periodo["negativos_total"] == 0 and periodo["csat_ajustado"] == 100.0


def test_auditar_con_ia_carga_transcripcion_solo_de_candidatos(cliente, store, chatwoot, monkeypatch):
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=2), enc(3, rating=5)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")
    vistos = []

    def ia_falsa(filas, config):
        vistos.extend((f["row_id"], bool(f.get("transcripcion_conversacion"))) for f in filas)
        return [{"row_id": f["row_id"], "justificable": "SÍ", "motivo_inconformidad": "OTRO", "confianza": 0.8} for f in filas]

    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", ia_falsa)
    html = _traer(cliente).get_data(as_text=True)
    period_id = _hidden(html, "period_id")
    cliente.post(
        "/auditoria-csat",
        data={
            "accion": "auditar_con_ia",
            "analysis_id": _hidden(html, "analysis_id"),
            "period_id": period_id,
            "justificable__2": "NO",
        },
    )
    assert vistos == [("1", True)]
    assert chatwoot.mensajes_pedidos == [501]
    negativos = {n["survey_id"]: n for n in store.negativos(period_id)}
    assert negativos[1]["ia_justificable"] == "SÍ" and negativos[1]["decision_final"] == ""
    assert negativos[2]["decision_final"] == "NO"
    assert "transcripcion" not in negativos[1]


def test_auditar_con_ia_no_deja_transcripciones_en_el_temporal(cliente, store, chatwoot, monkeypatch):
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=2)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")
    vistos = []

    def ia_falsa(filas, config):
        vistos.extend(bool(f.get("transcripcion_conversacion")) for f in filas)
        return [{"row_id": f["row_id"], "justificable": "SÍ", "motivo_inconformidad": "OTRO", "confianza": 0.8} for f in filas]

    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", ia_falsa)
    html = _traer(cliente).get_data(as_text=True)
    analysis_id = _hidden(html, "analysis_id")
    cliente.post(
        "/auditoria-csat",
        data={"accion": "auditar_con_ia", "analysis_id": analysis_id, "period_id": _hidden(html, "period_id")},
    )
    assert vistos == [True, True]
    estado = herramienta.cargar_analisis(analysis_id)
    assert estado["rows"] and all(not f.get("transcripcion_conversacion") for f in estado["rows"])
    assert any(f.get("ia_justificable") for f in estado["rows"])


def test_ver_conversacion_no_guarda(cliente, store, chatwoot):
    r = cliente.get("/auditoria-csat/conversacion/501")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and store.listar_periodos() == []
    assert chatwoot.mensajes_pedidos == [501]
    assert "Abrir en Chatwoot" in html and "https://chat.test/app/accounts/2/conversations/501" in html
    assert "Buen día, ya lo reviso" in html
    assert "cliente@correo.com" not in html


def test_ver_conversacion_chatwoot_caido(cliente, chatwoot_que_falla):
    r = cliente.get("/auditoria-csat/conversacion/501")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Traceback" not in html
    assert "No se pudo cargar la conversación" in html


def test_csv_sigue_funcionando(cliente):
    encabezado = ",".join(herramienta.EXPECTED_COLUMNS)
    valores = []
    for columna in herramienta.EXPECTED_COLUMNS:
        normal = herramienta.normalizar_texto(columna)
        if "calificacion" in normal:
            valores.append("1")
        elif "fecha" in normal:
            valores.append("2025-11-10 10:00")
        else:
            valores.append("x")
    csv = (encabezado + "\n" + ",".join(valores) + "\n").encode("utf-8")
    r = cliente.post(
        "/auditoria-csat",
        data={"accion": "analizar_csv", "archivo": (io.BytesIO(csv), "csat.csv")},
        content_type="multipart/form-data",
    )
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "CSV cargado" in html
    assert "Modo prueba — nada de esto se guarda" not in html
