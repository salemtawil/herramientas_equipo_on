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


def _ficha_de(html, row_id):
    return re.search(rf'<article[^>]*data-csat-ficha data-row-id="{row_id}".*?</article>', html, re.S).group(0)


def _formulario_fichas(html):
    return re.search(r"<form[^>]*data-csat-fichas[^>]*>.*?</form>", html, re.S).group(0)


def _decision_actual(html, row_id):
    """Decisión del botón marcado como actual en la ficha de esa fila (value="<row_id>|<decisión>")."""
    actual = re.search(r'value="([^"]+)"[^>]*class="[^"]*is-actual', _ficha_de(html, row_id))
    if not actual:
        return ""
    fila, decision = actual.group(1).rsplit("|", 1)
    assert fila == str(row_id)
    return decision


def _kpi(html, clave):
    return re.search(rf'data-csat-kpi="{clave}">([^<]*)<', html).group(1).strip()


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
    assert _kpi(html, "por_confirmar") == "1" and 'data-confirmada="0"' in _ficha_de(html, "1")
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
    assert _kpi(html2, "por_confirmar") == "0" and 'data-confirmada="1"' in _ficha_de(html2, "1")


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
    assert _decision_actual(html2, "1") == "SÍ"
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
    guardado = cliente.post(
        "/auditoria-csat",
        data={
            "accion": "guardar_auditoria",
            "analysis_id": _hidden(html, "analysis_id"),
            "period_id": period_id,
            "justificable__2": "NO",
        },
    ).get_data(as_text=True)
    cliente.post(
        "/auditoria-csat",
        data={"accion": "auditar_con_ia", "analysis_id": _hidden(guardado, "analysis_id"), "period_id": period_id},
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
    monkeypatch.setenv("CSAT_AI_MAX_CASES", "2")
    vistos = []

    def ia_falsa(filas, config):
        vistos.extend(bool(f.get("transcripcion_conversacion")) for f in filas)
        return [{"row_id": f["row_id"], "justificable": "SÍ", "motivo_inconformidad": "OTRO", "confianza": 0.8} for f in filas]

    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", ia_falsa)
    html = _traer(cliente).get_data(as_text=True)
    respuesta = cliente.post(
        "/auditoria-csat",
        data={"accion": "auditar_con_ia", "analysis_id": _hidden(html, "analysis_id"), "period_id": _hidden(html, "period_id")},
    ).get_data(as_text=True)
    assert vistos == [True, True]
    # El estado que queda (el que lleva la página de respuesta) no guarda las conversaciones.
    with app.app_context():
        estado = herramienta.cargar_analisis(_hidden(respuesta, "analysis_id"))
    assert estado["rows"] and all(not f.get("transcripcion_conversacion") for f in estado["rows"])
    assert all("metricas_tiempo" not in f for f in estado["rows"])
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


# --- Auditar con IA: todos los negativos, por tandas ---------------------------------------


def _ia_propone_si(filas, config):
    return [{"row_id": f["row_id"], "justificable": "SÍ", "motivo_inconformidad": "OTRO", "confianza": 0.8} for f in filas]


def _paso_json(cliente, html, analysis_id=None):
    return cliente.post(
        "/auditoria-csat",
        data={
            "accion": "auditar_con_ia",
            "analysis_id": analysis_id or _hidden(html, "analysis_id"),
            "period_id": _hidden(html, "period_id"),
        },
        headers={"Accept": "application/json"},
    ).get_json()


def test_paso_a_paso_revisa_todos_los_negativos(cliente, store, chatwoot, monkeypatch):
    chatwoot.encuestas = [enc(i, rating=1) for i in range(1, 8)] + [enc(20, rating=5)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", _ia_propone_si)
    html = _traer(cliente).get_data(as_text=True)

    primero = _paso_json(cliente, html)
    assert (primero["auditadas"], primero["pendientes"], primero["total_negativos"], primero["fin"]) == (1, 6, 7, False)
    pasos = [primero]
    # Como hace la página: cada paso parte del estado que devolvió el anterior.
    while not pasos[-1]["fin"] and len(pasos) < 20:
        pasos.append(_paso_json(cliente, html, pasos[-1]["analysis_id"]))
    assert len(pasos) == 7 and pasos[-1]["pendientes"] == 0
    assert "period_id=" in pasos[-1]["url"]
    assert pasos[-1]["analysis_id"] and "analysis_id" not in pasos[-1]["url"]
    assert all(n["ia_justificable"] == "SÍ" for n in store.negativos(_hidden(html, "period_id")))


def test_proveedor_saturado_pide_esperar_y_no_culpa_al_cupo(cliente, store, chatwoot, monkeypatch):
    from utils.ia_chat import IATemporalError

    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=2)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")

    def saturado(filas, config):
        raise IATemporalError("El proveedor de IA está saturado o con fallos (503); se reintentará en 30 s.")

    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", saturado)
    html = _traer(cliente).get_data(as_text=True)
    datos = _paso_json(cliente, html)
    assert datos["fin"] is False and datos["esperar_segundos"] == 30 and datos["pendientes"] == 2
    assert "no es por falta de cupo" in datos["advertencia"].lower()
    assert "CSAT_AI_MAX_CASES" not in datos["advertencia"]


def test_cupo_diario_agotado_detiene(cliente, store, chatwoot, monkeypatch):
    from utils.ia_chat import IARateLimitError

    chatwoot.encuestas = [enc(1, rating=1)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")

    def sin_cupo(filas, config):
        raise IARateLimitError("Límite diario de la IA alcanzado; retoma mañana.", diario=True)

    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", sin_cupo)
    datos = _paso_json(cliente, _traer(cliente).get_data(as_text=True))
    assert datos["fin"] is True and datos["esperar_segundos"] == 0
    assert "compartido con la Auditoría de chats" in datos["advertencia"]


def test_sin_javascript_un_clic_audita_una_tanda_y_dice_cuantos_quedan(cliente, store, chatwoot, monkeypatch):
    chatwoot.encuestas = [enc(i, rating=1) for i in range(1, 8)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", _ia_propone_si)
    html = _traer(cliente).get_data(as_text=True)
    respuesta = cliente.post(
        "/auditoria-csat",
        data={"accion": "auditar_con_ia", "analysis_id": _hidden(html, "analysis_id"), "period_id": _hidden(html, "period_id")},
    ).get_data(as_text=True)
    assert "La IA revisó 1 negativo(s). Quedan 6 por revisar." in respuesta
    assert "data-csat-ia" in respuesta and "auditoria_csat.js" in respuesta



# --- El estado viaja firmado en la página: no depende de qué servidor atiende -----------------


def test_estado_viaja_en_la_pagina_aunque_se_borre_el_temporal(cliente, store, chatwoot, monkeypatch, tmp_path):
    """En Vercel cada petición puede caer en otro servidor sin los archivos temporales del anterior."""
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=2), enc(3, rating=5)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", _ia_propone_si)
    html = _traer(cliente, prueba="1").get_data(as_text=True)
    # Otro servidor: directorio temporal vacío.
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))

    paso = _paso_json(cliente, html)
    assert paso["auditadas"] == 1 and paso["pendientes"] == 1
    segundo = cliente.post(
        "/auditoria-csat",
        data={"accion": "auditar_con_ia", "analysis_id": paso["analysis_id"]},
        headers={"Accept": "application/json"},
    ).get_json()
    assert (segundo["auditadas"], segundo["pendientes"], segundo["fin"]) == (1, 0, True)

    vista = cliente.post("/auditoria-csat", data={"accion": "ver_estado", "analysis_id": segundo["analysis_id"]})
    texto = vista.get_data(as_text=True)
    assert vista.status_code == 200
    assert texto.count('data-csat-ia-propuesta="SÍ"') == 2 and texto.count("La IA cree") == 2
    assert "Modo prueba" in texto


