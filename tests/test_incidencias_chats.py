import csv
import io
from datetime import datetime

import pytest

from app import app
from tools import incidencias_chats as herramienta
from utils.chatwoot_reportes import _obtener_timezone, _timezone
from utils.incidencias_chats_store import MemoriaIncidenciasStore

TZ = _obtener_timezone(_timezone())
SINCE = int(datetime(2026, 11, 20, 8, 0, tzinfo=TZ).timestamp())
BANDEJA = 3
COBRO = "<script>x</script> me cobraron dos veces"


def _m(id, tipo, texto, t):
    mensaje = {"id": id, "message_type": tipo, "content": texto, "created_at": t, "private": False}
    if tipo == 1:
        mensaje["sender_type"] = "user"
        mensaje["sender"] = {"id": 7, "name": "Luis Gómez"}
    return mensaje


class ChatwootFalso:
    base_url = "https://chat.test"

    def __init__(self, n=3, cobro=(2,), sin_respuesta=(3,), falla_listado=False):
        self.conversaciones, self.mensajes = [], {}
        self.falla_listado = falla_listado
        for i in range(1, n + 1):
            t = SINCE + i * 60
            self.conversaciones.append(
                {
                    "id": i,
                    "created_at": t,
                    "inbox_id": BANDEJA,
                    "status": "resolved",
                    "last_activity_at": t + 60,
                    "meta": {"assignee": {"id": 7, "name": "Luis Gómez"}},
                }
            )
            texto = COBRO if i in cobro else "Hola, una consulta"
            self.mensajes[i] = [_m(i * 10 + 1, 0, texto, t), _m(i * 10 + 2, 1, "Hola, te ayudo", t + 30)]
            if i in sin_respuesta:
                # Mala atención: el chat se cerró sin respuesta de un agente.
                self.mensajes[i] = [_m(i * 10 + 1, 0, "Hola, ¿hay alguien?", t)]

    def listar_bandejas(self):
        return [{"id": BANDEJA, "name": "WhatsApp", "channel_type": "Channel::Whatsapp"}]

    def conversaciones_en_rango(self, since, until, page=1, inbox_ids=None):
        if self.falla_listado:
            raise RuntimeError("Chatwoot caído")
        return list(self.conversaciones[(page - 1) * 25 : page * 25])

    def mensajes_de_conversacion(self, conversation_id, max_paginas=5):
        return list(self.mensajes[int(conversation_id)])

    def respuestas_csat(self, since, until, max_paginas=40):
        return []

    def url_conversacion(self, conversation_id):
        return f"https://chat.test/app/accounts/2/conversations/{int(conversation_id)}"


@pytest.fixture
def entorno(monkeypatch):
    store = MemoriaIncidenciasStore()
    monkeypatch.setattr(herramienta, "obtener_store", lambda: store)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    monkeypatch.setattr(herramienta, "obtener_config_ia", lambda: {"activa": False, "api_key": "", "model": ""})
    return store


@pytest.fixture
def cliente():
    return app.test_client()


def _datos(**extra):
    datos = {
        "desde_fecha": "2026-11-20",
        "desde_hora": "08:00",
        "hasta_fecha": "2026-11-20",
        "hasta_hora": "12:00",
        "bandejas": str(BANDEJA),
        "creado_por": "Marta",
    }
    datos.update(extra)
    return datos


def _crear_y_terminar(cliente, store):
    respuesta = cliente.post("/incidencias-chats/revisiones", data=_datos())
    assert respuesta.status_code == 302
    review_id = store.listar_revisiones()[0]["id"]
    assert respuesta.headers["Location"].endswith(f"/incidencias-chats/revision/{review_id}")
    for _ in range(50):
        datos = cliente.post(
            f"/incidencias-chats/revision/{review_id}/paso", headers={"Accept": "application/json"}
        ).get_json()
        if datos["accion"] == "fin":
            break
    else:
        pytest.fail("La revisión no terminó")
    return review_id


def test_index_carga_y_aparece_en_navegacion(entorno, cliente):
    respuesta = cliente.get("/incidencias-chats/")
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    assert "Incidencias de chats" in html
    assert 'href="/incidencias-chats/"' in html
    for campo in ("desde_fecha", "desde_hora", "hasta_fecha", "hasta_hora", "bandejas", "usar_ia", "prueba", "creado_por"):
        assert f'name="{campo}"' in html
    assert 'data-desde="08:00"' in html and 'data-hasta="16:30"' in html


def test_index_sin_supabase_permite_modo_prueba(cliente, monkeypatch):
    def sin_store():
        raise herramienta.IncidenciasConfigError("Configura SUPABASE_URL")

    monkeypatch.setattr(herramienta, "obtener_store", sin_store)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    html = cliente.get("/incidencias-chats/").get_data(as_text=True)
    assert "SUPABASE_URL" in html
    assert 'name="prueba"' in html


