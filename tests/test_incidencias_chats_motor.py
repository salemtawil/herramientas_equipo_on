import pytest

from utils import incidencias_chats_motor as motor
from utils.incidencias_chats_store import MemoriaIncidenciasStore

SINCE = 1_700_000_000
UNTIL = SINCE + 24 * 3600
BANDEJA = 3


def _m(id, tipo, texto, t, **extra):
    mensaje = {"id": id, "message_type": tipo, "content": texto, "created_at": t, "private": False}
    if tipo == 1:
        mensaje["sender_type"] = "user"
        mensaje["sender"] = {"id": 7, "name": "Luis Gómez"}
    mensaje.update(extra)
    return mensaje


def _normal(cid, t):
    return [_m(cid * 10 + 1, 0, "Hola, una consulta", t), _m(cid * 10 + 2, 1, "Hola, te ayudo", t + 30)]


def _cobro(cid, t):
    return [
        _m(cid * 10 + 1, 0, "Hola, me cobraron dos veces el pedido", t),
        _m(cid * 10 + 2, 1, "Lo reviso ya mismo", t + 30),
    ]


def _llamada(cid, t):
    return [_m(cid * 10 + 1, 0, "Llamada", t, content_type="voice_call")]


def _conv(cid, created_at, inbox_id=BANDEJA, status="resolved", last_activity_at=None):
    return {
        "id": cid,
        "created_at": created_at,
        "inbox_id": inbox_id,
        "status": status,
        "last_activity_at": last_activity_at or created_at + 60,
        "meta": {"assignee": {"id": 7, "name": "Luis Gómez"}},
    }


class ChatwootFalso:
    def __init__(self, conversaciones, mensajes, csat=None, fallan=(), csat_falla=False):
        self.conversaciones = conversaciones
        self.mensajes = mensajes
        self.csat = csat or []
        self.fallan = set(fallan)
        self.csat_falla = csat_falla
        self.lecturas = []
        self.paginas = []

    def conversaciones_en_rango(self, since, until, page=1, inbox_ids=None):
        self.paginas.append(page)
        return list(self.conversaciones[(page - 1) * 25 : page * 25])

    def mensajes_de_conversacion(self, conversation_id):
        self.lecturas.append(int(conversation_id))
        if int(conversation_id) in self.fallan:
            raise RuntimeError("Chatwoot no responde")
        return list(self.mensajes[int(conversation_id)])

    def respuestas_csat(self, since, until):
        if self.csat_falla:
            raise RuntimeError("CSAT caído")
        return list(self.csat)


def _reloj(paso=1.0):
    estado = {"t": 0.0}

    def reloj():
        estado["t"] += paso
        return estado["t"]

    return reloj


def _escenario(n=30, cobro=(), llamadas=(), **kwargs):
    conversaciones, mensajes = [], {}
    for i in range(1, n + 1):
        t = SINCE + i * 60
        conversaciones.append(_conv(i, t))
        if i in cobro:
            mensajes[i] = _cobro(i, t)
        elif i in llamadas:
            mensajes[i] = _llamada(i, t)
        else:
            mensajes[i] = _normal(i, t)
    return ChatwootFalso(conversaciones, mensajes, **kwargs)


def _nueva(store):
    return motor.crear_revision(store, since=SINCE, until=UNTIL, bandejas=[BANDEJA], usar_ia=False, creado_por="ana")


def _correr(store, revision_id, chatwoot, reloj=None, maximo=200):
    respuesta = None
    for _ in range(maximo):
        respuesta = motor.ejecutar_paso(store, revision_id, chatwoot, {}, ahora=UNTIL, reloj=reloj or _reloj())
        if respuesta["accion"] == "fin":
            return respuesta
    raise AssertionError(f"No terminó: {respuesta}")


