import random
from datetime import date, datetime, timedelta, timezone

from utils import auditoria_chats_motor as motor
from utils.auditoria_chats_store import MemoriaAuditoriaStore
from utils.ia_chat import IARateLimitError

CLAVES = ["saludo", "comprension", "exactitud", "resolucion", "tono", "tiempos", "cierre"]
BASE_TS = int(datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc).timestamp())
CONFIG_IA = {"base_url": "https://ia.test/v1", "model": "modelo-prueba", "api_key": "k", "activa": True}


def _resultado(nota=4, satisfaccion="satisfecho", confianza="alta"):
    return {
        "criterios": {clave: nota for clave in CLAVES},
        "nota_global": nota,
        "satisfaccion_cliente": satisfaccion,
        "resuelto": "si",
        "resumen": "Bien.",
        "fortalezas": [],
        "mejoras": [],
        "evidencias": [],
        "confianza": confianza,
    }


def _mensajes(con_agente=True):
    mensajes = [{"id": 1, "message_type": 0, "content": "Hola", "created_at": BASE_TS}]
    if con_agente:
        mensajes.append({"id": 2, "message_type": 1, "content": "Buenos días", "created_at": BASE_TS + 60})
    return mensajes


class ChatwootFalso:
    def __init__(self, conversaciones, sin_agente=()):
        self.conversaciones = conversaciones  # {agente_id: [conversation_id, ...]}
        self.sin_agente = set(sin_agente)
        self.lecturas = []

    def conversaciones_de_agente(self, agente_id, since, until, page=1):
        ids = self.conversaciones.get(agente_id, [])
        pagina = ids[(page - 1) * 25 : page * 25]
        return [{"id": cid, "created_at": BASE_TS + i} for i, cid in enumerate(pagina)]

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        self.lecturas.append(conversation_id)
        return _mensajes(con_agente=conversation_id not in self.sin_agente)

    def url_conversacion(self, conversation_id):
        return f"https://chat.test/c/{conversation_id}"


AGENTES = [{"id": 1, "nombre": "Ana Pérez", "turno": "Mañana"}, {"id": 2, "nombre": "Luis Gómez", "turno": "Tarde"}]


def _crear(store, chats_por_agente=3, agentes=AGENTES, pauta_version="1"):
    return motor.crear_lote(
        store,
        pauta_version=pauta_version,
        since=date(2026, 11, 9),
        until=date(2026, 11, 15),
        alcance="todos",
        detalle={},
        chats_por_agente=chats_por_agente,
        agentes=agentes,
        config_ia=CONFIG_IA,
    )


def _ia_ok(monkeypatch, resultado=None):
    monkeypatch.setattr(motor, "completar_json", lambda mensajes, config, **k: resultado or _resultado())


def _correr(store, lote_id, chatwoot, rng=None, maximo=200):
    pasos = []
    for _ in range(maximo):
        paso = motor.ejecutar_paso(store, lote_id, chatwoot, CONFIG_IA, rng=rng or random.Random(0))
        pasos.append(paso)
        if paso["accion"] in ("fin", "espera", "configuracion") or paso["estado"] == "limite_diario":
            break
    return pasos


def test_rango_semana_anterior():
    assert motor.rango_semana_anterior(date(2026, 11, 19), "America/Caracas") == (date(2026, 11, 9), date(2026, 11, 15))
    assert motor.rango_semana_anterior(date(2026, 11, 16), "America/Caracas") == (date(2026, 11, 9), date(2026, 11, 15))


def test_resolver_agentes_por_turno_y_aviso_sin_cruce():
    agentes_chatwoot = [{"id": 1, "name": "Ana Perez"}, {"id": 2, "name": "Luis Gómez"}, {"id": 3, "name": "Eva"}]
    turnos = {"Mañana": ["Ana Pérez", "Nadie Existe"], "Tarde": ["Luis Gómez"]}
    agentes, avisos = motor.resolver_agentes("turno", {"turno": "Mañana"}, agentes_chatwoot, turnos)
    assert agentes == [{"id": 1, "nombre": "Ana Perez", "turno": "Mañana"}]
    assert avisos == ["Nadie Existe"]

    todos, _ = motor.resolver_agentes("todos", {}, agentes_chatwoot, turnos)
    assert [a["id"] for a in todos] == [1, 2, 3]
    assert todos[2]["turno"] is None

    elegidos, _ = motor.resolver_agentes("agentes", {"agentes": ["2"]}, agentes_chatwoot, turnos)
    assert elegidos == [{"id": 2, "nombre": "Luis Gómez", "turno": "Tarde"}]


def test_crear_lote_limita_chats_y_guarda_datos():
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=50)
    assert lote["chats_por_agente"] == 20
    assert lote["estado"] == "muestreando"
    assert lote["modelo"] == "modelo-prueba"
    assert lote["pauta_version"] == "1"
    assert lote["since"] < lote["until"]


def test_lote_completo_dos_agentes(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store)
    chatwoot = ChatwootFalso({1: [11, 12, 13, 14], 2: [21, 22, 23, 24]})
    pasos = _correr(store, lote["id"], chatwoot)

    assert pasos[-1]["accion"] == "fin"
    chats = store.listar_chats(lote["id"])
    assert len(chats) == 6
    assert all(c["estado"] == "auditado" for c in chats)
    assert all(not c.get("transcripcion_tmp") for c in chats)
    assert store.obtener_lote(lote["id"])["estado"] == "completado"
    assert pasos[-1]["progreso"] == {"total": 6, "auditados": 6, "errores": 0, "pendientes": 0}


