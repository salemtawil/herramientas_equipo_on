import pytest

from utils import multiadmin_llamadas as ml


class Respuesta:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data
        self.ok = 200 <= status < 300

    def json(self):
        return self._data


class SesionFalsa:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.llamadas.append({"url": url, "headers": headers, "params": params})
        return self.respuestas.pop(0)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    estado = {"renovado": 0}
    monkeypatch.setattr(ml, "_token", lambda forzar=False: "tok-nuevo" if forzar else "tok-viejo")
    return estado


def test_listar_llamadas_usa_fechas_en_ms_y_devuelve_items():
    sesion = SesionFalsa([Respuesta(200, {"items": [{"callId": "a"}, {"callId": "b"}], "count": 2})])
    items = ml.listar_llamadas(1000, 2000, sesion=sesion)
    assert [i["callId"] for i in items] == ["a", "b"]
    llamada = sesion.llamadas[0]
    assert llamada["url"] == "https://admin-api.compi.sh/projects/compinche/call-analysis"
    assert llamada["params"] == {"startDate": 1000, "endDate": 2000}
    assert llamada["headers"]["authorization"] == "Bearer tok-viejo"
    assert llamada["headers"]["origin"] == "https://admin.compi.sh"


def test_401_renueva_el_token_y_reintenta_una_vez():
    sesion = SesionFalsa([Respuesta(401), Respuesta(200, {"items": [], "count": 0})])
    assert ml.listar_llamadas(1, 2, sesion=sesion) == []
    assert sesion.llamadas[1]["headers"]["authorization"] == "Bearer tok-nuevo"


def test_error_del_servidor_lanza_sin_exponer_el_token():
    sesion = SesionFalsa([Respuesta(500)])
    with pytest.raises(ml.MultiadminLlamadasError) as error:
        ml.listar_llamadas(1, 2, sesion=sesion)
    assert "500" in str(error.value) and "tok-" not in str(error.value)


def test_detalle_llamada_pide_call_id_y_record_key():
    sesion = SesionFalsa([Respuesta(200, {"callId": "compinche1", "rubric": {"items": []}})])
    detalle = ml.detalle_llamada("compinche1", "Julio#compinche1#1", sesion=sesion)
    assert detalle["callId"] == "compinche1"
    assert sesion.llamadas[0]["params"] == {"callId": "compinche1", "recordKey": "Julio#compinche1#1"}


def test_base_url_configurable(monkeypatch):
    monkeypatch.setenv("MULTIADMIN_ADMIN_API_URL", "https://otra.test/")
    sesion = SesionFalsa([Respuesta(200, {"items": []})])
    ml.listar_llamadas(1, 2, sesion=sesion)
    assert sesion.llamadas[0]["url"] == "https://otra.test/projects/compinche/call-analysis"