def test_rango_invalido():
    store = MemoriaIncidenciasStore()
    with pytest.raises(ValueError):
        motor.crear_revision(store, since=SINCE, until=SINCE, bandejas=[], usar_ia=False, creado_por="")
    with pytest.raises(ValueError):
        motor.crear_revision(store, since=SINCE, until=SINCE + 73 * 3600, bandejas=[], usar_ia=False, creado_por="")
    revision = motor.crear_revision(store, since=SINCE, until=SINCE + 72 * 3600, bandejas=[], usar_ia=False, creado_por="")
    assert revision["estado"] == "listando" and revision["csat"] is None


def test_recorte_exacto_por_created_at_y_bandeja():
    conversaciones = [
        _conv(1, SINCE + 10),
        _conv(2, SINCE - 10),
        _conv(3, UNTIL + 10),
        _conv(4, SINCE + 20, inbox_id=99),
        _conv(5, UNTIL),
    ]
    chatwoot = ChatwootFalso(conversaciones, {i: _normal(i, SINCE) for i in range(1, 6)})
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    _correr(store, revision["id"], chatwoot)
    assert sorted(c["conversation_id"] for c in store.listar_chats(revision["id"])) == [1, 5]


def test_corre_hasta_fin():
    chatwoot = _escenario(30, cobro={7}, llamadas={3, 4})
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    respuesta = _correr(store, revision["id"], chatwoot)
    assert respuesta["estado"] == "completado"
    progreso = respuesta["progreso"]
    assert progreso["total"] == 30
    assert progreso["con_incidencias"] == 1
    assert progreso["descartados"] == 2
    assert progreso["evaluados"] == 28
    assert progreso["errores"] == 0
    chats = {c["conversation_id"]: c for c in store.listar_chats(revision["id"])}
    assert chats[7]["incidencias"][0]["clave"] == "cobros"
    assert chats[7]["resuelto"] is True and chats[7]["status"] == "resolved"
    assert chats[7]["reglas_version"] == motor.REGLAS_VERSION
    assert chats[7]["ia_estado"] is None
    assert all(not c.get("transcripcion_tmp") for c in chats.values())


def test_presupuesto_por_paso():
    chatwoot = _escenario(10)
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    paso = None
    for _ in range(5):
        paso = motor.ejecutar_paso(store, revision["id"], chatwoot, {}, ahora=UNTIL, reloj=_reloj(3.0))
        if paso["accion"] == "evaluacion":
            break
    assert paso["accion"] == "evaluacion"
    assert 1 <= len(chatwoot.lecturas) <= 3


def test_reutiliza_resuelto_sin_releer():
    chatwoot = _escenario(5, cobro={2})
    store = MemoriaIncidenciasStore()
    primera = _nueva(store)
    _correr(store, primera["id"], chatwoot)
    chatwoot.lecturas = []
    segunda = _nueva(store)
    respuesta = _correr(store, segunda["id"], chatwoot)
    assert 2 not in chatwoot.lecturas
    antes = {c["conversation_id"]: c for c in store.listar_chats(primera["id"])}
    despues = {c["conversation_id"]: c for c in store.listar_chats(segunda["id"])}
    assert despues[2]["estado"] == "evaluado"
    assert despues[2]["incidencias"] == antes[2]["incidencias"]
    assert respuesta["progreso"]["con_incidencias"] == 1


def test_relee_si_hubo_actividad():
    chatwoot = _escenario(5, cobro={2})
    store = MemoriaIncidenciasStore()
    primera = _nueva(store)
    _correr(store, primera["id"], chatwoot)
    chatwoot.lecturas = []
    chatwoot.conversaciones[1]["last_activity_at"] += 500
    segunda = _nueva(store)
    _correr(store, segunda["id"], chatwoot)
    assert 2 in chatwoot.lecturas


