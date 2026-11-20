import json

import pytest

from utils import ia_chat
from utils.ia_chat import (
    IAConfigError,
    IARateLimitError,
    IARespuestaError,
    completar_json,
    obtener_config_ia,
)


class RespuestaFalsa:
    def __init__(self, status_code=200, data=None, text=None, headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text if text is not None else json.dumps(data or {})
        self.headers = headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def _config(**cambios):
    config = {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "api_key": "clave-prueba",
        "activa": True,
    }
    config.update(cambios)
    return config


def _respuesta_contenido(contenido):
    return RespuestaFalsa(data={"choices": [{"message": {"content": contenido}}]})


def test_config_por_defecto_groq(monkeypatch):
    for nombre in ("AUDITORIA_CHATS_AI_BASE_URL", "AUDITORIA_CHATS_AI_MODEL", "AUDITORIA_CHATS_AI_API_KEY"):
        monkeypatch.delenv(nombre, raising=False)
    config = obtener_config_ia()
    assert config["base_url"] == "https://api.groq.com/openai/v1"
    assert config["model"] == "openai/gpt-oss-120b"
    assert config["activa"] is False


def test_config_lee_variables(monkeypatch):
    monkeypatch.setenv("AUDITORIA_CHATS_AI_BASE_URL", "http://127.0.0.1:11434/v1/")
    monkeypatch.setenv("AUDITORIA_CHATS_AI_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "abc")
    config = obtener_config_ia()
    assert config["base_url"] == "http://127.0.0.1:11434/v1"
    assert config["model"] == "qwen2.5:7b"
    assert config["activa"] is True


def test_completar_json_envia_payload_y_parsea(monkeypatch):
    llamadas = {}

    def post_falso(url, headers=None, json=None, timeout=None):
        llamadas.update(url=url, headers=headers, json=json, timeout=timeout)
        return _respuesta_contenido('```json\n{"a": 1}\n```')

    monkeypatch.setattr(ia_chat.requests, "post", post_falso)
    resultado = completar_json([{"role": "user", "content": "hola"}], _config())

    assert resultado == {"a": 1}
    assert llamadas["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert llamadas["headers"]["Authorization"] == "Bearer clave-prueba"
    assert llamadas["json"]["response_format"] == {"type": "json_object"}
    assert llamadas["json"]["model"] == "openai/gpt-oss-120b"
    assert llamadas["json"]["messages"] == [{"role": "user", "content": "hola"}]


def test_sin_clave_lanza_config_error():
    with pytest.raises(IAConfigError):
        completar_json([], _config(api_key="", activa=False))


def test_401_lanza_config_error_legible(monkeypatch):
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(401, text="invalid api key"))
    with pytest.raises(IAConfigError) as error:
        completar_json([], _config())
    assert "AUDITORIA_CHATS_AI_API_KEY" in str(error.value)


def test_429_por_minuto(monkeypatch):
    respuesta = RespuestaFalsa(
        429,
        text='{"error":{"message":"Rate limit reached on tokens per minute (TPM)"}}',
        headers={"retry-after": "7"},
    )
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: respuesta)
    with pytest.raises(IARateLimitError) as error:
        completar_json([], _config())
    assert error.value.esperar_segundos == 7
    assert error.value.diario is False


def test_429_por_dia(monkeypatch):
    respuesta = RespuestaFalsa(
        429,
        text='{"error":{"message":"Rate limit reached on tokens per day (TPD): Limit 200000"}}',
        headers={"retry-after": "3600"},
    )
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: respuesta)
    with pytest.raises(IARateLimitError) as error:
        completar_json([], _config())
    assert error.value.diario is True


def test_contenido_no_json_lanza_respuesta_error(monkeypatch):
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: _respuesta_contenido("no es json"))
    with pytest.raises(IARespuestaError):
        completar_json([], _config())


def test_429_por_dia_gemini(monkeypatch):
    texto = (
        '[{"error": {"code": 429, "message": "You exceeded your current quota.", "status": "RESOURCE_EXHAUSTED", '
        '"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}]'
    )
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(429, text=texto))
    with pytest.raises(IARateLimitError) as error:
        completar_json([], _config())
    assert error.value.diario is True


def test_429_por_minuto_gemini(monkeypatch):
    texto = '[{"error": {"code": 429, "details": [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]}}]'
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(429, text=texto))
    with pytest.raises(IARateLimitError) as error:
        completar_json([], _config())
    assert error.value.diario is False