def test_muestreo_excluye_ya_auditados_y_sin_mensajes_de_agente(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    previo = _crear(store, agentes=AGENTES[:1])
    store.insertar_chats([{"batch_id": previo["id"], "conversation_id": 11, "agente_id": 1, "estado": "auditado"}])
    lote = _crear(store, chats_por_agente=2, agentes=AGENTES[:1])
    chatwoot = ChatwootFalso({1: [11, 12, 13, 14]}, sin_agente={12})
    _correr(store, lote["id"], chatwoot)

    chats = store.listar_chats(lote["id"])
    auditados = sorted(c["conversation_id"] for c in chats if c["estado"] == "auditado")
    assert auditados == [13, 14]
    assert 11 not in [c["conversation_id"] for c in chats]
    assert [c["estado"] for c in chats if c["conversation_id"] == 12] == ["descartado"]


def test_agente_con_menos_chats_que_n(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=5)
    pasos = _correr(store, lote["id"], ChatwootFalso({1: [11], 2: []}))
    assert pasos[-1]["accion"] == "fin"
    assert pasos[-1]["progreso"]["total"] == 1
    muestreados = store.obtener_lote(lote["id"])["agentes_muestreados"]
    assert {m["id"]: m["elegidos"] for m in muestreados} == {1: 1, 2: 0}


def test_json_invalido_reintenta_una_vez_y_luego_error(monkeypatch):
    llamadas = []

    def ia_mala(mensajes, config, **k):
        llamadas.append(1)
        return {"nota_global": 9}

    monkeypatch.setattr(motor, "completar_json", ia_mala)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    pasos = _correr(store, lote["id"], ChatwootFalso({1: [11]}))

    chat = store.listar_chats(lote["id"])[0]
    assert len(llamadas) == 2
    assert chat["estado"] == "error"
    assert chat["por_revisar"] is True
    assert chat["ia_error"]
    assert not chat.get("transcripcion_tmp")
    assert store.obtener_lote(lote["id"])["estado"] == "con_errores"
    assert pasos[-1]["progreso"]["errores"] == 1


def test_429_minuto_devuelve_espera_y_no_pierde_fila(monkeypatch):
    def ia_limitada(mensajes, config, **k):
        raise IARateLimitError("minuto", esperar_segundos=9, diario=False)

    monkeypatch.setattr(motor, "completar_json", ia_limitada)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    pasos = _correr(store, lote["id"], ChatwootFalso({1: [11]}))

    assert pasos[-1]["accion"] == "espera"
    assert pasos[-1]["esperar_segundos"] == 9
    chat = store.listar_chats(lote["id"])[0]
    assert chat["estado"] == "leido"
    assert chat["transcripcion_tmp"]


def test_429_diario_pone_lote_en_limite_diario_y_se_retoma(monkeypatch):
    def ia_sin_cupo(mensajes, config, **k):
        raise IARateLimitError("día", esperar_segundos=3600, diario=True)

    monkeypatch.setattr(motor, "completar_json", ia_sin_cupo)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    chatwoot = ChatwootFalso({1: [11]})
    pasos = _correr(store, lote["id"], chatwoot)
    assert pasos[-1]["estado"] == "limite_diario"
    assert pasos[-1]["esperar_segundos"] == 0

    _ia_ok(monkeypatch)
    pasos = _correr(store, lote["id"], chatwoot)
    assert pasos[-1]["accion"] == "fin"
    assert store.listar_chats(lote["id"])[0]["estado"] == "auditado"


def test_ia_desactivada_no_toca_filas_leidas():
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    chatwoot = ChatwootFalso({1: [11]})
    sin_ia = dict(CONFIG_IA, api_key="", activa=False)
    paso = None
    for _ in range(10):
        paso = motor.ejecutar_paso(store, lote["id"], chatwoot, sin_ia, rng=random.Random(0))
        if paso["accion"] == "configuracion":
            break
    assert paso["accion"] == "configuracion"
    assert "AUDITORIA_CHATS_AI_API_KEY" in paso["mensaje"]
    assert store.listar_chats(lote["id"])[0]["estado"] == "leido"


def test_muestra_control_10_por_ciento_minimo_uno(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=5)
    _correr(store, lote["id"], ChatwootFalso({1: list(range(100, 110)), 2: list(range(200, 210))}), rng=random.Random(1))
    chats = store.listar_chats(lote["id"])
    control = [c for c in chats if c.get("motivo_revision") == "control"]
    assert len(chats) == 10
    assert len(control) == 1
    assert all(c["por_revisar"] for c in control)


def test_marcados_no_entran_en_control(monkeypatch):
    _ia_ok(monkeypatch, _resultado(nota=2, satisfaccion="insatisfecho"))
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=2, agentes=AGENTES[:1])
    _correr(store, lote["id"], ChatwootFalso({1: [11, 12]}))
    motivos = [c.get("motivo_revision") for c in store.listar_chats(lote["id"])]
    assert motivos == ["marcado", "marcado"]


