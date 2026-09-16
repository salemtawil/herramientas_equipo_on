import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import requests


class ChatwootConfigError(ValueError):
    pass


@dataclass
class RangoChatwoot:
    fecha: date
    since: int
    until: int
    timezone: str
    inicio_local: str
    fin_local: str


@dataclass
class RangoReporteChatwoot:
    rangos: list
    fecha: date
    fecha_fin: date
    timezone: str
    inicio_local: str
    fin_local: str


def _env_requerida(nombre):
    valor = os.getenv(nombre, "").strip()
    if not valor:
        raise ChatwootConfigError(f"Falta configurar {nombre}.")
    return valor


def _base_url():
    return os.getenv("CHATWOOT_BASE_URL", "https://app.chatwoot.com").strip().rstrip("/")


def _account_id():
    return _env_requerida("CHATWOOT_ACCOUNT_ID")


def _api_token():
    return _env_requerida("CHATWOOT_API_ACCESS_TOKEN")


def _timezone():
    return os.getenv("CHATWOOT_TIMEZONE", "America/Caracas").strip() or "America/Caracas"


def _obtener_timezone(tz_name):
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        if tz_name == "America/Caracas":
            return timezone(timedelta(hours=-4), name=tz_name)
        if tz_name.upper() == "UTC":
            return timezone.utc
        raise ChatwootConfigError(
            f"No se pudo cargar la zona horaria {tz_name}. Usa UTC, America/Caracas "
            "o instala tzdata en el entorno."
        ) from exc


def _parsear_hora(hora_texto, nombre_campo):
    texto = str(hora_texto or "").strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"{nombre_campo} debe tener formato HH:MM.") from exc


def construir_rango_chatwoot(fecha_texto=None, hora_inicio_texto=None, hora_fin_texto=None):
    tz_name = _timezone()
    tz = _obtener_timezone(tz_name)
    ahora = datetime.now(tz)

    if fecha_texto:
        fecha = datetime.strptime(fecha_texto, "%Y-%m-%d").date()
    else:
        fecha = ahora.date()

    hora_inicio = _parsear_hora(hora_inicio_texto, "La hora de inicio") or time.min
    hora_fin = _parsear_hora(hora_fin_texto, "La hora de fin")

    inicio = datetime.combine(fecha, hora_inicio, tzinfo=tz)
    if hora_fin:
        fin = datetime.combine(fecha, hora_fin, tzinfo=tz) + timedelta(seconds=59)
    elif fecha == ahora.date():
        fin = ahora
    else:
        fin = datetime.combine(fecha + timedelta(days=1), time.min, tzinfo=tz) - timedelta(seconds=1)

    if fin <= inicio:
        raise ValueError("La hora de fin debe ser posterior a la hora de inicio.")

    return RangoChatwoot(
        fecha=fecha,
        since=int(inicio.timestamp()),
        until=int(fin.timestamp()),
        timezone=tz_name,
        inicio_local=inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin_local=fin.strftime("%Y-%m-%d %H:%M:%S"),
    )


def construir_rango_chatwoot_fechas(
    fecha_inicio_texto=None,
    fecha_fin_texto=None,
    hora_inicio_texto=None,
    hora_fin_texto=None,
):
    tz_name = _timezone()
    tz = _obtener_timezone(tz_name)
    ahora = datetime.now(tz)

    if fecha_inicio_texto:
        fecha_inicio = datetime.strptime(fecha_inicio_texto, "%Y-%m-%d").date()
    else:
        fecha_inicio = ahora.date()

    if fecha_fin_texto:
        fecha_fin = datetime.strptime(fecha_fin_texto, "%Y-%m-%d").date()
    else:
        fecha_fin = fecha_inicio

    if fecha_fin < fecha_inicio:
        raise ValueError("La fecha fin debe ser igual o posterior a la fecha inicio.")

    hora_inicio = _parsear_hora(hora_inicio_texto, "La hora de inicio") or time.min
    hora_fin = _parsear_hora(hora_fin_texto, "La hora de fin")

    inicio = datetime.combine(fecha_inicio, hora_inicio, tzinfo=tz)
    if hora_fin:
        fin = datetime.combine(fecha_fin, hora_fin, tzinfo=tz) + timedelta(seconds=59)
    elif fecha_fin == ahora.date():
        fin = ahora
    else:
        fin = datetime.combine(fecha_fin + timedelta(days=1), time.min, tzinfo=tz) - timedelta(seconds=1)

    if fin <= inicio:
        raise ValueError("El fin del rango debe ser posterior al inicio.")

    return RangoChatwoot(
        fecha=fecha_inicio,
        since=int(inicio.timestamp()),
        until=int(fin.timestamp()),
        timezone=tz_name,
        inicio_local=inicio.strftime("%Y-%m-%d %H:%M:%S"),
        fin_local=fin.strftime("%Y-%m-%d %H:%M:%S"),
    )


def construir_rango_diario(fecha_texto=None):
    return construir_rango_chatwoot(fecha_texto)


