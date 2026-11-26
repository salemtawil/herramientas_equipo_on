from datetime import datetime

import pytest

from tests.test_incidencias_chats_motor import BANDEJA, SINCE, UNTIL, _escenario, _reloj
from utils import incidencias_chats_ia as ia
from utils import incidencias_chats_motor as motor
from utils.chatwoot_reportes import _obtener_timezone
from utils.ia_chat import IAConfigError, IARateLimitError, IARespuestaError, IATemporalError
from utils.incidencias_chats_store import MemoriaIncidenciasStore

CONFIG = {"activa": True, "api_key": "x"}
OK = {
    "incidencias": [{"indice": 1, "confirmada": True, "motivo": "dijo «Lo reviso ya mismo»"}],
    "resumen": "Cobro duplicado sin solución.",
    "incidencias_extra": [],
}


class IAFalsa:
    def __init__(self, respuestas=None):
        self.respuestas = list(respuestas or [OK])
        self.llamadas = []

    def __call__(self, mensajes, config, timeout=60):
        self.llamadas.append(mensajes)
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CHATWOOT_TIMEZONE", "America/Caracas")
    monkeypatch.delenv("INCIDENCIAS_CHATS_AI_CUPO_DIARIO", raising=False)


def _revision(store, usar_ia=True):
    return motor.crear_revision(store, since=SINCE, until=UNTIL, bandejas=[BANDEJA], usar_ia=usar_ia, creado_por="ana")


def _paso(store, rid, chatwoot, config=CONFIG):
    return motor.ejecutar_paso(store, rid, chatwoot, config, ahora=UNTIL, reloj=_reloj())


def _correr(store, rid, chatwoot, config=CONFIG, maximo=300):
    for _ in range(maximo):
        r = _paso(store, rid, chatwoot, config)
        if r["accion"] == "fin":
            return r
    raise AssertionError(f"No terminó: {r}")


def _hoy():
    return datetime.fromtimestamp(UNTIL, _obtener_timezone("America/Caracas")).date()


def _por_conv(store, rid):
    return {c["conversation_id"]: c for c in store.listar_chats(rid)}


def test_cupo_por_defecto_y_invalido(monkeypatch):
    assert ia.cupo_ia() == 10
    monkeypatch.setenv("INCIDENCIAS_CHATS_AI_CUPO_DIARIO", "abc")
    assert ia.cupo_ia() == 10
    monkeypatch.setenv("INCIDENCIAS_CHATS_AI_CUPO_DIARIO", "3")
    assert ia.cupo_ia() == 3


def test_ia_confirma_y_borra_transcripcion(monkeypatch):
    falsa = IAFalsa()
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    _correr(store, rid, _escenario(5, cobro={2}))
    chat = _por_conv(store, rid)[2]
    assert chat["ia_estado"] == "hecha" and chat["transcripcion_tmp"] is None
    assert chat["ia_resultado"]["resumen"] == "Cobro duplicado sin solución."
    assert store.usos_ia(_hoy()) == 1 and len(falsa.llamadas) == 1
    assert "me cobraron dos veces" in falsa.llamadas[0][1]["content"]
    assert all(c["transcripcion_tmp"] is None for c in store.listar_chats(rid))


def test_transcripcion_guardada_mientras_pendiente(monkeypatch):
    # Sin config activa la IA no corre, pero antes de ella el chat marcado queda «pendiente» con transcripción.
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    chatwoot = _escenario(3, cobro={2})
    original = ia.paso_ia
    visto = {}

    def espia(store_, revision, config, hoy):
        if not visto:
            visto.update({c["conversation_id"]: dict(c) for c in store_.listar_chats(revision["id"])})
        return original(store_, revision, config, hoy)

    monkeypatch.setattr(motor, "paso_ia", espia)
    monkeypatch.setattr(ia, "completar_json", IAFalsa())
    _correr(store, rid, chatwoot)
    assert visto[2]["ia_estado"] == "pendiente" and visto[2]["transcripcion_tmp"]
    assert visto[1]["ia_estado"] is None and visto[1]["transcripcion_tmp"] is None


def test_ia_respeta_cupo(monkeypatch):
    monkeypatch.setenv("INCIDENCIAS_CHATS_AI_CUPO_DIARIO", "1")
    falsa = IAFalsa()
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    _correr(store, rid, _escenario(5, cobro={2, 4}))
    estados = sorted(c["ia_estado"] for c in store.listar_chats(rid) if c["ia_estado"])
    assert estados == ["hecha", "sin_cupo"] and len(falsa.llamadas) == 1
    assert all(c["transcripcion_tmp"] is None for c in store.listar_chats(rid))


