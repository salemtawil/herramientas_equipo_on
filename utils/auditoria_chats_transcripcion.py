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


_RE_REGISTRO_LLAMADA = re.compile(
    r"^\s*(llamada|call)\s+(entrante|saliente|perdida|finalizada|terminada|recibida|incoming|outgoing|missed|ended|completed)"
    r"|^\s*(missed|incoming|outgoing)\s+call",
    re.IGNORECASE,
)
MAX_FORMA = 40


def es_llamada(mensajes):
    """True si la conversación es una llamada (no un chat con notas de voz).

    Una nota de voz es un adjunto de audio en un mensaje normal y no cuenta. Una llamada deja
    mensajes de tipo llamada, atributos de llamada (call_status, call_sid…) o un registro de sistema
    del estilo «Llamada entrante…» / «Missed call…».
    """
    for mensaje in mensajes or []:
        if "call" in str(mensaje.get("content_type") or "").lower():
            return True
        atributos = mensaje.get("content_attributes") or {}
        if isinstance(atributos, dict) and any("call" in str(clave).lower() for clave in atributos):
            return True
        if mensaje.get("message_type") == 2 and _RE_REGISTRO_LLAMADA.search(_texto(mensaje)):
            return True
    return False


def forma_mensajes(mensajes):
    """Estructura de la conversación sin ningún texto ni enlace, para diagnosticar descartes."""
    forma = []
    for mensaje in (mensajes or [])[:MAX_FORMA]:
        atributos = mensaje.get("content_attributes") or {}
        forma.append(
            {
                "tipo": mensaje.get("message_type"),
                "content_type": mensaje.get("content_type"),
                "con_texto": bool(_texto(mensaje)),
                "adjuntos": [str(a.get("file_type") or "") for a in mensaje.get("attachments") or []],
                "atributos": sorted(str(k) for k in atributos) if isinstance(atributos, dict) else [],
                "privado": bool(mensaje.get("private")),
            }
        )
    return forma


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

    return _recortar("\n".join(lineas), max_chars)


def _recortar(texto, max_chars):
    if len(texto) <= max_chars:
        return texto
    mitad = max_chars // 2
    return texto[:mitad] + SEPARADOR_RECORTE + texto[-mitad:]


# ---------------------------------------------------------------------------
# Pauta QA-1.1: transcripción con identificadores, período del agente y tiempos
# ---------------------------------------------------------------------------

MENSAJE_ACTIVIDAD = 2
ESPERA_MAXIMA_SEGUNDOS = 180

_RE_ASIGNACION = re.compile(r"(?:assigned to|asignad[oa] a)\s+(.+?)(?:\s+(?:by|por)\s+.*)?$", re.IGNORECASE)
_RE_AUTOASIGNACION = re.compile(r"^(.+?)\s+(?:self-assigned|se auto-?asign)", re.IGNORECASE)
_RE_RESOLUCION = re.compile(r"resolved|resuelt", re.IGNORECASE)
_RE_RESUELTO_POR = re.compile(r"(?:by|por)\s+(.+?)\.?$", re.IGNORECASE)
_RE_AUTOMATICO = re.compile(r"automatic|automátic", re.IGNORECASE)


def _id(mensaje):
    return f"m{mensaje.get('id')}"


def _ts_mensaje(mensaje):
    return int(mensaje.get("created_at") or 0)


def _ordenados(mensajes):
    return sorted(mensajes or [], key=lambda m: (_ts_mensaje(m), m.get("id") or 0))


def _remitente(mensaje):
    sender = mensaje.get("sender") or {}
    return sender if isinstance(sender, dict) else {}


def _es_respuesta_agente(mensaje, agente_id=None):
    if mensaje.get("message_type") != MENSAJE_SALIENTE or mensaje.get("private") or not _texto(mensaje):
        return False
    return agente_id is None or _remitente(mensaje).get("id") == agente_id


def _es_cliente(mensaje):
    return mensaje.get("message_type") == MENSAJE_ENTRANTE and not mensaje.get("private")