def test_fila_procesando_abandonada_se_recupera(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    chatwoot = ChatwootFalso({1: [11]})
    motor.ejecutar_paso(store, lote["id"], chatwoot, CONFIG_IA, rng=random.Random(0))  # muestreo
    chat = store.listar_chats(lote["id"])[0]
    hace_5_min = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    store.chats[chat["id"]].update(estado="procesando", updated_at=hace_5_min)

    pasos = _correr(store, lote["id"], chatwoot)
    assert pasos[-1]["accion"] == "fin"
    assert store.obtener_chat(chat["id"])["estado"] == "auditado"


def test_nota_efectiva_y_resumen():
    assert motor.nota_efectiva({"ia_nota": 3, "nota_final": None}) == 3
    assert motor.nota_efectiva({"ia_nota": 3, "nota_final": 5}) == 5
    chats = [
        {"agente_id": 1, "agente_nombre": "Ana", "estado": "revisado", "ia_nota": 2, "nota_final": 4,
         "ia_satisfaccion": "insatisfecho", "satisfaccion_final": "satisfecho", "por_revisar": True},
        {"agente_id": 1, "agente_nombre": "Ana", "estado": "auditado", "ia_nota": 4, "nota_final": None,
         "ia_satisfaccion": "neutral", "por_revisar": False},
        {"agente_id": 1, "agente_nombre": "Ana", "estado": "descartado"},
    ]
    resumen = motor.resumen_por_agente(chats)
    assert resumen == [
        {"agente_id": 1, "agente_nombre": "Ana", "chats": 2, "nota_ia_media": 3.0, "nota_efectiva_media": 4.0,
         "pct_satisfechos": 50.0, "por_revisar": 0, "revisados": 1, "errores": 0,
         "qa_media": None, "estados": {"aprobado": 0, "necesita_mejorar": 0, "no_aprobado": 0, "pendiente": 0}}
    ]


def test_historial_semanal():
    chats = [
        {"agente_id": 1, "agente_nombre": "Ana", "estado": "auditado", "ia_nota": 4,
         "conversacion_fecha": "2026-11-10T14:00:00+00:00"},
        {"agente_id": 1, "agente_nombre": "Ana", "estado": "revisado", "ia_nota": 2, "nota_final": 3,
         "conversacion_fecha": "2026-11-12T14:00:00+00:00"},
        {"agente_id": 1, "agente_nombre": "Ana", "estado": "auditado", "ia_nota": 5,
         "conversacion_fecha": "2026-11-17T14:00:00+00:00"},
    ]
    filas = motor.historial_semanal(chats, "America/Caracas")
    assert filas == [
        {"agente_id": 1, "agente_nombre": "Ana", "semana": "2026-11-09", "chats": 2,
         "nota_efectiva_media": 3.5, "pct_revisado": 50.0, "qa_media": None},
        {"agente_id": 1, "agente_nombre": "Ana", "semana": "2026-11-16", "chats": 1,
         "nota_efectiva_media": 5.0, "pct_revisado": 0.0, "qa_media": None},
    ]


def test_filas_csv():
    lote = {"id": "l1"}
    chats = [
        {"conversation_id": 11, "agente_nombre": "Ana", "turno": "Mañana", "conversacion_fecha": "2026-11-10T14:00:00+00:00",
         "estado": "auditado", "ia_nota": 4, "ia_satisfaccion": "satisfecho",
         "ia_resultado": dict(_resultado(), resumen="Bien hecho"), "nota_final": None},
        {"conversation_id": 12, "estado": "descartado"},
    ]
    columnas, filas = motor.filas_csv(lote, chats, url_conversacion=lambda cid: f"https://c/{cid}")
    assert columnas[:3] == ["Conversación", "Enlace", "Agente"]
    assert len(filas) == 1
    assert filas[0][0] == 11 and filas[0][1] == "https://c/11"
    assert "Bien hecho" in filas[0]


# ---------------------------------------------------------------------------
# Correcciones de la revisión final
# ---------------------------------------------------------------------------


class StoreConCarrera(MemoriaAuditoriaStore):
    """Simula que otra pestaña se lleva la fila 'leido' justo antes de tomarla."""

    def __init__(self):
        super().__init__()
        self.robar_leido = False

    def tomar_siguiente(self, lote_id, estados, nuevo_estado):
        if self.robar_leido and estados == ("leido",):
            self.robar_leido = False
            for chat in self.chats.values():
                if chat.get("batch_id") == lote_id and chat.get("estado") == "leido":
                    chat["estado"] = "procesando"
            return None
        return super().tomar_siguiente(lote_id, estados, nuevo_estado)


def test_paso_no_devuelve_none_si_otra_pestana_tomo_el_leido(monkeypatch):
    _ia_ok(monkeypatch)
    store = StoreConCarrera()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    chatwoot = ChatwootFalso({1: [11]})
    motor.ejecutar_paso(store, lote["id"], chatwoot, CONFIG_IA, rng=random.Random(0))  # muestreo
    motor.ejecutar_paso(store, lote["id"], chatwoot, CONFIG_IA, rng=random.Random(0))  # lectura
    store.robar_leido = True
    paso = motor.ejecutar_paso(store, lote["id"], chatwoot, CONFIG_IA, rng=random.Random(0))
    assert isinstance(paso, dict)
    assert paso["accion"] == "espera"


def test_muestreo_no_repite_agente_ya_muestreado_por_otra_pestana():
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=2, agentes=AGENTES[:1])
    foto_vieja = store.obtener_lote(lote["id"])
    chatwoot = ChatwootFalso({1: [11, 12, 13, 14, 15, 16]})
    motor.ejecutar_paso(store, lote["id"], chatwoot, CONFIG_IA, rng=random.Random(0))
    motor._muestrear_agente(store, foto_vieja, AGENTES[0], chatwoot, random.Random(5))
    assert len(store.listar_chats(lote["id"])) == 2


class ChatwootConBordes(ChatwootFalso):
    """Página 1 solo con chats fuera del rango; página 2 con chats dentro."""

    def conversaciones_de_agente(self, agente_id, since, until, page=1):
        if page == 1:
            return [{"id": 900 + i, "created_at": since - 3600} for i in range(3)]
        if page == 2:
            return [{"id": 11, "created_at": since + 60}, {"id": 12, "created_at": until + 60}]
        return []


def test_muestreo_filtra_rango_y_sigue_paginando(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=5, agentes=AGENTES[:1])
    motor.ejecutar_paso(store, lote["id"], ChatwootConBordes({}), CONFIG_IA, rng=random.Random(0))
    assert [c["conversation_id"] for c in store.listar_chats(lote["id"])] == [11]


def test_control_no_se_duplica_tras_reintentar(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=5)
    chatwoot = ChatwootFalso({1: list(range(100, 110)), 2: list(range(200, 210))})
    _correr(store, lote["id"], chatwoot, rng=random.Random(1))
    sin_control = [c for c in store.listar_chats(lote["id"]) if c.get("motivo_revision") != "control"]
    store.actualizar_chat(sin_control[0]["id"], {"estado": "pendiente", "intentos": 0})
    store.actualizar_lote(lote["id"], {"estado": "auditando"})
    _correr(store, lote["id"], chatwoot, rng=random.Random(2))
    control = [c for c in store.listar_chats(lote["id"]) if c.get("motivo_revision") == "control"]
    assert len(control) == 1


def test_filas_csv_neutraliza_formulas():
    chats = [
        {"conversation_id": 11, "agente_nombre": "=cmd", "estado": "revisado", "comentario_revisor": "+SUMA(A1)",
         "ia_resultado": {"resumen": "@HYPERLINK(\"x\")", "criterios": {}}, "revisor": "-1"},
    ]
    _, filas = motor.filas_csv({}, chats)
    fila = filas[0]
    assert "'=cmd" in fila
    assert "'+SUMA(A1)" in fila
    assert "'@HYPERLINK(\"x\")" in fila
    assert "'-1" in fila
    assert fila[0] == 11


def test_error_de_configuracion_no_gasta_los_chats(monkeypatch):
    from utils.ia_chat import IAConfigError

    def ia_sin_modelo(mensajes, config, **k):
        raise IAConfigError("El modelo no existe.")

    monkeypatch.setattr(motor, "completar_json", ia_sin_modelo)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=2, agentes=AGENTES[:1])
    pasos = _correr(store, lote["id"], ChatwootFalso({1: [11, 12]}))
    assert pasos[-1]["accion"] == "configuracion"
    assert "El modelo no existe." in pasos[-1]["mensaje"]
    assert all(c["estado"] in ("leido", "pendiente") for c in store.listar_chats(lote["id"]))
    assert all(int(c.get("intentos") or 0) == 0 for c in store.listar_chats(lote["id"]))


class ChatwootConBandejas(ChatwootFalso):
    def __init__(self):
        super().__init__({})
        self.inbox_ids = []

    def conversaciones_de_agente(self, agente_id, since, until, page=1, inbox_ids=None):
        self.inbox_ids.append(inbox_ids)
        if page > 1:
            return []
        return [
            {"id": 11, "created_at": BASE_TS, "inbox_id": 3},
            {"id": 12, "created_at": BASE_TS, "inbox_id": 9},  # bandeja de llamadas
        ]