def test_ia_inactiva_va_a_sin_cupo(monkeypatch):
    falsa = IAFalsa()
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    _correr(store, rid, _escenario(4, cobro={2}), config={"activa": False})
    chat = _por_conv(store, rid)[2]
    assert chat["ia_estado"] == "sin_cupo" and chat["transcripcion_tmp"] is None and not falsa.llamadas


def test_ia_alta_primero(monkeypatch):
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    base = {"review_id": rid, "estado": "evaluado", "ia_estado": "pendiente", "transcripcion_tmp": "t"}
    store.insertar_chats([
        dict(base, conversation_id=1, incidencias=[{"severidad": "media", "etiqueta": "m", "evidencia": "e"}]),
        dict(base, conversation_id=2, incidencias=[{"severidad": "alta", "etiqueta": "a", "evidencia": "e"}]),
    ])
    monkeypatch.setattr(ia, "completar_json", IAFalsa())
    ia.paso_ia(store, store.obtener_revision(rid), CONFIG, _hoy())
    c = _por_conv(store, rid)
    assert c[2]["ia_estado"] == "hecha" and c[1]["ia_estado"] == "pendiente"


def test_ia_limite_diario_termina(monkeypatch):
    monkeypatch.setattr(ia, "completar_json", IAFalsa([IARateLimitError("diario", diario=True)]))
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    r = _correr(store, rid, _escenario(6, cobro={2, 4}))
    assert r["estado"] == "completado"
    ch = _por_conv(store, rid)
    assert ch[2]["ia_estado"] == ch[4]["ia_estado"] == "sin_cupo"
    assert all(c["transcripcion_tmp"] is None for c in ch.values())
    assert store.usos_ia(_hoy()) == 0


def test_ia_limite_temporal_espera_y_reintenta(monkeypatch):
    monkeypatch.setattr(ia, "completar_json", IAFalsa([IATemporalError("saturado"), OK]))
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    chatwoot = _escenario(3, cobro={2})
    respuestas = []
    for _ in range(50):
        respuestas.append(_paso(store, rid, chatwoot))
        if respuestas[-1]["accion"] == "fin":
            break
    espera = [r for r in respuestas if r["accion"] == "espera"]
    assert espera and espera[0]["esperar_segundos"] == 30
    assert _por_conv(store, rid)[2]["ia_estado"] == "hecha"


@pytest.mark.parametrize("error", [IARespuestaError("mal json"), IAConfigError("clave"), RuntimeError("boom")])
def test_ia_error_de_respuesta_no_bloquea(monkeypatch, error):
    monkeypatch.setattr(ia, "completar_json", IAFalsa([error]))
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    r = _correr(store, rid, _escenario(6, cobro={2, 4}))
    assert r["estado"] == "completado"
    ch = _por_conv(store, rid)
    assert ch[2]["ia_estado"] == ch[4]["ia_estado"] == "error"
    assert all(c["transcripcion_tmp"] is None for c in ch.values())


def test_sin_usar_ia_no_llama(monkeypatch):
    falsa = IAFalsa()
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store, usar_ia=False)["id"]
    _correr(store, rid, _escenario(5, cobro={2}))
    assert not falsa.llamadas
    assert all(c["transcripcion_tmp"] is None and c["ia_estado"] is None for c in store.listar_chats(rid))


def test_incidencia_extra_de_ia(monkeypatch):
    respuesta = dict(OK, incidencias_extra=[
        {"tipo": "cliente", "etiqueta": "Amenaza de baja", "evidencia": "escríbeme a ana@correo.com " + "x" * 400},
        {"tipo": "raro", "etiqueta": "", "evidencia": "sin etiqueta"},
    ])
    monkeypatch.setattr(ia, "completar_json", IAFalsa([respuesta]))
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    _correr(store, rid, _escenario(4, cobro={2}))
    chat = _por_conv(store, rid)[2]
    extras = [i for i in chat["incidencias"] if i.get("origen") == "ia"]
    assert len(extras) == 1
    assert extras[0]["tipo"] == "cliente" and extras[0]["severidad"] == "media"
    assert len(extras[0]["evidencia"]) <= 200 and "ana@correo.com" not in extras[0]["evidencia"]
    assert any(i.get("origen") == "reglas" for i in chat["incidencias"])


def test_formato_invalido_es_error(monkeypatch):
    monkeypatch.setattr(ia, "completar_json", IAFalsa([{"otra": 1}]))
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    _correr(store, rid, _escenario(4, cobro={2}))
    assert _por_conv(store, rid)[2]["ia_estado"] == "error"


