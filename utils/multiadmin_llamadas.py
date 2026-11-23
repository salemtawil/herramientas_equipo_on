"""Cliente de solo lectura del Análisis de llamadas de Multiadmin (admin.compi.sh).

La lista por rango de fechas trae solo el resumen de cada llamada; la rúbrica, el coaching y los
puntos clave vienen en el detalle de cada llamada. Nunca se escribe nada en Multiadmin.
"""

import os

import requests

from tools import api_multiadmin

BASE_URL_DEFAULT = "https://admin-api.compi.sh"
RUTA_LLAMADAS = "/projects/compinche/call-analysis"
TIMEOUT = 60


TIMEOUT_DETALLE = 15


class MultiadminLlamadasError(Exception):
    def __init__(self, mensaje, status=None):
        super().__init__(mensaje)
        self.status = status


def _base_url():
    return (os.getenv("MULTIADMIN_ADMIN_API_URL") or BASE_URL_DEFAULT).strip().rstrip("/")


def _token(forzar=False):
    if forzar:
        return api_multiadmin._renovar_token_multiadmin()
    return api_multiadmin._obtener_token_multiadmin()


def _headers(token):
    headers = api_multiadmin._headers_multiadmin(token)
    headers.update(origin="https://admin.compi.sh", referer="https://admin.compi.sh/")
    return headers


def _get(params, sesion=None, timeout=TIMEOUT):
    sesion = sesion or requests
    url = _base_url() + RUTA_LLAMADAS
    try:
        respuesta = sesion.get(url, headers=_headers(_token()), params=params, timeout=timeout)
        if respuesta.status_code in (401, 403):
            respuesta = sesion.get(url, headers=_headers(_token(forzar=True)), params=params, timeout=timeout)
    except MultiadminLlamadasError:
        raise
    except requests.RequestException as exc:
        raise MultiadminLlamadasError(f"No se pudo conectar con Multiadmin: {type(exc).__name__}.") from exc
    except RuntimeError as exc:  # sin tokens configurados
        raise MultiadminLlamadasError(f"No se pudo obtener el acceso a Multiadmin: {exc}") from exc
    if not respuesta.ok:
        raise MultiadminLlamadasError(
            f"Multiadmin respondió {respuesta.status_code} al pedir las llamadas.", status=respuesta.status_code
        )
    try:
        return respuesta.json()
    except ValueError as exc:
        raise MultiadminLlamadasError("Multiadmin devolvió una respuesta que no es JSON.") from exc


def listar_llamadas(desde_ms, hasta_ms, sesion=None):
    """Resumen de las llamadas analizadas entre dos instantes (milisegundos epoch)."""
    data = _get({"startDate": int(desde_ms), "endDate": int(hasta_ms)}, sesion)
    items = data.get("items") if isinstance(data, dict) else data
    return list(items or [])


def detalle_llamada(call_id, record_key, sesion=None):
    """Detalle de una llamada: rúbrica, coaching, puntos clave y analítica."""
    data = _get({"callId": call_id, "recordKey": record_key}, sesion, timeout=TIMEOUT_DETALLE)
    if not isinstance(data, dict):
        raise MultiadminLlamadasError("Multiadmin devolvió un detalle de llamada no válido.")
    return data