def test_ver_estado_no_borra_decisiones(cliente, store, chatwoot):
    chatwoot.encuestas = [enc(1, rating=1)]
    html = _traer(cliente).get_data(as_text=True)
    guardado = cliente.post(
        "/auditoria-csat",
        data={"accion": "guardar_auditoria", "analysis_id": _hidden(html, "analysis_id"), "period_id": _hidden(html, "period_id"), "justificable__1": "NO"},
    ).get_data(as_text=True)
    vista = cliente.post(
        "/auditoria-csat", data={"accion": "ver_estado", "analysis_id": _hidden(guardado, "analysis_id")}
    ).get_data(as_text=True)
    assert _decision_actual(vista, "1") == "NO"
    assert store.negativos(_hidden(html, "period_id"))[0]["decision_final"] == "NO"


# --- Acción decidir: una decisión a la vez ---
JSON = {"Accept": "application/json"}


def _decidir(cliente, analysis_id, period_id, row_id, justificable="SÍ", json=True, **extra):
    datos = {
        "accion": "decidir",
        "analysis_id": analysis_id,
        "period_id": period_id,
        "row_id": row_id,
        "justificable": justificable,
        "motivo": herramienta.MOTIVOS_INCONFORMIDAD[0],
        "nota": "n",
    }
    datos.update(extra)
    return cliente.post("/auditoria-csat", data=datos, headers=JSON if json else {})


