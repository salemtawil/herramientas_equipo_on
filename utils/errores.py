"""Mensajes de error seguros para mostrar en la interfaz del admin."""

import requests

MENSAJE_DETALLE_EN_LOGS = "El detalle técnico quedó registrado en el servidor."


def mensaje_error_publico(exc, prefijo):
    """Devuelve un texto apto para la UI a partir de una excepción capturada.

    Los ValueError y RuntimeError que lanza el código de la app llevan mensajes
    pensados para el usuario (columnas faltantes, configuración pendiente,
    archivo demasiado grande, etc.) y se muestran tal cual. Cualquier otra
    excepción, y los errores de red de ``requests`` (que incluyen URLs
    internas), se sustituye por un mensaje genérico. El detalle completo debe
    registrarse con ``logger.exception`` en el servidor.
    """
    es_error_de_red = isinstance(exc, requests.exceptions.RequestException)
    if isinstance(exc, (ValueError, RuntimeError)) and not es_error_de_red:
        detalle = str(exc).strip()
        if detalle:
            return f"{prefijo}: {detalle}"
    return f"{prefijo}. {MENSAJE_DETALLE_EN_LOGS}"