def test_muestreo_usa_solo_las_bandejas_del_lote(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = motor.crear_lote(
        store, since=date(2026, 11, 9), until=date(2026, 11, 15), alcance="agentes",
        detalle={"agentes": ["1"], "bandejas": [3]}, chats_por_agente=5, agentes=AGENTES[:1], config_ia=CONFIG_IA,
    )
    chatwoot = ChatwootConBandejas()
    motor.ejecutar_paso(store, lote["id"], chatwoot, CONFIG_IA, rng=random.Random(0))
    assert chatwoot.inbox_ids[0] == [3]
    assert [c["conversation_id"] for c in store.listar_chats(lote["id"])] == [11]


def test_error_temporal_espera_sin_gastar_intentos(monkeypatch):
    from utils.ia_chat import IATemporalError

    def ia_saturada(mensajes, config, **k):
        raise IATemporalError("Alta demanda.", esperar_segundos=30)

    monkeypatch.setattr(motor, "completar_json", ia_saturada)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    pasos = _correr(store, lote["id"], ChatwootFalso({1: [11]}))
    chat = store.listar_chats(lote["id"])[0]
    assert pasos[-1]["accion"] == "espera" and pasos[-1]["esperar_segundos"] == 30
    assert chat["estado"] == "leido" and int(chat.get("intentos") or 0) == 0


# ---------------------------------------------------------------------------
# Modelo de respaldo
# ---------------------------------------------------------------------------

CONFIG_CON_RESPALDO = dict(CONFIG_IA, model="principal", model_respaldo="respaldo")


def _ia_por_modelo(monkeypatch, comportamiento):
    """comportamiento: {modelo: excepción o None (=responde bien)}."""
    llamados = []

    def ia(mensajes, config, **k):
        llamados.append(config["model"])
        error = comportamiento.get(config["model"])
        if error:
            raise error
        return _resultado()

    monkeypatch.setattr(motor, "completar_json", ia)
    return llamados


def _auditar_un_chat(config):
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    chatwoot = ChatwootFalso({1: [11]})
    pasos = [motor.ejecutar_paso(store, lote["id"], chatwoot, config, rng=random.Random(0)) for _ in range(3)]
    return store, lote, pasos


def test_respaldo_audita_si_el_principal_esta_saturado(monkeypatch):
    from utils.ia_chat import IATemporalError

    llamados = _ia_por_modelo(monkeypatch, {"principal": IATemporalError("503")})
    store, lote, pasos = _auditar_un_chat(CONFIG_CON_RESPALDO)
    chat = store.listar_chats(lote["id"])[0]
    assert llamados == ["principal", "respaldo"]
    assert chat["estado"] == "auditado"
    assert chat["ia_resultado"]["modelo"] == "respaldo"


def test_respaldo_suma_cupo_cuando_el_principal_agoto_el_dia(monkeypatch):
    llamados = _ia_por_modelo(monkeypatch, {"principal": IARateLimitError("día", diario=True)})
    store, lote, _ = _auditar_un_chat(CONFIG_CON_RESPALDO)
    assert llamados == ["principal", "respaldo"]
    assert store.listar_chats(lote["id"])[0]["estado"] == "auditado"


def test_limite_diario_solo_si_ambos_modelos_lo_agotaron(monkeypatch):
    from utils.ia_chat import IATemporalError

    _ia_por_modelo(monkeypatch, {"principal": IARateLimitError("día", diario=True), "respaldo": IATemporalError("503")})
    store, lote, pasos = _auditar_un_chat(CONFIG_CON_RESPALDO)
    assert pasos[-1]["accion"] == "espera"
    assert store.obtener_lote(lote["id"])["estado"] != "limite_diario"

    _ia_por_modelo(monkeypatch, {"principal": IARateLimitError("día", diario=True), "respaldo": IARateLimitError("día", diario=True)})
    store, lote, pasos = _auditar_un_chat(CONFIG_CON_RESPALDO)
    assert store.obtener_lote(lote["id"])["estado"] == "limite_diario"


def test_error_de_configuracion_no_usa_respaldo(monkeypatch):
    from utils.ia_chat import IAConfigError

    llamados = _ia_por_modelo(monkeypatch, {"principal": IAConfigError("no existe")})
    _, _, pasos = _auditar_un_chat(CONFIG_CON_RESPALDO)
    assert llamados == ["principal"]
    assert pasos[-1]["accion"] == "configuracion"


def test_sin_respaldo_guarda_el_modelo_principal(monkeypatch):
    _ia_por_modelo(monkeypatch, {})
    store, lote, _ = _auditar_un_chat(dict(CONFIG_IA, model="principal"))
    assert store.listar_chats(lote["id"])[0]["ia_resultado"]["modelo"] == "principal"


# ---------------------------------------------------------------------------
# Llamadas, motivo de descarte y forma del chat
# ---------------------------------------------------------------------------


class ChatwootConLlamada(ChatwootFalso):
    def __init__(self, conversaciones, llamadas=(), sin_agente=()):
        super().__init__(conversaciones, sin_agente=sin_agente)
        self.llamadas = set(llamadas)

    def conversaciones_de_agente(self, agente_id, since, until, page=1, inbox_ids=None):
        return [dict(c, inbox_id=7) for c in super().conversaciones_de_agente(agente_id, since, until, page)]

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        if conversation_id in self.llamadas:
            return _mensajes() + [{"id": 3, "message_type": 2, "content_type": "voice_call", "created_at": BASE_TS + 90}]
        return super().mensajes_de_conversacion(conversation_id, max_paginas)


def test_llamada_se_descarta_y_se_reemplaza(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=2, agentes=AGENTES[:1])
    # 3 conversaciones, 2 llamadas: siempre queda al menos una llamada elegida y la reserva la reemplaza.
    chatwoot = ChatwootConLlamada({1: [11, 12, 13]}, llamadas={11, 12})
    _correr(store, lote["id"], chatwoot, rng=random.Random(3))
    chats = store.listar_chats(lote["id"])
    descartados = [c for c in chats if c["estado"] == "descartado"]
    assert descartados and all(c["detalle"]["motivo_descarte"] == "llamada" for c in descartados)
    assert [c["conversation_id"] for c in chats if c["estado"] == "auditado"] == [13]


def test_sin_respuesta_escrita_tiene_motivo(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    _correr(store, lote["id"], ChatwootConLlamada({1: [11]}, sin_agente={11}))
    chat = store.listar_chats(lote["id"])[0]
    assert chat["estado"] == "descartado"
    assert chat["detalle"]["motivo_descarte"] == "sin_respuesta_escrita"


def test_chat_auditado_guarda_bandeja_y_forma(monkeypatch):
    _ia_ok(monkeypatch)
    store = MemoriaAuditoriaStore()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    _correr(store, lote["id"], ChatwootConLlamada({1: [11]}))
    chat = store.listar_chats(lote["id"])[0]
    assert chat["estado"] == "auditado"
    assert chat["detalle"]["bandeja_id"] == 7
    assert [m["tipo"] for m in chat["detalle"]["forma"]] == [0, 1]


def test_valoracion_segun_nota_efectiva():
    assert motor.valoracion({"ia_nota": 5}) == "buena"
    assert motor.valoracion({"ia_nota": 4}) == "buena"
    assert motor.valoracion({"ia_nota": 3}) == "regular"
    assert motor.valoracion({"ia_nota": 2}) == "mala"
    assert motor.valoracion({"ia_nota": 2, "nota_final": 4}) == "buena"
    assert motor.valoracion({"estado": "error"}) is None


def _chat_feedback(nota, criterios, fortalezas=(), mejoras=(), **extra):
    chat = {
        "agente_id": 7, "agente_nombre": "LuisM", "estado": "auditado", "ia_nota": nota,
        "ia_resultado": {"criterios": criterios, "fortalezas": list(fortalezas), "mejoras": list(mejoras)},
    }
    chat.update(extra)
    return chat


def test_feedback_por_agente_agrupa_valoraciones_criterios_y_textos():
    base = {"saludo": 5, "comprension": 4, "exactitud": 4, "resolucion": 4, "tono": 5, "tiempos": 3, "cierre": 2}
    chats = [
        _chat_feedback(5, base, fortalezas=["Saluda con cordialidad"], mejoras=["Despedirse"]),
        _chat_feedback(3, dict(base, cierre=1), fortalezas=["saluda con cordialidad"], mejoras=["Confirmar si queda algo"]),
        _chat_feedback(2, dict(base, resolucion=2), estado="revisado", nota_final=2, comentario_revisor="Faltó dar el paso siguiente"),
        {"agente_id": 7, "agente_nombre": "LuisM", "estado": "descartado"},
        {"agente_id": 7, "agente_nombre": "LuisM", "estado": "error", "ia_error": "x"},
    ]
    [fila] = motor.feedback_por_agente(chats)
    assert fila["agente_nombre"] == "LuisM"
    assert fila["auditados"] == 3
    assert fila["valoraciones"] == {"buena": 1, "regular": 1, "mala": 1}
    assert fila["nota_media"] == 3.3
    assert [c["clave"] for c in fila["puntos_fuertes"]] == ["saludo", "tono", "comprension"]
    assert [c["clave"] for c in fila["areas_mejora"]] == ["cierre", "tiempos", "resolucion"]
    assert fila["areas_mejora"][0]["media"] == 1.7
    assert fila["fortalezas"] == ["Saluda con cordialidad"]
    assert fila["mejoras"] == ["Despedirse", "Confirmar si queda algo"]
    assert fila["comentarios"] == ["Faltó dar el paso siguiente"]


# --- Flujo QA-1.1: lectura, clasificación y evaluación ---

import pytest  # noqa: E402

from utils.auditoria_chats_rubrica import CRITERIOS_QA, PAUTA_VERSION_QA  # noqa: E402
from utils.auditoria_chats_store import AuditoriaChatsError  # noqa: E402

MANUAL = [
    {"codigo": c, "titulo": f"Sección {c}", "texto": f"Texto {c}", "orden": i}
    for i, c in enumerate(["1.1.1", "1.1.3", "1.1.8", "1.2.5", "1.4.1", "1.1.5"])
]


def _evaluacion_qa(resultado="cumple", fallas=()):
    return {
        "criterios": {c: {"resultado": resultado, "evidencias": ["m2"], "comentario": "ok"} for c, _, _ in CRITERIOS_QA},
        "fallas_criticas": [{"codigo": f, "evidencias": ["m2"], "descripcion": "x"} for f in fallas],
        "cumplimientos": ["Saluda"],
        "incumplimientos": [],
        "recomendaciones": ["Despedirse"],
        "estado_resolucion": "resuelto",
        "responsabilidad": "agente",
        "satisfaccion_cliente": "satisfecho",
        "resumen": "Bien.",
        "confianza": "alta",
    }


class IAFalsaQA:
    def __init__(self, evaluacion=None):
        self.llamadas = []
        self.evaluacion = evaluacion or _evaluacion_qa()

    def __call__(self, mensajes, config, **kwargs):
        es_evaluacion = "INSTRUCCIONES DE RESPUESTA" in mensajes[0]["content"]
        self.llamadas.append("evaluacion" if es_evaluacion else "clasificacion")
        if es_evaluacion:
            return self.evaluacion
        return {"motivo_principal": "Pausa", "procedimientos": ["P03"], "secciones_extra": ["1.1.5"], "servicio": "Compinche"}


def _store_qa():
    store = MemoriaAuditoriaStore()
    store.guardar_manual("3.0", MANUAL)
    return store


def _correr_contando(store, lote_id, chatwoot, ia, maximo=100):
    for _ in range(maximo):
        antes = len(ia.llamadas)
        paso = motor.ejecutar_paso(store, lote_id, chatwoot, CONFIG_IA, rng=random.Random(0))
        assert len(ia.llamadas) - antes <= 1
        if paso["accion"] in ("fin", "espera", "configuracion") or paso["estado"] == "limite_diario":
            return paso
    raise AssertionError("El lote no terminó")


def test_crear_lote_qa_sin_manual_lanza(monkeypatch):
    monkeypatch.delenv("AUDITORIA_CHATS_MANUAL_VERSION", raising=False)
    with pytest.raises(AuditoriaChatsError):
        _crear(MemoriaAuditoriaStore(), pauta_version=PAUTA_VERSION_QA)


def test_lote_qa_completo_clasifica_y_evalua(monkeypatch):
    monkeypatch.delenv("AUDITORIA_CHATS_MANUAL_VERSION", raising=False)
    store = _store_qa()
    ia = IAFalsaQA()
    monkeypatch.setattr(motor, "completar_json", ia)
    lote = _crear(store, chats_por_agente=2, agentes=AGENTES[:1], pauta_version=PAUTA_VERSION_QA)
    assert lote["pauta_version"] == PAUTA_VERSION_QA
    assert lote["alcance_detalle"]["manual_version"] == "3.0"
    paso = _correr_contando(store, lote["id"], ChatwootFalso({1: [101, 102]}), ia)
    assert paso["accion"] == "fin"
    assert ia.llamadas == ["clasificacion", "evaluacion", "clasificacion", "evaluacion"] or sorted(ia.llamadas) == [
        "clasificacion", "clasificacion", "evaluacion", "evaluacion"
    ]
    chats = store.listar_chats(lote["id"])
    for chat in chats:
        assert chat["estado"] == "auditado"
        assert chat["ia_qa"] == 100.0 and chat["ia_estado"] == "aprobado" and chat["ia_nota"] is None
        assert chat["ia_resultado"]["pauta_version"] == PAUTA_VERSION_QA
        assert chat["ia_resultado"]["criterios"]["A1"]["evidencias"] == ["m2"]
        assert chat["detalle"]["clasificacion"]["procedimientos"] == ["P03"]
        assert chat["detalle"]["periodo"] == {"desde": None, "hasta": None, "inferido": False}  # mensajes sin remitente
        assert chat["detalle"]["ids"] == ["m1", "m2"]
        assert "primera_respuesta" in chat["detalle"]["metricas"]
        assert chat["transcripcion_tmp"] is None


def test_lote_qa_envia_solo_las_secciones_aplicables(monkeypatch):
    store = _store_qa()
    vistos = []

    def ia(mensajes, config, **kwargs):
        if "INSTRUCCIONES DE RESPUESTA" in mensajes[0]["content"]:
            vistos.append(mensajes[1]["content"])
            return _evaluacion_qa()
        return {"motivo_principal": "Pausa", "procedimientos": ["P03"], "secciones_extra": [], "servicio": "Compinche"}

    monkeypatch.setattr(motor, "completar_json", ia)
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1], pauta_version=PAUTA_VERSION_QA)
    _correr(store, lote["id"], ChatwootFalso({1: [101]}))
    assert "Texto 1.4.1" in vistos[0] and "Texto 1.1.1" in vistos[0] and "Texto 1.1.5" not in vistos[0]