def _dos_negativos(cliente, chatwoot):
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=1)]
    html = _traer(cliente).get_data(as_text=True)
    return _hidden(html, "analysis_id"), _hidden(html, "period_id")


def test_decidir_json_guarda_una_fila(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    r = _decidir(cliente, aid, pid, "1", motivo="CAPTCHA")
    datos = r.get_json()
    assert datos["ok"] and datos["ficha"]["confirmada"]
    assert datos["kpis"]["por_confirmar"] == 1
    assert datos["pestanas"]["confirmados"] == 1
    por_id = {str(n["survey_id"]): n for n in store.negativos(pid)}
    assert por_id["1"]["decision_final"] == "SÍ" and por_id["1"]["origen_decision"] == "humana"
    assert not por_id["2"].get("decision_final")


def test_dos_decisiones_encadenadas(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    primera = _decidir(cliente, aid, pid, "1").get_json()
    segunda = _decidir(cliente, primera["analysis_id"], pid, "2", "NO").get_json()
    assert segunda["ok"] and segunda["pestanas"]["confirmados"] == 2
    por_id = {str(n["survey_id"]): n for n in store.negativos(pid)}
    assert por_id["1"]["decision_final"] == "SÍ" and por_id["2"]["decision_final"] == "NO"


def test_decidir_invalido_no_cambia_nada(cliente, store, chatwoot):
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=5)]
    html = _traer(cliente).get_data(as_text=True)
    aid, pid = _hidden(html, "analysis_id"), _hidden(html, "period_id")
    antes = store.negativos(pid)
    for row_id, justificable in (("999", "SÍ"), ("2", "SÍ"), ("1", "")):
        datos = _decidir(cliente, aid, pid, row_id, justificable).get_json()
        assert datos["ok"] is False and datos["error"] and datos["analysis_id"] == aid
    assert store.negativos(pid) == antes
    assert _decidir(cliente, aid, pid, "1").get_json()["ok"]


