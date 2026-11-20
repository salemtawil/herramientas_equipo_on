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


def _crear(store, chats_por_agente=3, agentes=AGENTES):
    return motor.crear_lote(
        store,
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
         "pct_satisfechos": 50.0, "por_revisar": 0, "revisados": 1, "errores": 0}
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
         "nota_efectiva_media": 3.5, "pct_revisado": 50.0},
        {"agente_id": 1, "agente_nombre": "Ana", "semana": "2026-11-16", "chats": 1,
         "nota_efectiva_media": 5.0, "pct_revisado": 0.0},
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