def construir_rango_madrugada(fecha_texto=None):
    tz_name = _timezone()
    tz = _obtener_timezone(tz_name)
    ahora = datetime.now(tz)

    if fecha_texto:
        fecha = datetime.strptime(fecha_texto, "%Y-%m-%d").date()
    else:
        fecha = ahora.date()

    if fecha == ahora.date() and ahora.time() < time(7, 0):
        return construir_rango_chatwoot(fecha.isoformat(), "00:00", None)

    return construir_rango_chatwoot(fecha.isoformat(), "00:00", "07:00")


def _fechas_inclusivas(fecha_inicio, fecha_fin):
    fecha = fecha_inicio
    while fecha <= fecha_fin:
        yield fecha
        fecha += timedelta(days=1)


def construir_rangos_madrugada(fecha_inicio_texto=None, fecha_fin_texto=None):
    tz_name = _timezone()
    tz = _obtener_timezone(tz_name)
    ahora = datetime.now(tz)

    if fecha_inicio_texto:
        fecha_inicio = datetime.strptime(fecha_inicio_texto, "%Y-%m-%d").date()
    else:
        fecha_inicio = ahora.date()

    if fecha_fin_texto:
        fecha_fin = datetime.strptime(fecha_fin_texto, "%Y-%m-%d").date()
    else:
        fecha_fin = fecha_inicio

    if fecha_fin < fecha_inicio:
        raise ValueError("La fecha fin debe ser igual o posterior a la fecha inicio.")

    return [construir_rango_madrugada(fecha.isoformat()) for fecha in _fechas_inclusivas(fecha_inicio, fecha_fin)]


def construir_rango_reporte(
    tipo_rango="diario",
    fecha_texto=None,
    hora_inicio_texto=None,
    hora_fin_texto=None,
    fecha_fin_texto=None,
):
    if tipo_rango == "madrugada":
        rangos = construir_rangos_madrugada(fecha_texto, fecha_fin_texto)
    else:
        rangos = [
            construir_rango_chatwoot_fechas(
                fecha_texto,
                fecha_fin_texto,
                hora_inicio_texto,
                hora_fin_texto,
            )
        ]

    return RangoReporteChatwoot(
        rangos=rangos,
        fecha=rangos[0].fecha,
        fecha_fin=rangos[-1].fecha,
        timezone=rangos[0].timezone,
        inicio_local=rangos[0].inicio_local,
        fin_local=rangos[-1].fin_local,
    )


def _rango_unico_reporte(
    tipo_rango="diario",
    fecha_texto=None,
    hora_inicio_texto=None,
    hora_fin_texto=None,
):
    return construir_rango_reporte(tipo_rango, fecha_texto, hora_inicio_texto, hora_fin_texto).rangos[0]


class ChatwootClient:
    def __init__(self, base_url=None, account_id=None, api_token=None, timeout=30):
        self.base_url = (base_url or _base_url()).rstrip("/")
        self.account_id = account_id or _account_id()
        self.api_token = api_token or _api_token()
        self.timeout = timeout

    @property
    def headers(self):
        return {"api_access_token": self.api_token}

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        respuesta = requests.get(url, headers=self.headers, params=params or {}, timeout=self.timeout)
        if respuesta.status_code >= 400:
            self._raise_http_error(respuesta, url)
        try:
            return respuesta.json()
        except ValueError as exc:
            content_type = respuesta.headers.get("content-type", "")
            raise RuntimeError(
                "Chatwoot no devolvio JSON. "
                f"URL: {url}. Content-Type: {content_type}."
            ) from exc

    def _raise_http_error(self, respuesta, url):
        detalle = respuesta.text[:300]
        content_type = respuesta.headers.get("content-type", "")
        if "<!DOCTYPE html" in detalle or "text/html" in content_type:
            raise RuntimeError(
                f"Chatwoot respondio {respuesta.status_code} con una pagina HTML en {url}. "
                "Verifica que CHATWOOT_BASE_URL apunte a https://chat.mybrandpatch.com, "
                "CHATWOOT_ACCOUNT_ID sea 2 y que el endpoint custom de llamadas exista."
            )
        raise RuntimeError(f"Chatwoot respondio {respuesta.status_code} en {url}: {detalle}")

    def listar_agentes(self):
        return self.get(f"/api/v1/accounts/{self.account_id}/agents")

    def resumen_por_agente(self, rango):
        return self.get(
            f"/api/v2/accounts/{self.account_id}/summary_reports/agent",
            params={"since": str(rango.since), "until": str(rango.until)},
        )

    def mensajes_salientes_por_agente(self, rango):
        return self.get(
            f"/api/v2/accounts/{self.account_id}/reports/outgoing_messages_count",
            params={"group_by": "agent", "since": str(rango.since), "until": str(rango.until)},
        )

    def estadisticas_llamadas(self, rango, group_by="agent"):
        return self.get(
            f"/custom/api/v1/accounts/{self.account_id}/call_stats",
            params={"group_by": group_by, "since": str(rango.since), "until": str(rango.until)},
        )


