"""Conector mínimo para APIs de chat compatibles con OpenAI (Groq, OpenRouter, Ollama, Gemini, OpenAI)."""

import json
import os
import re

import requests

BASE_URL_DEFAULT = "https://api.groq.com/openai/v1"
MODEL_DEFAULT = "openai/gpt-oss-120b"
ESPERA_DEFAULT = 20


class IAConfigError(Exception):
    pass


class IARespuestaError(Exception):
    pass


class IARateLimitError(Exception):
    def __init__(self, mensaje, esperar_segundos=ESPERA_DEFAULT, diario=False):
        super().__init__(mensaje)
        self.esperar_segundos = esperar_segundos
        self.diario = diario


def _env(nombre):
    return str(os.getenv(nombre) or "").strip()


def obtener_config_ia():
    api_key = _env("AUDITORIA_CHATS_AI_API_KEY")
    return {
        "base_url": (_env("AUDITORIA_CHATS_AI_BASE_URL") or BASE_URL_DEFAULT).rstrip("/"),
        "model": _env("AUDITORIA_CHATS_AI_MODEL") or MODEL_DEFAULT,
        "api_key": api_key,
        "activa": bool(api_key),
    }


def _es_limite_diario(texto):
    texto = str(texto or "").lower()
    return "per day" in texto or "tpd" in texto or "rpd" in texto


def _segundos_espera(respuesta):
    try:
        return max(1, int(float(respuesta.headers.get("retry-after", ESPERA_DEFAULT))))
    except (TypeError, ValueError):
        return ESPERA_DEFAULT


def _parsear_contenido(contenido):
    texto = str(contenido or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.IGNORECASE).strip()
    try:
        data = json.loads(texto)
    except ValueError as exc:
        raise IARespuestaError("La IA no devolvió un JSON válido.") from exc
    if not isinstance(data, dict):
        raise IARespuestaError("La IA devolvió un JSON que no es un objeto.")
    return data


def completar_json(mensajes, config, timeout=40):
    if not config.get("api_key"):
        raise IAConfigError("Configura AUDITORIA_CHATS_AI_API_KEY para usar la auditoría con IA.")

    url = f"{config['base_url'].rstrip('/')}/chat/completions"
    payload = {
        "model": config["model"],
        "messages": mensajes,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}

    try:
        respuesta = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise IARespuestaError(f"No se pudo conectar con el proveedor de IA: {exc.__class__.__name__}.") from exc

    if respuesta.status_code in (401, 403):
        raise IAConfigError(
            "El proveedor de IA rechazó la clave. Revisa AUDITORIA_CHATS_AI_API_KEY y AUDITORIA_CHATS_AI_BASE_URL."
        )
    if respuesta.status_code == 429:
        diario = _es_limite_diario(respuesta.text)
        mensaje = (
            "Límite diario de la IA alcanzado; retoma mañana."
            if diario
            else "Límite por minuto de la IA alcanzado; se reintentará en unos segundos."
        )
        raise IARateLimitError(mensaje, esperar_segundos=_segundos_espera(respuesta), diario=diario)
    if respuesta.status_code >= 400:
        raise IARespuestaError(f"El proveedor de IA respondió {respuesta.status_code}: {respuesta.text[:200]}")

    try:
        data = respuesta.json()
        contenido = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise IARespuestaError("La respuesta del proveedor de IA no tiene el formato esperado.") from exc

    return _parsear_contenido(contenido)
