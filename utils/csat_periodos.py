"""Períodos seleccionables para la auditoría CSAT."""
from datetime import date, datetime, timedelta

TIPOS_PERIODO: list[tuple[str, str]] = [
    ("semana_pasada", "Semana pasada (lun–dom)"),
    ("esta_semana", "Esta semana"),
    ("ultimos_7", "Últimos 7 días"),
    ("mes_pasado", "Mes pasado"),
    ("este_mes", "Este mes"),
    ("personalizado", "Personalizado"),
]

_TIPOS_VALIDOS = {clave for clave, _ in TIPOS_PERIODO}


def _parsear_fecha(texto: str | None, nombre: str) -> date:
    if not texto:
        raise ValueError(f"Falta la fecha {nombre} para el período personalizado.")
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"La fecha {nombre} no es válida (use AAAA-MM-DD).") from None


def _validar_tipo(tipo: str) -> None:
    if tipo not in _TIPOS_VALIDOS:
        raise ValueError(f"Tipo de período desconocido: {tipo}.")


def resolver_periodo(
    tipo: str,
    hoy: date,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
) -> tuple[date, date]:
    """Devuelve (inicio, fin) del período elegido, con `hoy` como referencia."""
    _validar_tipo(tipo)
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    primer_dia_mes = hoy.replace(day=1)

    if tipo == "semana_pasada":
        inicio = lunes_actual - timedelta(days=7)
        return inicio, inicio + timedelta(days=6)
    if tipo == "esta_semana":
        return lunes_actual, hoy
    if tipo == "ultimos_7":
        return hoy - timedelta(days=6), hoy
    if tipo == "mes_pasado":
        fin = primer_dia_mes - timedelta(days=1)
        return fin.replace(day=1), fin
    if tipo == "este_mes":
        return primer_dia_mes, hoy

    inicio = _parsear_fecha(fecha_inicio, "de inicio")
    fin = _parsear_fecha(fecha_fin, "de fin")
    if fin < inicio:
        raise ValueError("La fecha de fin no puede ser anterior a la de inicio.")
    return inicio, fin


def periodo_anterior(tipo: str, inicio: date, fin: date) -> tuple[date, date]:
    """Devuelve el período comparable inmediatamente anterior al indicado."""
    _validar_tipo(tipo)
    if tipo in ("semana_pasada", "esta_semana"):
        return inicio - timedelta(days=7), inicio - timedelta(days=1)
    if tipo in ("mes_pasado", "este_mes"):
        fin_anterior = inicio - timedelta(days=1)
        return fin_anterior.replace(day=1), fin_anterior
    # ultimos_7 y personalizado: mismo largo justo antes
    largo = (fin - inicio).days + 1
    return inicio - timedelta(days=largo), inicio - timedelta(days=1)


def formatear_periodo(inicio: date, fin: date) -> str:
    """Formato de visualización: dd/mm/aa al dd/mm/aa."""
    return f"{inicio.strftime('%d/%m/%y')} al {fin.strftime('%d/%m/%y')}"