def test_dos_pestanas():
    chatwoot = _escenario(30, cobro={5})
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    terminadas = 0
    for _ in range(200):
        for _pestana in range(2):
            respuesta = motor.ejecutar_paso(store, revision["id"], chatwoot, {}, ahora=UNTIL, reloj=_reloj())
            terminadas += respuesta["accion"] == "fin"
        if terminadas >= 2:
            break
    ids = [c["conversation_id"] for c in store.listar_chats(revision["id"])]
    assert len(ids) == len(set(ids)) == 30
    assert sorted(chatwoot.lecturas) == list(range(1, 31))


def test_error_de_lectura_tres_intentos():
    chatwoot = _escenario(3, fallan={2})
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    respuesta = _correr(store, revision["id"], chatwoot)
    assert respuesta["estado"] == "con_errores"
    assert respuesta["progreso"]["errores"] == 1
    assert chatwoot.lecturas.count(2) == motor.MAX_INTENTOS
    chat = next(c for c in store.listar_chats(revision["id"]) if c["conversation_id"] == 2)
    assert chat["estado"] == "error" and chat["intentos"] == motor.MAX_INTENTOS

    assert motor.reintentar_errores(store, revision["id"]) == 1
    chat = next(c for c in store.listar_chats(revision["id"]) if c["conversation_id"] == 2)
    assert chat["estado"] == "pendiente" and chat["intentos"] == 0
    chatwoot.fallan = set()
    assert _correr(store, revision["id"], chatwoot)["estado"] == "completado"


def test_csat_falla_sigue():
    chatwoot = _escenario(3, csat_falla=True)
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    respuesta = _correr(store, revision["id"], chatwoot)
    assert respuesta["estado"] == "completado"
    guardada = store.obtener_revision(revision["id"])
    assert guardada["csat"] == {} and guardada["csat_error"]


def test_csat_bajo_se_usa():
    chatwoot = _escenario(3, csat=[{"conversation_id": 2, "rating": 1}, {"conversation_id": 3, "rating": "5"}])
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    _correr(store, revision["id"], chatwoot)
    chats = {c["conversation_id"]: c for c in store.listar_chats(revision["id"])}
    assert [i["clave"] for i in chats[2]["incidencias"]] == ["csat_bajo"]
    assert chats[3]["incidencias"] == []


def _incidencia(clave, severidad, ts, evidencia, coincidencia, tipo="cliente"):
    return {
        "tipo": tipo, "clave": clave, "etiqueta": clave.title(), "severidad": severidad, "evidencia": evidencia,
        "coincidencia": coincidencia, "mensaje_id": 1, "ts": ts, "agente_id": 7, "agente_nombre": "Luis",
        "origen": "reglas",
    }


def test_listas_orden_y_marca():
    chats = [
        {"id": "a", "conversation_id": 1, "status": "resolved", "ia_estado": None, "incidencias": [
            _incidencia("fallas_app", "media", 10, "La app no funciona hoy", "no funciona"),
        ]},
        {"id": "b", "conversation_id": 2, "status": "open", "ia_estado": None, "incidencias": [
            _incidencia("cobros", "alta", 50, "Hola, me cobraron dos veces ayer", "me cobraron dos veces"),
            _incidencia("espera_larga", "media", 60, "Esperó 20 min", "", tipo="atencion"),
        ]},
    ]
    listas = motor.listas_revision(chats, {2: {"decision": "atendida", "por": "ana"}})
    cliente = listas["cliente"]
    assert [f["clave"] for f in cliente] == ["cobros", "fallas_app"]
    for fila in cliente + listas["atencion"]:
        assert fila["antes"] + fila["marca"] + fila["despues"] == fila["evidencia"]
    assert cliente[0]["marca"] == "me cobraron dos veces" and cliente[0]["chat_id"] == "b"
    assert cliente[0]["decision"]["decision"] == "atendida"
    assert listas["atencion"][0]["marca"] == ""
    assert listas["agentes"] == ["Luis"]
    assert ("cobros", "Cobros") in listas["claves"]
    assert [f["clave"] for f in motor.listas_revision(chats, {}, clave="cobros")["cliente"]] == ["cobros"]