def test_lote_qa_falla_sospechosa_queda_pendiente_y_por_revisar(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaQA(_evaluacion_qa(fallas=["CR04"])))
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1], pauta_version=PAUTA_VERSION_QA)
    _correr(store, lote["id"], ChatwootFalso({1: [101]}))
    [chat] = store.listar_chats(lote["id"])
    assert chat["ia_estado"] == "pendiente" and chat["por_revisar"] is True
    assert chat["ia_resultado"]["fallas_criticas"][0]["estado"] == "sospechosa"


def test_lote_qa_limite_diario_en_clasificacion_no_pierde_fila(monkeypatch):
    store = _store_qa()

    def ia(mensajes, config, **kwargs):
        raise IARateLimitError("Sin cupo diario", diario=True)

    monkeypatch.setattr(motor, "completar_json", ia)
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1], pauta_version=PAUTA_VERSION_QA)
    pasos = _correr(store, lote["id"], ChatwootFalso({1: [101]}))
    assert pasos[-1]["estado"] == "limite_diario"
    [chat] = store.listar_chats(lote["id"])
    assert chat["estado"] == "leido" and chat["transcripcion_tmp"]


def test_lote_qa_json_invalido_en_evaluacion_reintenta_y_luego_error(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaQA({"criterios": {}}))
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1], pauta_version=PAUTA_VERSION_QA)
    _correr(store, lote["id"], ChatwootFalso({1: [101]}))
    [chat] = store.listar_chats(lote["id"])
    assert chat["estado"] == "error" and chat["intentos"] == motor.MAX_INTENTOS_IA