def test_decidir_sin_js_recarga_con_ficha_confirmada(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    r = _decidir(cliente, aid, pid, "1", json=False)
    assert r.status_code == 200 and "Confirmado" in r.get_data(as_text=True)


def test_decidir_con_supabase_caido_conserva_la_decision(cliente, store, chatwoot, monkeypatch):
    aid, pid = _dos_negativos(cliente, chatwoot)

    def falla(*args, **kwargs):
        raise RuntimeError("supabase caído")

    monkeypatch.setattr(store, "reemplazar_negativos", falla)
    datos = _decidir(cliente, aid, pid, "1").get_json()
    assert datos["ok"] and datos["advertencia"]
    with app.app_context():
        estado = herramienta.cargar_analisis(datos["analysis_id"])
    assert next(f for f in estado["rows"] if f["row_id"] == "1")["justificable"] == "SÍ"


def test_acciones_sin_filas_no_borran_decisiones(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    datos = _decidir(cliente, aid, pid, "1").get_json()
    r = cliente.post(
        "/auditoria-csat",
        data={"accion": "aceptar_propuestas_ia", "analysis_id": datos["analysis_id"], "period_id": pid},
    )
    assert store.negativos(pid)[0]["decision_final"] == "SÍ"
    r = cliente.post(
        "/auditoria-csat",
        data={"accion": "descargar_csv_auditado", "analysis_id": _hidden(r.get_data(as_text=True), "analysis_id"), "period_id": pid},
    )
    assert r.status_code == 200 and "SÍ" in r.get_data(as_text=True)
    assert store.negativos(pid)[0]["decision_final"] == "SÍ"


def test_decidir_no_aplica_retencion(cliente, store, chatwoot, monkeypatch):
    aid, pid = _dos_negativos(cliente, chatwoot)
    llamadas = []
    monkeypatch.setattr(store, "borrar_vencidos", lambda hoy: llamadas.append(hoy))
    assert _decidir(cliente, aid, pid, "1").get_json()["ok"]
    assert llamadas == []


# --- Pantalla por pasos y fichas ---


def _fichas(html):
    return re.findall(r"<article[^>]*data-csat-ficha[^>]*>.*?</article>", html, re.S)


def test_pagina_muestra_pasos_kpis_y_fichas(cliente, store, chatwoot):
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=2), enc(3, rating=5)]
    html = _traer(cliente).get_data(as_text=True)
    assert 'data-csat-paso="confirmar"' in html
    assert 'data-csat-kpi="csat_ajustado"' in html
    assert len(_fichas(html)) == 2
    assert "No fue culpa del agente" in html
    assert "SÍ justificable" not in html and "CSAT actualizado" not in html


def test_ficha_con_propuesta_ia_en_lenguaje_claro(cliente, store, chatwoot, monkeypatch):
    chatwoot.encuestas = [enc(1, rating=1)]
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(herramienta, "auditar_lote_con_proveedor", _ia_propone_si)
    html = _traer(cliente).get_data(as_text=True)
    respuesta = cliente.post(
        "/auditoria-csat",
        data={"accion": "auditar_con_ia", "analysis_id": _hidden(html, "analysis_id"), "period_id": _hidden(html, "period_id")},
    ).get_data(as_text=True)
    (ficha,) = _fichas(respuesta)
    assert "La IA cree" in ficha and "No fue culpa del agente" in ficha
    assert re.search(r'value="1\|SÍ"[^>]*class="[^"]*is-sugerido', ficha) or re.search(
        r'class="[^"]*is-sugerido[^"]*"[^>]*value="1\|SÍ"', ficha
    )


def test_pagina_sin_auditoria_explica_los_pasos(cliente, store):
    html = cliente.get("/auditoria-csat").get_data(as_text=True)
    assert "Tú confirmas" in html
    assert "data-csat-ficha" not in html