def test_filas_csv_protege_formulas():
    chats = [{"id": "a", "conversation_id": 1, "ia_estado": None, "incidencias": [
        _incidencia("cobros", "alta", SINCE, "=HYPERLINK(1)", "")]}]
    filas = motor.filas_csv({}, chats, {1: {"decision": "atendida", "por": "ana", "nota": "-ok"}}, lambda c: f"u/{c}")
    assert filas[0][:3] == ["Chat", "Enlace", "Fecha"]
    assert len(filas) == 2 and len(filas[1]) == 12
    assert filas[1][1] == "u/1" and filas[1][7] == "'=HYPERLINK(1)" and filas[1][11] == "'-ok"


def test_revision_en_memoria_parcial():
    chatwoot = _escenario(40)
    resultado = motor.revision_en_memoria(chatwoot, since=SINCE, until=UNTIL, bandejas=[BANDEJA], maximo=30)
    assert resultado["parcial"] is True
    assert len(resultado["chats"]) == 30
    assert resultado["vistos"] >= 30
    assert resultado["revision"]["estado"] == "completado"


def _abandonar(store, review_id, conversation_id, intentos):
    chat = next(c for c in store.listar_chats(review_id) if c["conversation_id"] == conversation_id)
    store.chats[chat["id"]].update(estado="procesando", intentos=intentos, updated_at="2000-01-01T00:00:00+00:00")


def test_abandonado_cuenta_intentos():
    chatwoot = _escenario(2)
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    while store.obtener_revision(revision["id"])["estado"] == "listando":
        motor.ejecutar_paso(store, revision["id"], chatwoot, {}, ahora=UNTIL, reloj=_reloj())
    _abandonar(store, revision["id"], 1, intentos=0)
    _abandonar(store, revision["id"], 2, intentos=motor.MAX_INTENTOS - 1)
    respuesta = _correr(store, revision["id"], chatwoot)
    chats = {c["conversation_id"]: c for c in store.listar_chats(revision["id"])}
    assert chats[1]["estado"] == "evaluado" and chats[1]["intentos"] == 1
    assert chats[2]["estado"] == "error" and chats[2]["intentos"] == motor.MAX_INTENTOS
    assert 2 not in chatwoot.lecturas
    assert respuesta["estado"] == "con_errores"


class ChatwootListadoFalla(ChatwootFalso):
    def __init__(self, *args, fallos=10**6, **kwargs):
        super().__init__(*args, **kwargs)
        self.fallos = fallos
        self.intentos_listado = 0

    def conversaciones_en_rango(self, since, until, page=1, inbox_ids=None):
        self.intentos_listado += 1
        if self.intentos_listado <= self.fallos:
            raise RuntimeError("422 filtro inválido")
        return super().conversaciones_en_rango(since, until, page, inbox_ids)


def test_listado_falla_siempre_termina():
    chatwoot = ChatwootListadoFalla([_conv(1, SINCE + 60)], {1: _normal(1, SINCE + 60)})
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    respuesta = _correr(store, revision["id"], chatwoot, maximo=20)
    assert respuesta["estado"] == "con_errores"
    assert chatwoot.intentos_listado == motor.MAX_INTENTOS
    assert "422" in store.obtener_revision(revision["id"])["contadores"]["error_listado"]


def test_listado_falla_una_vez_se_recupera():
    chatwoot = ChatwootListadoFalla([_conv(1, SINCE + 60)], {1: _normal(1, SINCE + 60)}, fallos=motor.MAX_INTENTOS - 1)
    store = MemoriaIncidenciasStore()
    revision = _nueva(store)
    respuesta = _correr(store, revision["id"], chatwoot)
    assert respuesta["estado"] == "completado" and respuesta["progreso"]["evaluados"] == 1
    assert store.obtener_revision(revision["id"])["contadores"]["fallos_listado"] == 0