def _partir_nombre(nombre):
    partes = str(nombre or "").strip().split()
    if not partes:
        return "", ""
    return partes[0], " ".join(partes[1:])


def _indice_agentes(agentes):
    indice = {}
    for agente in agentes or []:
        agente_id = agente.get("id")
        if agente_id is None:
            continue
        nombre = agente.get("name") or agente.get("available_name") or agente.get("email") or f"Agente {agente_id}"
        indice[int(agente_id)] = nombre
    return indice


def _normalizar_lista_respuesta(respuesta):
    if isinstance(respuesta, list):
        return respuesta
    if isinstance(respuesta, dict):
        payload = respuesta.get("payload")
        if isinstance(payload, list):
            return payload
        data = respuesta.get("data")
        if isinstance(data, list):
            return data
    return []


def _normalizar_float(valor):
    numero = pd.to_numeric(valor, errors="coerce")
    if pd.isna(numero):
        return 0.0
    return float(numero)


def _normalizar_int(valor):
    return int(round(_normalizar_float(valor)))


def _valor(item, *claves, default=None):
    for clave in claves:
        if clave in item:
            return item.get(clave)
    return default


def _filas_call_stats(respuesta):
    if isinstance(respuesta, dict):
        filas = respuesta.get("rows")
        if isinstance(filas, list):
            return filas
    if isinstance(respuesta, list):
        return respuesta
    return []


def _nombre_fila_call_stats(fila, agentes):
    agente_id = _valor(fila, "id", "agent_id", "agentId")
    if agente_id is not None:
        try:
            agente_id = int(agente_id)
        except (TypeError, ValueError):
            pass
        nombre = agentes.get(agente_id)
        if nombre:
            return nombre

    return (
        _valor(fila, "name")
        or _valor(fila, "agent")
        or _valor(fila, "email")
        or _valor(fila, "inbox")
        or "Sin asignar"
    )


def _dataframe_desde_call_stats(respuesta, agentes):
    filas = []
    for item in _filas_call_stats(respuesta):
        nombre = _nombre_fila_call_stats(item, agentes)
        first_name, last_name = _partir_nombre(nombre)

        contestadas = _normalizar_int(_valor(item, "callsAnswered", "calls_answered"))
        perdidas = _normalizar_int(_valor(item, "missedCalls", "missed_calls"))
        salientes = _normalizar_int(_valor(item, "outboundCalls", "outbound_calls"))
        mins_llamadas = _normalizar_float(_valor(item, "callMinutes", "call_minutes"))
        mins_salientes = _normalizar_float(
            _valor(item, "outboundCallMinutes", "outbound_call_minutes")
        )

        if not any([contestadas, perdidas, salientes, mins_llamadas, mins_salientes]):
            continue

        filas.append(
            {
                "First Name": first_name,
                "Last Name": last_name,
                "Calls": contestadas + perdidas,
                "Outgoing calls": salientes,
                "Missed calls": perdidas,
                "Call seconds": round(mins_llamadas * 60),
                "Outgoing call seconds": round(mins_salientes * 60),
                "Worktime": "00:00:01",
            }
        )

    return pd.DataFrame(filas)


def obtener_dataframe_reporte_chatwoot(
    fecha_texto=None,
    hora_inicio_texto=None,
    hora_fin_texto=None,
    cliente=None,
    tipo_rango="diario",
    fecha_fin_texto=None,
):
    rango_reporte = construir_rango_reporte(
        tipo_rango,
        fecha_texto,
        hora_inicio_texto,
        hora_fin_texto,
        fecha_fin_texto,
    )
    cliente = cliente or ChatwootClient()

    agentes = _indice_agentes(_normalizar_lista_respuesta(cliente.listar_agentes()))
    dataframes = []
    for rango in rango_reporte.rangos:
        respuesta_call_stats = cliente.estadisticas_llamadas(rango, group_by="agent")
        dataframes.append(_dataframe_desde_call_stats(respuesta_call_stats, agentes))

    df = pd.concat(dataframes, ignore_index=True) if dataframes else pd.DataFrame()
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "First Name",
                "Last Name",
                "Calls",
                "Outgoing calls",
                "Missed calls",
                "Call seconds",
                "Outgoing call seconds",
                "Worktime",
            ]
        )

    metadata = {
        "fecha": rango_reporte.fecha.isoformat(),
        "fecha_fin": rango_reporte.fecha_fin.isoformat(),
        "since": rango_reporte.rangos[0].since,
        "until": rango_reporte.rangos[-1].until,
        "timezone": rango_reporte.timezone,
        "inicio_local": rango_reporte.inicio_local,
        "fin_local": rango_reporte.fin_local,
        "fuente": "Chatwoot",
        "tipo_rango": tipo_rango,
        "cantidad_rangos": len(rango_reporte.rangos),
    }
    return df, metadata