def test_csv_usa_fichas(cliente):
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
    html = cliente.post(
        "/auditoria-csat",
        data={"accion": "analizar_csv", "archivo": (io.BytesIO(csv), "csat.csv")},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    fichas = _fichas(html)
    assert len(fichas) == 1
    assert _hidden(_formulario_fichas(html), "period_id") == ""


def test_guardar_auditoria_sin_campos_por_fila_conserva_decisiones(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    datos = _decidir(cliente, aid, pid, "1").get_json()
    r = cliente.post(
        "/auditoria-csat",
        data={"accion": "guardar_auditoria", "analysis_id": datos["analysis_id"], "period_id": pid},
    )
    assert r.status_code == 200
    por_id = {str(n["survey_id"]): n for n in store.negativos(pid)}
    assert por_id["1"]["decision_final"] == "SÍ" and por_id["1"]["origen_decision"] == "humana"


def test_reporte_ia_usa_las_palabras_de_la_pantalla(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    datos = _decidir(cliente, aid, pid, "1").get_json()
    r = cliente.post(
        "/auditoria-csat",
        data={"accion": "descargar_reporte_ia", "analysis_id": datos["analysis_id"], "period_id": pid},
    )
    texto = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "No fue culpa del agente" in texto and "CSAT real" in texto and "CSAT ajustado" in texto
    for viejo in ("SÍ justificable", "CSAT actualizado", "CSAT original", "TAL VEZ"):
        assert viejo not in texto


# --- Revisión final: un solo token por página, decisión sin JS y enlaces seguros ---


def test_pagina_lleva_el_token_a_lo_sumo_dos_veces(cliente, store, chatwoot):
    chatwoot.encuestas = [enc(i, rating=1) for i in range(1, 7)]
    html = _traer(cliente).get_data(as_text=True)
    aid = _hidden(html, "analysis_id")
    assert aid and len(_fichas(html)) == 6
    assert html.count(aid) <= 2
    # El formulario único de fichas lleva el token, el período y la acción una sola vez.
    formulario = _formulario_fichas(html)
    assert formulario.count('name="analysis_id"') == 1 and formulario.count('name="accion"') == 1
    assert 'value="decidir"' in formulario and 'name="prueba"' not in formulario


def test_formulario_de_fichas_lleva_prueba_en_modo_prueba(cliente, store, chatwoot):
    chatwoot.encuestas = [enc(1, rating=1)]
    html = _traer(cliente, prueba="1").get_data(as_text=True)
    assert 'name="prueba" value="1"' in _formulario_fichas(html)


def test_decidir_sin_js_con_el_boton_de_la_ficha(cliente, store, chatwoot):
    aid, pid = _dos_negativos(cliente, chatwoot)
    motivo = herramienta.MOTIVOS_INCONFORMIDAD[0]
    r = cliente.post(
        "/auditoria-csat",
        data={
            "accion": "decidir",
            "analysis_id": aid,
            "period_id": pid,
            "decision": "2|SÍ",
            "motivo__1": "",
            "nota__1": "no es esta",
            "motivo__2": motivo,
            "nota__2": "nota de la 2",
        },
    )
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Confirmado" in html
    assert _decision_actual(html, "2") == "SÍ" and _decision_actual(html, "1") == ""
    por_id = {str(n["survey_id"]): n for n in store.negativos(pid)}
    assert por_id["2"]["decision_final"] == "SÍ" and por_id["2"]["origen_decision"] == "humana"
    assert not por_id["1"].get("decision_final")
    with app.app_context():
        estado = herramienta.cargar_analisis(_hidden(html, "analysis_id"))
    fila = next(f for f in estado["rows"] if f["row_id"] == "2")
    assert fila["motivo_inconformidad"] == motivo and fila["comentario_auditor"] == "nota de la 2"


class StoreIntocable:
    def __getattr__(self, nombre):
        pytest.fail(f"En modo prueba no se debe tocar el store ({nombre})")


def test_decidir_en_modo_prueba_no_toca_el_store(cliente, store, chatwoot, monkeypatch):
    chatwoot.encuestas = [enc(1, rating=1), enc(2, rating=1)]
    html = _traer(cliente, prueba="1").get_data(as_text=True)
    monkeypatch.setattr(herramienta, "obtener_store_csat", lambda: StoreIntocable())
    aid = _hidden(html, "analysis_id")
    datos = _decidir(cliente, aid, "", "1", prueba="1").get_json()
    assert datos["ok"] and datos["ficha"]["confirmada"]
    r = cliente.post(
        "/auditoria-csat",
        data={"accion": "decidir", "analysis_id": datos["analysis_id"], "prueba": "1", "decision": "2|NO"},
        headers=JSON,
    )
    assert r.get_json()["ok"]
    assert store.listar_periodos() == []


def test_enlace_del_csv_no_se_usa_si_no_es_http(cliente):
    encabezado = ",".join(herramienta.EXPECTED_COLUMNS)
    valores = []
    for columna in herramienta.EXPECTED_COLUMNS:
        normal = herramienta.normalizar_texto(columna)
        if "calificacion" in normal:
            valores.append("1")
        elif "fecha" in normal:
            valores.append("2025-11-10 10:00")
        elif "enlace" in normal:
            valores.append("javascript:alert(1)")
        else:
            valores.append("x")
    csv = (encabezado + "\n" + ",".join(valores) + "\n").encode("utf-8")
    html = cliente.post(
        "/auditoria-csat",
        data={"accion": "analizar_csv", "archivo": (io.BytesIO(csv), "csat.csv")},
        content_type="multipart/form-data",
    ).get_data(as_text=True)
    (ficha,) = _fichas(html)
    assert "javascript:" not in ficha and "Abrir enlace" not in ficha