def test_crear_rango_invalido_avisa(entorno, cliente):
    respuesta = cliente.post(
        "/incidencias-chats/revisiones", data=_datos(hasta_hora="07:00"), follow_redirects=False
    )
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/incidencias-chats/")
    assert entorno.listar_revisiones() == []
    html = cliente.get("/incidencias-chats/").get_data(as_text=True)
    assert "posterior" in html


def test_crear_y_avanzar_hasta_fin(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    html = cliente.get(f"/incidencias-chats/revision/{review_id}").get_data(as_text=True)
    assert "Reportes de clientes" in html and "Mala atención" in html
    assert html.count('class="table-wrap"') >= 2
    assert "#2" in html and "#3" in html
    assert "data-ic-paso-url" not in html


def test_evidencia_escapada(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    html = cliente.get(f"/incidencias-chats/revision/{review_id}").get_data(as_text=True)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<mark>me cobraron dos veces</mark>" in html


def test_decision_guarda_por_conversacion_y_cookie(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    respuesta = cliente.post(
        "/incidencias-chats/conversacion/2/decision",
        data={"decision": "atendida", "por": "Marta", "nota": "Ya se devolvió", "review_id": review_id},
        headers={"Accept": "application/json"},
    )
    assert respuesta.status_code == 200
    assert respuesta.get_json()["ok"] is True
    assert "ic_por=" in respuesta.headers.get("Set-Cookie", "")
    guardada = entorno.decisiones([2])[2]
    assert guardada["decision"] == "atendida" and guardada["por"] == "Marta"
    assert guardada["review_id"] == review_id and guardada["nota"] == "Ya se devolvió"
    html = cliente.get(f"/incidencias-chats/revision/{review_id}").get_data(as_text=True)
    assert "Atendida" in html


def test_decision_sin_nombre_rechazada(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    respuesta = cliente.post(
        "/incidencias-chats/conversacion/2/decision",
        data={"decision": "atendida", "por": "  ", "review_id": review_id},
        headers={"Accept": "application/json"},
    )
    assert respuesta.status_code == 400
    assert respuesta.get_json()["ok"] is False
    assert entorno.decisiones([2]) == {}


def test_decision_invalida_o_ajena_rechazada(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    malo = cliente.post(
        "/incidencias-chats/conversacion/2/decision",
        data={"decision": "borrar", "por": "Marta", "review_id": review_id},
        headers={"Accept": "application/json"},
    )
    assert malo.status_code == 400
    ajena = cliente.post(
        "/incidencias-chats/conversacion/999/decision",
        data={"decision": "atendida", "por": "Marta", "review_id": review_id},
        headers={"Accept": "application/json"},
    )
    assert ajena.status_code == 404
    assert entorno.decisiones([2, 999]) == {}


def test_modo_prueba_no_usa_store(cliente, monkeypatch):
    def explota():
        raise RuntimeError("no se debe usar el store")

    monkeypatch.setattr(herramienta, "obtener_store", explota)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    respuesta = cliente.post("/incidencias-chats/revisiones", data=_datos(prueba="1"))
    html = respuesta.get_data(as_text=True)
    assert respuesta.status_code == 200
    assert "Modo prueba: no se guarda" in html
    assert "<mark>me cobraron dos veces</mark>" in html
    assert "Resultado parcial" not in html


def test_modo_prueba_parcial_muestra_vistos(cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_store", lambda: MemoriaIncidenciasStore())
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso(n=40))
    html = cliente.post("/incidencias-chats/revisiones", data=_datos(prueba="1")).get_data(as_text=True)
    # Con 20 de máximo basta la primera página (25 chats vistos).
    assert f"Resultado parcial: {herramienta.MAX_CHATS_PRUEBA} de al menos 25 chats" in html


def test_modo_prueba_rango_maximo_12_horas(entorno, cliente):
    respuesta = cliente.post("/incidencias-chats/revisiones", data=_datos(prueba="1", hasta_hora="21:00"))
    assert respuesta.status_code == 302
    html = cliente.get("/incidencias-chats/").get_data(as_text=True)
    assert "12 horas" in html


def test_modo_prueba_error_de_chatwoot_avisa(cliente, monkeypatch):
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso(falla_listado=True))
    respuesta = cliente.post("/incidencias-chats/revisiones", data=_datos(prueba="1"))
    assert respuesta.status_code == 302
    html = cliente.get("/incidencias-chats/").get_data(as_text=True)
    assert "No se pudieron listar los chats" in html


def test_csv(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    respuesta = cliente.get(f"/incidencias-chats/revision/{review_id}/csv")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "text/csv"
    assert 'filename="incidencias_2026-11-20_0800_2026-11-20_1200.csv"' in respuesta.headers["Content-Disposition"]
    cuerpo = respuesta.get_data()
    assert cuerpo.startswith(b"\xef\xbb\xbf")
    filas = list(csv.reader(io.StringIO(cuerpo.decode("utf-8-sig"))))
    assert "Evidencia" in filas[0]
    incidencias = sum(len(c.get("incidencias") or []) for c in entorno.listar_chats(review_id))
    assert incidencias >= 1
    assert len(filas) - 1 == incidencias


def test_revision_inexistente_404(entorno, cliente):
    assert cliente.get("/incidencias-chats/revision/no-existe").status_code == 404


def test_paso_sin_terminar_muestra_url_de_paso(entorno, cliente):
    cliente.post("/incidencias-chats/revisiones", data=_datos())
    review_id = entorno.listar_revisiones()[0]["id"]
    html = cliente.get(f"/incidencias-chats/revision/{review_id}").get_data(as_text=True)
    assert f'data-ic-paso-url="/incidencias-chats/revision/{review_id}/paso"' in html


class StoreQueFalla(MemoriaIncidenciasStore):
    """La revisión existe, pero leer sus chats falla (p. ej. Supabase caído)."""

    def listar_chats(self, review_id):
        raise herramienta.IncidenciasError("Supabase no responde")


def _revision_con_store_roto(monkeypatch):
    store = StoreQueFalla()
    revision = store.crear_revision({"since": SINCE, "until": SINCE + 3600, "bandejas": [], "estado": "evaluando"})
    monkeypatch.setattr(herramienta, "obtener_store", lambda: store)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    return revision["id"]


@pytest.mark.parametrize(
    "metodo, ruta",
    [("get", ""), ("post", "/reintentar-errores"), ("get", "/csv")],
)
def test_error_del_store_avisa_en_espanol(cliente, monkeypatch, metodo, ruta):
    review_id = _revision_con_store_roto(monkeypatch)
    respuesta = getattr(cliente, metodo)(f"/incidencias-chats/revision/{review_id}{ruta}")
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/incidencias-chats/")


def test_paso_revision_inexistente_json_detiene(entorno, cliente):
    respuesta = cliente.post("/incidencias-chats/revision/no-existe/paso", headers={"Accept": "application/json"})
    assert respuesta.status_code == 404
    datos = respuesta.get_json()
    assert datos["accion"] == "configuracion" and datos["mensaje"]


def test_decision_muestra_no_es_incidencia(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    html = cliente.get(f"/incidencias-chats/revision/{review_id}").get_data(as_text=True)
    assert "No es incidencia" in html and "Falso positivo" not in html
    respuesta = cliente.post(
        "/incidencias-chats/conversacion/2/decision",
        data={"decision": "falso_positivo", "por": "Marta", "review_id": review_id},
        headers={"Accept": "application/json"},
    )
    assert "No es incidencia" in respuesta.get_json()["mensaje"]
    assert entorno.decisiones([2])[2]["decision"] == "falso_positivo"


def test_cookie_por_es_segura_en_https(entorno, cliente):
    review_id = _crear_y_terminar(cliente, entorno)
    respuesta = cliente.post(
        "/incidencias-chats/conversacion/2/decision",
        data={"decision": "atendida", "por": "Marta", "review_id": review_id},
        base_url="https://localhost",
    )
    assert "Secure" in respuesta.headers["Set-Cookie"]


def test_modo_prueba_cortado_por_tiempo_avisa(cliente, monkeypatch):
    original = herramienta.motor.revision_en_memoria

    def con_limite_cero(chatwoot, **kwargs):
        return original(chatwoot, limite_segundos=0, **kwargs)

    monkeypatch.setattr(herramienta.motor, "revision_en_memoria", con_limite_cero)
    monkeypatch.setattr(herramienta, "obtener_chatwoot", lambda: ChatwootFalso())
    html = cliente.post("/incidencias-chats/revisiones", data=_datos(prueba="1")).get_data(as_text=True)
    assert "antes del límite de tiempo; acorta el rango" in html


def test_aviso_de_tope_del_listado_en_la_revision(entorno, cliente):
    cliente.post("/incidencias-chats/revisiones", data=_datos())
    review_id = entorno.listar_revisiones()[0]["id"]
    entorno.actualizar_revision(review_id, {"contadores": {"aviso_listado": "Se alcanzó el máximo de páginas"}})
    html = cliente.get(f"/incidencias-chats/revision/{review_id}").get_data(as_text=True)
    assert "Se alcanzó el máximo de páginas" in html