def _mensajes_v2(mensajes):
    incluidos = []
    for mensaje in _ordenados(mensajes):
        tipo = mensaje.get("message_type")
        if tipo in (MENSAJE_ENTRANTE, MENSAJE_SALIENTE) and (_texto(mensaje) or mensaje.get("attachments")):
            incluidos.append(mensaje)
        elif tipo == MENSAJE_ACTIVIDAD and _texto(mensaje):
            incluidos.append(mensaje)
    return incluidos


def ids_mensajes(mensajes):
    return {_id(m) for m in _mensajes_v2(mensajes)}


def _autor_v2(mensaje):
    tipo = mensaje.get("message_type")
    if tipo == MENSAJE_ACTIVIDAD:
        return "Sistema"
    if tipo == MENSAJE_ENTRANTE:
        return "Cliente"
    nombre = _remitente(mensaje).get("name") or "sin nombre"
    return f"Nota interna ({nombre})" if mensaje.get("private") else f"Agente ({nombre})"


def construir_transcripcion_v2(mensajes, tz_name, max_chars=12000):
    tz = _obtener_timezone(tz_name)
    lineas = []
    for mensaje in _mensajes_v2(mensajes):
        hora = datetime.fromtimestamp(_ts_mensaje(mensaje), tz).strftime("%H:%M:%S")
        partes = [" ".join(anonimizar(_texto(mensaje)).split())] + _etiquetas_adjuntos(mensaje)
        contenido = " ".join(p for p in partes if p)
        lineas.append(f"[{_id(mensaje)} {hora}] {_autor_v2(mensaje)}: {contenido}")
    return _recortar("\n".join(lineas), max_chars)


def _asignado_a(mensaje):
    """Nombre de la persona asignada en un mensaje de actividad, o None."""
    if mensaje.get("message_type") != MENSAJE_ACTIVIDAD:
        return None
    texto = _texto(mensaje)
    coincidencia = _RE_ASIGNACION.search(texto) or _RE_AUTOASIGNACION.search(texto)
    return coincidencia.group(1).strip().rstrip(".") if coincidencia else None


def _es_resolucion(mensaje):
    return mensaje.get("message_type") == MENSAJE_ACTIVIDAD and bool(_RE_RESOLUCION.search(_texto(mensaje)))


def _mismo_nombre(a, b):
    a, b = " ".join(str(a or "").lower().split()), " ".join(str(b or "").lower().split())
    return bool(a and b) and (a == b or a in b or b in a)


def periodo_agente(mensajes, agente_id, agente_nombre):
    """Tramo de la conversación a cargo del agente: desde su asignación (o su primer mensaje)
    hasta la asignación a otra persona o la resolución."""
    ordenados = _ordenados(mensajes)
    inicio = None
    for indice, mensaje in enumerate(ordenados):
        asignado = _asignado_a(mensaje)
        if (asignado and _mismo_nombre(asignado, agente_nombre)) or _es_respuesta_agente(mensaje, agente_id):
            inicio = indice
            break
    if inicio is None:
        return {"desde": None, "hasta": None, "inferido": False}

    hasta = None
    for mensaje in ordenados[inicio + 1 :]:
        asignado = _asignado_a(mensaje)
        if (asignado and not _mismo_nombre(asignado, agente_nombre)) or _es_resolucion(mensaje):
            hasta = _id(mensaje)
            break
    return {"desde": _id(ordenados[inicio]), "hasta": hasta, "inferido": True}


def _tramo(ordenados, periodo):
    ids = [_id(m) for m in ordenados]
    if not periodo or periodo.get("desde") not in ids:
        return []
    desde = ids.index(periodo["desde"])
    hasta = ids.index(periodo["hasta"]) if periodo.get("hasta") in ids else len(ordenados) - 1
    return ordenados[desde : hasta + 1]


def _esperas(mensajes, agente_id=None):
    esperas, esperando = [], None
    for mensaje in mensajes:
        if _es_cliente(mensaje):
            esperando = esperando or mensaje
        elif _es_respuesta_agente(mensaje):
            if esperando and (agente_id is None or _remitente(mensaje).get("id") == agente_id):
                segundos = _ts_mensaje(mensaje) - _ts_mensaje(esperando)
                if segundos > ESPERA_MAXIMA_SEGUNDOS:
                    esperas.append({"desde": _id(esperando), "hasta": _id(mensaje), "segundos": segundos})
            esperando = None
    return esperas