def test_abandonado_con_clasificacion_vuelve_a_clasificado():
    store = _store_qa()
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1], pauta_version=PAUTA_VERSION_QA)
    store.insertar_chats([{"batch_id": lote["id"], "conversation_id": 5, "agente_id": 1, "estado": "procesando"}])
    [chat] = store.listar_chats(lote["id"])
    viejo = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    store.chats[chat["id"]].update(
        transcripcion_tmp="[m1 10:00:00] Cliente: hola", detalle={"clasificacion": {"motivo_principal": "x"}}, updated_at=viejo
    )
    motor._recuperar_abandonados(store, store.listar_chats(lote["id"]))
    assert store.obtener_chat(chat["id"])["estado"] == "clasificado"


# --- Resúmenes y exportes QA-1.1 ---


def _chat_qa(qa, ia_estado, criterios=None, **extra):
    criterios = criterios or {c: "cumple" for c, _, _ in CRITERIOS_QA}
    chat = {
        "agente_id": 7, "agente_nombre": "LuisM", "estado": "auditado", "conversation_id": extra.pop("cid", 1),
        "ia_qa": qa, "ia_estado": ia_estado, "ia_satisfaccion": "satisfecho",
        "ia_resultado": {
            "pauta_version": PAUTA_VERSION_QA,
            "criterios": {c: {"resultado": r, "evidencias": [], "comentario": "c"} for c, r in criterios.items()},
            "fallas_criticas": [], "cumplimientos": ["Saluda bien"], "incumplimientos": ["No documenta"],
            "recomendaciones": ["Dejar nota"], "resumen": "R", "estado_resolucion": "resuelto",
        },
        "detalle": {"clasificacion": {"motivo_principal": "Pausa", "procedimientos": ["P03"]}},
    }
    chat.update(extra)
    return chat


def test_qa_y_estado_efectivos():
    assert motor.qa_efectivo({"ia_qa": 80.0}) == 80.0
    assert motor.qa_efectivo({"ia_qa": 80.0, "qa_final": 90.0}) == 90.0
    assert motor.estado_efectivo({"ia_estado": "pendiente", "estado_final": "aprobado"}) == "aprobado"
    assert motor.estado_efectivo({"ia_estado": "necesita_mejorar"}) == "necesita_mejorar"


def test_feedback_por_agente_qa_usa_criterios_corregidos():
    base = {c: "cumple" for c, _, _ in CRITERIOS_QA}
    chats = [
        _chat_qa(100.0, "aprobado", dict(base, F2="no_cumple", E2="parcial")),
        _chat_qa(75.0, "necesita_mejorar", dict(base, F2="no_cumple", B1="no_verificable", E2="no_cumple")),
        _chat_qa(60.0, "pendiente", dict(base, F2="no_cumple", E2="no_cumple"), estado="revisado",
                 qa_final=90.0, estado_final="aprobado", comentario_revisor="Bien resuelto",
                 revision={"criterios": {"E2": "cumple"}, "fallas": {"CR04": "confirmada"}}),
        {"agente_id": 7, "agente_nombre": "LuisM", "estado": "descartado"},
    ]
    [fila] = motor.feedback_por_agente_qa(chats)
    assert fila["auditados"] == 3
    assert fila["qa_media"] == 88.3
    assert fila["estados"] == {"aprobado": 2, "necesita_mejorar": 1, "no_aprobado": 0, "pendiente": 0}
    assert fila["fallas_confirmadas"] == 1
    assert [c["codigo"] for c in fila["areas_mejora"]] == ["F2", "E2"]
    assert fila["areas_mejora"][0]["pct"] == 0.0 and fila["areas_mejora"][1]["pct"] == 50.0
    assert [c["codigo"] for c in fila["puntos_fuertes"]] == ["A1", "A2", "B1"]
    assert [t["texto"] for t in fila["cumplimientos"]] == ["Saluda bien"]
    assert [t["texto"] for t in fila["recomendaciones"]] == ["Dejar nota"]
    assert fila["comentarios"] == ["Bien resuelto"]