def test_404_modelo_inexistente_es_error_de_configuracion(monkeypatch):
    texto = '[{"error": {"code": 404, "message": "This model models/gemini-2.5-flash is no longer available to new users."}}]'
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(404, text=texto))
    with pytest.raises(IAConfigError) as error:
        completar_json([], _config(model="gemini-2.5-flash"))
    assert "AUDITORIA_CHATS_AI_MODEL" in str(error.value)
    assert "gemini-2.5-flash" in str(error.value)


def test_503_alta_demanda_es_temporal(monkeypatch):
    from utils.ia_chat import IATemporalError

    texto = '[{"error": {"code": 503, "message": "This model is currently experiencing high demand.", "status": "UNAVAILABLE"}}]'
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(503, text=texto))
    with pytest.raises(IATemporalError) as error:
        completar_json([], _config())
    assert error.value.diario is False
    assert error.value.esperar_segundos >= 20


def test_timeout_es_temporal(monkeypatch):
    from utils.ia_chat import IATemporalError

    def post_lento(*a, **k):
        raise ia_chat.requests.exceptions.ReadTimeout("lento")

    monkeypatch.setattr(ia_chat.requests, "post", post_lento)
    with pytest.raises(IATemporalError):
        completar_json([], _config())


def test_config_respaldo_y_razonamiento(monkeypatch):
    monkeypatch.setenv("AUDITORIA_CHATS_AI_API_KEY", "abc")
    monkeypatch.setenv("AUDITORIA_CHATS_AI_MODEL_RESPALDO", " gemini-lite ")
    monkeypatch.setenv("AUDITORIA_CHATS_AI_RAZONAMIENTO", "low")
    config = obtener_config_ia()
    assert config["model_respaldo"] == "gemini-lite"
    assert config["razonamiento"] == "low"


def test_config_sin_respaldo_ni_razonamiento(monkeypatch):
    monkeypatch.delenv("AUDITORIA_CHATS_AI_MODEL_RESPALDO", raising=False)
    monkeypatch.delenv("AUDITORIA_CHATS_AI_RAZONAMIENTO", raising=False)
    config = obtener_config_ia()
    assert config["model_respaldo"] == ""
    assert config["razonamiento"] == ""


def test_razonamiento_y_timeout_en_la_peticion(monkeypatch):
    llamadas = {}

    def post_falso(url, headers=None, json=None, timeout=None):
        llamadas.update(json=json, timeout=timeout)
        return _respuesta_contenido('{"a": 1}')

    monkeypatch.setattr(ia_chat.requests, "post", post_falso)
    completar_json([], _config(razonamiento="low"))
    assert llamadas["json"]["reasoning_effort"] == "low"
    assert llamadas["timeout"] == 60

    completar_json([], _config(razonamiento=""))
    assert "reasoning_effort" not in llamadas["json"]


@pytest.mark.parametrize(
    "valor, esperado",
    [
        ('"gemini-3.8-flash"', "gemini-3.8-flash"),
        ("'gemini-3.8-flash'\n", "gemini-3.8-flash"),
        ("models/gemini-3.8-flash", "gemini-3.8-flash"),
        ("  gemini-3.8-flash  ", "gemini-3.8-flash"),
    ],
)
def test_nombre_de_modelo_se_limpia(monkeypatch, valor, esperado):
    monkeypatch.setenv("AUDITORIA_CHATS_AI_MODEL", valor)
    monkeypatch.setenv("AUDITORIA_CHATS_AI_MODEL_RESPALDO", valor)
    config = obtener_config_ia()
    assert config["model"] == esperado
    assert config["model_respaldo"] == esperado


def test_400_por_nombre_de_modelo_es_error_de_configuracion(monkeypatch):
    texto = '[{"error": {"code": 400, "message": "* GenerateContentRequest.model: unexpected model name format\n", "status": "INVALID_ARGUMENT"}}]'
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(400, text=texto))
    with pytest.raises(IAConfigError) as error:
        completar_json([], _config(model="Gemini 3.8 Flash"))
    mensaje = str(error.value)
    assert "Gemini 3.8 Flash" in mensaje and "AUDITORIA_CHATS_AI_MODEL" in mensaje


def test_400_por_razonamiento_es_error_de_configuracion(monkeypatch):
    texto = '[{"error": {"code": 400, "message": "Invalid value for reasoning_effort", "status": "INVALID_ARGUMENT"}}]'
    monkeypatch.setattr(ia_chat.requests, "post", lambda *a, **k: RespuestaFalsa(400, text=texto))
    with pytest.raises(IAConfigError) as error:
        completar_json([], _config(razonamiento="low"))
    assert "AUDITORIA_CHATS_AI_RAZONAMIENTO" in str(error.value)
