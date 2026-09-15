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


def construir_rango_diario(fecha_texto=None):
    return construir_rango_chatwoot(fecha_texto)


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
            detalle = respuesta.text[:300]
            raise RuntimeError(f"Chatwoot respondio {respuesta.status_code}: {detalle}")
        return respuesta.json()

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
            f"/api/v1/accounts/{self.account_id}/call_stats",
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


def _filas_call_stats(respuesta):
    if isinstance(respuesta, dict):
        filas = respuesta.get("rows")
        if isinstance(filas, list):
            return filas
    if isinstance(respuesta, list):
        return respuesta
    return []


def _nombre_fila_call_stats(fila, agentes):
    agente_id = fila.get("id")
    if agente_id is not None:
        try:
            agente_id = int(agente_id)
        except (TypeError, ValueError):
            pass
        nombre = agentes.get(agente_id)
        if nombre:
            return nombre

    return (
        fila.get("name")
        or fila.get("agent")
        or fila.get("email")
        or fila.get("inbox")
        or "Sin asignar"
    )


def _dataframe_desde_call_stats(respuesta, agentes):
    filas = []
    for item in _filas_call_stats(respuesta):
        nombre = _nombre_fila_call_stats(item, agentes)
        first_name, last_name = _partir_nombre(nombre)

        contestadas = _normalizar_int(item.get("callsAnswered"))
        perdidas = _normalizar_int(item.get("missedCalls"))
        salientes = _normalizar_int(item.get("outboundCalls"))
        mins_llamadas = _normalizar_float(item.get("callMinutes"))
        mins_salientes = _normalizar_float(item.get("outboundCallMinutes"))

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


def obtener_dataframe_reporte_chatwoot(fecha_texto=None, hora_inicio_texto=None, hora_fin_texto=None, cliente=None):
    rango = construir_rango_chatwoot(fecha_texto, hora_inicio_texto, hora_fin_texto)
    cliente = cliente or ChatwootClient()

    agentes = _indice_agentes(_normalizar_lista_respuesta(cliente.listar_agentes()))
    respuesta_call_stats = cliente.estadisticas_llamadas(rango, group_by="agent")
    df = _dataframe_desde_call_stats(respuesta_call_stats, agentes)
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
        "fecha": rango.fecha.isoformat(),
        "since": rango.since,
        "until": rango.until,
        "timezone": rango.timezone,
        "inicio_local": rango.inicio_local,
        "fin_local": rango.fin_local,
        "fuente": "Chatwoot",
    }
    return df, metadata