def test_feedback_qa_referencia_los_chats_de_cada_area_de_mejora():
    base = {c: "cumple" for c, _, _ in CRITERIOS_QA}
    chats = [
        _chat_qa(90.0, "aprobado", dict(base, E2="parcial"), id="a", cid=101),
        _chat_qa(70.0, "necesita_mejorar", dict(base, E2="no_cumple"), id="b", cid=102),
        _chat_qa(100.0, "aprobado", base, id="c", cid=103),
    ]
    chats[2]["ia_resultado"]["incumplimientos"] = ["no documenta", "Tarda en responder"]
    [fila] = motor.feedback_por_agente_qa(chats)
    [e2] = [c for c in fila["areas_mejora"] if c["codigo"] == "E2"]
    assert e2["chats"] == [{"id": "a", "conversation_id": 101}, {"id": "b", "conversation_id": 102}]
    assert fila["incumplimientos"] == [
        {"texto": "No documenta", "chats": [
            {"id": "a", "conversation_id": 101}, {"id": "b", "conversation_id": 102}, {"id": "c", "conversation_id": 103}]},
        {"texto": "Tarda en responder", "chats": [{"id": "c", "conversation_id": 103}]},
    ]


def test_resumen_e_historial_incluyen_qa():
    chats = [
        _chat_qa(80.0, "necesita_mejorar", conversacion_fecha="2026-11-10T14:00:00+00:00"),
        _chat_qa(90.0, "aprobado", conversacion_fecha="2026-11-11T14:00:00+00:00"),
    ]
    [fila] = motor.resumen_por_agente(chats)
    assert fila["qa_media"] == 85.0 and fila["estados"]["aprobado"] == 1
    [semana] = motor.historial_semanal(chats, "America/Caracas")
    assert semana["qa_media"] == 85.0 and semana["chats"] == 2


def test_filas_csv_qa():
    lote = {"pauta_version": PAUTA_VERSION_QA}
    chat = _chat_qa(80.0, "necesita_mejorar", comentario_revisor="=HYPERLINK(1)")
    columnas, filas = motor.filas_csv(lote, [chat])
    assert "QA IA" in columnas and "Estado IA" in columnas and "A1 Identificación del problema" in columnas
    fila = dict(zip(columnas, filas[0]))
    assert fila["QA IA"] == 80.0 and fila["Estado IA"] == "NECESITA MEJORAR"
    assert fila["Motivo"] == "Pausa" and fila["Procedimientos"] == "P03"
    assert fila["A1 Identificación del problema"] == "Cumple"
    assert fila["Comentario"] == "'=HYPERLINK(1)"


# --- Llamadas de Multiadmin en lotes QA ---

from utils.multiadmin_llamadas import MultiadminLlamadasError  # noqa: E402


def _llamada_ma(record, agente, ticket, puntaje=80.0, ts=BASE_TS, buzon=False):
    return {
        "callId": "compinche1", "recordKey": record, "ticketId": str(ticket), "agentNumber": agente,
        "customerNumber": "+15550001111", "createdAt": ts * 1000, "durationSec": 120,
        "metadata": {"callType": "inbound", "isVoicemail": buzon}, "analytics": {"issueType": "Consulta"},
        "scores": {"overall": puntaje}, "sentiment": {"agent": "positivo", "customer": "neutral"},
    }


class MultiadminFalso:
    def __init__(self, por_dia, falla=False):
        self.por_dia = por_dia  # lista de listas, una por día
        self.falla = falla
        self.dias_pedidos = []
        self.detalles = 0

    def listar_llamadas(self, desde_ms, hasta_ms):
        if self.falla:
            raise MultiadminLlamadasError("Multiadmin respondió 500 al pedir las llamadas.")
        self.dias_pedidos.append((desde_ms, hasta_ms))
        indice = len(self.dias_pedidos) - 1
        return self.por_dia[indice] if indice < len(self.por_dia) else []

    def detalle_llamada(self, call_id, record_key):
        self.detalles += 1
        return {"rubric": {"items": [{"name": "Empatia", "percentScore": 50, "weightPct": 10, "notes": "n"}]},
                "coaching": {"topWins": ["Cordial"], "topImprovements": ["Pasos"], "nextActions": ["Confirmar"]},
                "keyPoints": [], "analytics": {}}


class IAFalsaLlamadas(IAFalsaQA):
    def __call__(self, mensajes, config, **kwargs):
        if "coach de calidad" in mensajes[0]["content"]:
            self.llamadas.append("resumen_llamadas")
            return {"puntos_fuertes": [{"texto": "Cordial", "tickets": [501, 999]}], "areas_mejora": [],
                    "recomendaciones": [], "buzon_voz": None, "resumen": "Bien."}
        return super().__call__(mensajes, config, **kwargs)


def _crear_qa_dos_dias(store):
    return motor.crear_lote(
        store, since=date(2026, 11, 9), until=date(2026, 11, 10), alcance="agentes", detalle={},
        chats_por_agente=1, agentes=AGENTES[:1], config_ia=CONFIG_IA, pauta_version=PAUTA_VERSION_QA,
    )


def _correr_con(store, lote_id, chatwoot, multiadmin, maximo=100):
    pasos = []
    for _ in range(maximo):
        paso = motor.ejecutar_paso(store, lote_id, chatwoot, CONFIG_IA, rng=random.Random(0), multiadmin=multiadmin)
        pasos.append(paso)
        if paso["accion"] in ("fin", "espera", "configuracion"):
            break
    return pasos


def test_lote_qa_trae_llamadas_solo_de_sus_agentes_y_las_resume(monkeypatch):
    store = _store_qa()
    ia = IAFalsaLlamadas()
    monkeypatch.setattr(motor, "completar_json", ia)
    lote = _crear_qa_dos_dias(store)
    multiadmin = MultiadminFalso([
        [_llamada_ma("r1", "Ana Pérez", 501), _llamada_ma("r2", "Otro Agente", 502)],
        [_llamada_ma("r3", "Ana Pérez", 503, buzon=True)],
    ])
    pasos = _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert pasos[-1]["accion"] == "fin"
    assert len(multiadmin.dias_pedidos) == 2
    llamadas = store.listar_llamadas(lote["id"])
    assert sorted(l["record_key"] for l in llamadas) == ["r1", "r3"]
    assert all(l["agente_id"] == 1 and l["detalle_ok"] for l in llamadas)
    assert [l["sin_conversacion"] for l in sorted(llamadas, key=lambda l: l["record_key"])] == [False, True]
    final = store.obtener_lote(lote["id"])
    assert final["llamadas_estado"] == "listo"
    assert final["llamadas_sin_emparejar"] == {"Otro Agente": 1}
    assert final["feedback_llamadas"]["1"]["puntos_fuertes"] == [{"texto": "Cordial", "tickets": [501]}]
    assert ia.llamadas.count("resumen_llamadas") == 1
    assert ia.llamadas.index("resumen_llamadas") == len(ia.llamadas) - 1  # el resumen va después de los chats