def test_claim_abandonado_se_recupera_una_vez_y_luego_error(monkeypatch):
    monkeypatch.setattr(ia, "SEGUNDOS_IA_ABANDONADA", -1)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    store.insertar_chats([{
        "review_id": rid, "conversation_id": 1, "estado": "evaluado", "ia_estado": "procesando",
        "transcripcion_tmp": "t", "incidencias": [{"severidad": "alta", "etiqueta": "a", "evidencia": "e"}],
    }])
    ia._recuperar_abandonados_ia(store, store.listar_chats(rid))
    chat = store.listar_chats(rid)[0]
    assert chat["ia_estado"] == "pendiente"
    store.actualizar_chat(chat["id"], {"ia_estado": "procesando"})
    ia._recuperar_abandonados_ia(store, store.listar_chats(rid))
    chat = store.listar_chats(rid)[0]
    assert chat["ia_estado"] == "error" and chat["transcripcion_tmp"] is None


def test_claim_reciente_de_otra_pestana_espera(monkeypatch):
    falsa = IAFalsa()
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    store.insertar_chats([{
        "review_id": rid, "conversation_id": 1, "estado": "evaluado", "ia_estado": "procesando",
        "transcripcion_tmp": "t", "incidencias": [],
    }])
    r = ia.paso_ia(store, store.obtener_revision(rid), CONFIG, _hoy())
    assert r["accion"] == "espera" and not falsa.llamadas


def test_ia_temporal_persistente_termina_en_error(monkeypatch):
    falsa = IAFalsa([IATemporalError("saturado")])
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    r = _correr(store, rid, _escenario(3, cobro={2}))
    chat = _por_conv(store, rid)[2]
    assert r["estado"] == "completado" and chat["ia_estado"] == "error" and chat["transcripcion_tmp"] is None
    assert len(falsa.llamadas) == 3


def test_pendiente_sin_transcripcion_no_llama(monkeypatch):
    falsa = IAFalsa()
    monkeypatch.setattr(ia, "completar_json", falsa)
    store = MemoriaIncidenciasStore()
    rid = _revision(store)["id"]
    store.insertar_chats([{"review_id": rid, "conversation_id": 1, "estado": "evaluado", "ia_estado": "pendiente",
                           "transcripcion_tmp": None, "incidencias": [{"severidad": "alta"}]}])
    ia.paso_ia(store, store.obtener_revision(rid), CONFIG, _hoy())
    assert not falsa.llamadas and store.usos_ia(_hoy()) == 0
    assert store.listar_chats(rid)[0]["ia_estado"] is None


def test_reutilizar_no_hereda_ia_en_curso():
    store = MemoriaIncidenciasStore()
    previa = _revision(store)["id"]
    store.insertar_chats([{"review_id": previa, "conversation_id": 5, "estado": "evaluado", "resuelto": True,
                           "reglas_version": motor.REGLAS_VERSION, "last_activity_at": 100, "incidencias": [],
                           "ia_estado": "pendiente", "ia_resultado": {"x": 1}}])
    nueva = _revision(store)["id"]
    fila = motor._reutilizar(store, {"review_id": nueva, "conversation_id": 5, "status": "resolved",
                                     "last_activity_at": 100, "agente_nombre": ""})
    assert fila["estado"] == "evaluado" and fila["ia_estado"] is None and fila["ia_resultado"] is None


def test_veredicto_ia_en_filas_y_csv():
    chat = {"id": "a", "conversation_id": 1, "ia_estado": "hecha", "ia_resultado": {
        "incidencias": [{"indice": 1, "confirmada": True, "motivo": "lo dijo"}, {"indice": 2, "confirmada": False, "motivo": "no es"}],
        "resumen": "res"}, "incidencias": [
        {"tipo": "atencion", "etiqueta": "A", "severidad": "alta", "evidencia": "e"},
        {"tipo": "atencion", "etiqueta": "B", "severidad": "media", "evidencia": "e"},
        {"tipo": "cliente", "etiqueta": "C", "severidad": "media", "evidencia": "e", "origen": "ia"}]}
    filas = list(motor._filas_incidencias([chat], {}))
    assert [(f["ia_confirmada"], f["ia_motivo"]) for f in filas] == [(True, "lo dijo"), (False, "no es"), (True, "res")]
    csv = motor.filas_csv({}, [chat], {}, None)
    assert sorted(f[8] for f in csv[1:]) == ["Confirmada: lo dijo", "Confirmada: res", "Descartada: no es"]
    sin = dict(chat, ia_estado="sin_cupo", ia_resultado=None, incidencias=chat["incidencias"][:1])
    f = list(motor._filas_incidencias([sin], {}))[0]
    assert f["ia_confirmada"] is None and f["ia_motivo"] == ""