def _primera_respuesta(mensajes, agente_id=None):
    cliente = next((m for m in mensajes if _es_cliente(m)), None)
    if not cliente:
        return None
    respuesta = next(
        (m for m in mensajes if _ts_mensaje(m) >= _ts_mensaje(cliente) and _es_respuesta_agente(m, agente_id)),
        None,
    )
    if not respuesta:
        return None
    return {"segundos": _ts_mensaje(respuesta) - _ts_mensaje(cliente), "desde": _id(cliente), "hasta": _id(respuesta)}


def _primera_respuesta_agente(ordenados, tramo, agente_id):
    if not tramo:
        return None
    inicio = tramo[0]
    pendiente = None
    for mensaje in ordenados[: ordenados.index(inicio)]:
        if _es_cliente(mensaje):
            pendiente = pendiente or mensaje
        elif _es_respuesta_agente(mensaje):
            pendiente = None
    if pendiente:
        # El cliente ya esperaba cuando llegó la asignación: se cuenta desde la asignación.
        respuesta = next((m for m in tramo if _es_respuesta_agente(m, agente_id)), None)
        if not respuesta:
            return None
        return {"segundos": _ts_mensaje(respuesta) - _ts_mensaje(inicio), "desde": _id(inicio), "hasta": _id(respuesta)}
    return _primera_respuesta(tramo, agente_id)


def _quien_cerro(mensaje, agente_nombre):
    texto = _texto(mensaje)
    if _RE_AUTOMATICO.search(texto):
        return "sistema"
    por = _RE_RESUELTO_POR.search(texto)
    if not por:
        return None
    return "agente" if _mismo_nombre(por.group(1), agente_nombre) else "otro_agente"


def _inactividad(ordenados, agente_nombre):
    ultimo_cliente = max((i for i, m in enumerate(ordenados) if _es_cliente(m)), default=None)
    resultado = {"ultimo_cliente": None, "mensajes_agente": [], "cierre": None}
    if ultimo_cliente is None:
        return resultado
    resultado["ultimo_cliente"] = _id(ordenados[ultimo_cliente])
    anterior = ordenados[ultimo_cliente]
    for mensaje in ordenados[ultimo_cliente + 1 :]:
        if _es_respuesta_agente(mensaje):
            resultado["mensajes_agente"].append(
                {"id": _id(mensaje), "segundos_desde_anterior": _ts_mensaje(mensaje) - _ts_mensaje(anterior)}
            )
            anterior = mensaje
        elif _es_resolucion(mensaje) and resultado["cierre"] is None:
            resultado["cierre"] = {
                "id": _id(mensaje),
                "segundos_desde_ultimo_mensaje": _ts_mensaje(mensaje) - _ts_mensaje(anterior),
                "cerro": _quien_cerro(mensaje, agente_nombre),
            }
    return resultado


def metricas_tiempos(mensajes, periodo, agente_id, agente_nombre=""):
    """Tiempos del chat en segundos, con los ids de los mensajes que los originan.

    Las métricas «oficiales» cuentan a cualquier agente; las del agente evaluado solo cuentan sus
    respuestas dentro de su período, para no cargarle demoras de un colega.
    """
    ordenados = _ordenados(mensajes)
    tramo = _tramo(ordenados, periodo)
    if not agente_nombre:
        agente_nombre = next(
            (_remitente(m).get("name") for m in ordenados if _remitente(m).get("id") == agente_id), ""
        )
    return {
        "primera_respuesta": _primera_respuesta(ordenados),
        "primera_respuesta_agente": _primera_respuesta_agente(ordenados, tramo, agente_id),
        "esperas_largas_oficiales": _esperas(ordenados),
        "esperas_largas": _esperas(tramo, agente_id),
        "inactividad": _inactividad(ordenados, agente_nombre),
    }
