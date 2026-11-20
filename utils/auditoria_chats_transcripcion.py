"""Transcripción y anonimización de conversaciones de Chatwoot para la auditoría de chats."""

import re
from datetime import datetime

from utils.chatwoot_reportes import _obtener_timezone

MENSAJE_ENTRANTE = 0
MENSAJE_SALIENTE = 1
SEPARADOR_RECORTE = "\n[…]\n"

_RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RE_NUMERO_LARGO = re.compile(r"\d{8,}")
_RE_TELEFONO = re.compile(r"\+?\(?\d[\d\s\-().]{5,}\d")


def _reemplazar_telefono(coincidencia):
    texto = coincidencia.group(0)
    if sum(caracter.isdigit() for caracter in texto) >= 7:
        return "[teléfono]"
    return texto


def anonimizar(texto):
    texto = _RE_CORREO.sub("[correo]", str(texto or ""))
    texto = _RE_NUMERO_LARGO.sub("[número]", texto)
    return _RE_TELEFONO.sub(_reemplazar_telefono, texto)


ETIQUETAS_ADJUNTO = {
    "audio": "[nota de voz]",
    "image": "[imagen]",
    "video": "[video]",
    "file": "[archivo]",
    "location": "[ubicación]",
    "contact": "[contacto]",
}


def _texto(mensaje):
    return str(mensaje.get("content") or "").strip()


def _etiquetas_adjuntos(mensaje):
    adjuntos = mensaje.get("attachments") or []
    return [ETIQUETAS_ADJUNTO.get(str(a.get("file_type") or "").lower(), "[adjunto]") for a in adjuntos]


def mensajes_utiles(mensajes):
    utiles = []
    for mensaje in mensajes or []:
        if mensaje.get("message_type") not in (MENSAJE_ENTRANTE, MENSAJE_SALIENTE):
            continue
        if mensaje.get("private"):
            continue
        if not _texto(mensaje) and not mensaje.get("attachments"):
            continue
        utiles.append(mensaje)
    return utiles


def tiene_mensajes_de_agente(mensajes):
    """Solo cuentan las respuestas escritas del agente: un chat atendido solo con audios no es auditable."""
    return any(m.get("message_type") == MENSAJE_SALIENTE and _texto(m) for m in mensajes_utiles(mensajes))


def construir_transcripcion(mensajes, tz_name, max_chars=6000):
    tz = _obtener_timezone(tz_name)
    lineas = []
    for mensaje in mensajes_utiles(mensajes):
        hora = datetime.fromtimestamp(int(mensaje.get("created_at") or 0), tz).strftime("%H:%M")
        autor = "Agente" if mensaje.get("message_type") == MENSAJE_SALIENTE else "Cliente"
        partes = [" ".join(anonimizar(_texto(mensaje)).split())] + _etiquetas_adjuntos(mensaje)
        contenido = " ".join(p for p in partes if p)
        lineas.append(f"[{hora}] {autor}: {contenido}")

    texto = "\n".join(lineas)
    if len(texto) <= max_chars:
        return texto
    mitad = max_chars // 2
    return texto[:mitad] + SEPARADOR_RECORTE + texto[-mitad:]