def test_error_de_multiadmin_no_bloquea_los_chats(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaLlamadas())
    lote = _crear_qa_dos_dias(store)
    pasos = _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), MultiadminFalso([], falla=True))
    assert pasos[-1]["accion"] == "fin"
    final = store.obtener_lote(lote["id"])
    assert final["llamadas_estado"] == "error" and "500" in final["llamadas_error"]
    assert all(c["estado"] == "auditado" for c in store.listar_chats(lote["id"]))


def test_lote_v1_no_toca_llamadas(monkeypatch):
    store = MemoriaAuditoriaStore()
    _ia_ok(monkeypatch)
    lote = _crear(store, chats_por_agente=1, agentes=AGENTES[:1])
    multiadmin = MultiadminFalso([[_llamada_ma("r1", "Ana Pérez", 501)]])
    _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert multiadmin.dias_pedidos == [] and store.listar_llamadas(lote["id"]) == []


def test_reiniciar_llamadas_de_un_agente_y_retomar_lote_terminado(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaLlamadas())
    lote = _crear_qa_dos_dias(store)
    multiadmin = MultiadminFalso([[_llamada_ma("r1", "Ana Pérez", 501)], []])
    _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    motor.reiniciar_llamadas(store, lote["id"], agente_id=1)
    reiniciado = store.obtener_lote(lote["id"])
    assert reiniciado["llamadas_estado"] == "trayendo" and "1" not in reiniciado["feedback_llamadas"]
    assert store.listar_llamadas(lote["id"]) == []
    multiadmin.dias_pedidos.clear()
    multiadmin.por_dia = [[_llamada_ma("r1", "Ana Pérez", 501)], []]
    pasos = _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert pasos[-1]["accion"] == "fin"
    assert store.obtener_lote(lote["id"])["llamadas_estado"] == "listo"
    assert len(store.listar_llamadas(lote["id"])) == 1


def test_emparejamiento_automatico_se_mantiene_entre_dias(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaLlamadas())
    lote = motor.crear_lote(
        store, since=date(2026, 11, 9), until=date(2026, 11, 10), alcance="agentes", detalle={},
        chats_por_agente=1, agentes=[{"id": 1, "nombre": "Juan", "turno": "Mañana"}], config_ia=CONFIG_IA,
        pauta_version=PAUTA_VERSION_QA,
    )
    multiadmin = MultiadminFalso([
        [_llamada_ma("r1", "Juan Pérez", 501)],
        [_llamada_ma("r2", "Juan Pérez", 502), _llamada_ma("r3", "Juan López", 503)],
    ])
    _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert sorted(l["record_key"] for l in store.listar_llamadas(lote["id"])) == ["r1", "r2"]
    assert store.emparejamientos()["Juan Pérez"] == {"chatwoot_agente_id": 1, "manual": False}


class MultiadminConDetalleRoto(MultiadminFalso):
    def __init__(self, por_dia, codigo):
        super().__init__(por_dia)
        self.codigo = codigo

    def detalle_llamada(self, call_id, record_key):
        if record_key == "roto":
            raise MultiadminLlamadasError("Multiadmin respondió con error.", status=self.codigo)
        return super().detalle_llamada(call_id, record_key)


def test_detalle_inexistente_de_una_llamada_no_bloquea_las_demas(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaLlamadas())
    lote = _crear_qa_dos_dias(store)
    multiadmin = MultiadminConDetalleRoto([[_llamada_ma("roto", "Ana Pérez", 501), _llamada_ma("r2", "Ana Pérez", 502)], []], 404)
    pasos = _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert pasos[-1]["accion"] == "fin"
    assert store.obtener_lote(lote["id"])["llamadas_estado"] == "listo"
    rotas = [l for l in store.listar_llamadas(lote["id"]) if l["record_key"] == "roto"]
    assert rotas[0]["detalle_ok"] is True and rotas[0]["detalle_error"]


def test_reanudar_tras_error_conserva_lo_traido(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaLlamadas())
    lote = _crear_qa_dos_dias(store)
    multiadmin = MultiadminConDetalleRoto([[_llamada_ma("roto", "Ana Pérez", 501)], []], 503)
    _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert store.obtener_lote(lote["id"])["llamadas_estado"] == "error"
    pedidos = len(multiadmin.dias_pedidos)
    motor.reanudar_llamadas(store, lote["id"])
    assert store.obtener_lote(lote["id"])["llamadas_estado"] == "detallando"
    multiadmin.codigo = 404
    _correr_con(store, lote["id"], ChatwootFalso({1: [101]}), multiadmin)
    assert len(multiadmin.dias_pedidos) == pedidos  # no vuelve a traer los días
    assert store.obtener_lote(lote["id"])["llamadas_estado"] == "listo"


def test_emparejar_a_mano_mueve_las_llamadas_del_dueno_anterior(monkeypatch):
    store = _store_qa()
    monkeypatch.setattr(motor, "completar_json", IAFalsaLlamadas())
    lote = motor.crear_lote(
        store, since=date(2026, 11, 9), until=date(2026, 11, 9), alcance="agentes", detalle={},
        chats_por_agente=1, agentes=[{"id": 1, "nombre": "Juan", "turno": "M"}, {"id": 2, "nombre": "Pedro", "turno": "M"}],
        config_ia=CONFIG_IA, pauta_version=PAUTA_VERSION_QA,
    )
    multiadmin = MultiadminFalso([[_llamada_ma("r1", "Juan Pérez", 501)]])
    _correr_con(store, lote["id"], ChatwootFalso({1: [101], 2: [102]}), multiadmin)
    assert store.listar_llamadas(lote["id"])[0]["agente_id"] == 1
    motor.emparejar_a_mano(store, lote["id"], "Juan Pérez", 2)
    assert store.listar_llamadas(lote["id"]) == []
    feedback = store.obtener_lote(lote["id"])["feedback_llamadas"]
    assert "1" not in feedback and "2" not in feedback
    multiadmin.dias_pedidos.clear()
    _correr_con(store, lote["id"], ChatwootFalso({1: [101], 2: [102]}), multiadmin)
    assert store.listar_llamadas(lote["id"])[0]["agente_id"] == 2
