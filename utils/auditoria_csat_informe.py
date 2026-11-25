"""Bloque de texto con la auditoría CSAT para el informe semanal de CS."""

from datetime import date

from utils.chatwoot_reportes import construir_rango_chatwoot_fechas
from utils.csat_periodos import formatear_periodo, periodo_anterior

MAX_CASOS_RELEVANTES = 5
MAX_TEXTO_CASO = 200


def _fecha(valor):
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor)[:10])


def _pct(valor):
    return f"{float(valor or 0):.1f}%"


def _recortar(texto, maximo=MAX_TEXTO_CASO):
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= maximo else texto[: maximo - 1].rstrip() + "…"


def _calcular_csat(positivos, total):
    from tools.auditoria_csat import calcular_csat

    return calcular_csat(positivos, total)


def _linea_anterior(anterior):
    texto = f"Período anterior: {anterior.get('periodo', '')}"
    if anterior.get("error"):
        return f"{texto} — {anterior['error']}"
    detalle = f"CSAT real {_pct(anterior.get('csat_real'))}"
    if anterior.get("auditado") and anterior.get("csat_ajustado") is not None:
        detalle += f", CSAT ajustado {_pct(anterior['csat_ajustado'])}"
    else:
        detalle += " (sin auditoría)"
    return f"{texto} — {detalle}, {anterior.get('total', 0)} encuestas"


def _casos_relevantes(negativos):
    excluidos = [n for n in negativos if n.get("decision_final") == "SÍ"]
    no = [n for n in negativos if n.get("decision_final") == "NO"]
    return (excluidos + no)[:MAX_CASOS_RELEVANTES]


def construir_bloque_csat(periodo, negativos, anterior):
    negativos = list(negativos or [])
    inicio, fin = _fecha(periodo["fecha_inicio"]), _fecha(periodo["fecha_fin"])
    ratings = periodo.get("ratings_count") or {}
    distribucion = ", ".join(f"{n}★: {int(ratings.get(str(n)) or 0)}" for n in range(1, 6))

    lineas = [
        f"Período auditado: {formatear_periodo(inicio, fin)}",
        f"Total de encuestas: {periodo.get('total_encuestas') or 0}",
        f"Distribución: {distribucion}",
        f"CSAT real: {_pct(periodo.get('csat_real'))}",
        f"CSAT ajustado: {_pct(periodo.get('csat_ajustado'))}",
        "Por agente:",
    ]
    por_agente = periodo.get("por_agente") or []
    if not por_agente:
        lineas.append("- Sin datos por agente")
    for fila in por_agente:
        lineas.append(
            f"- {fila.get('Agente', 'Sin agente')}: CSAT original {_pct(fila.get('CSAT original'))}, "
            f"auditado {_pct(fila.get('CSAT auditado'))}, negativas {fila.get('Negativas', 0)}, "
            f"excluidas {fila.get('SÍ', 0)}"
        )

    lineas.append("Negativos por motivo:")
    conteo = {}
    for negativo in negativos:
        motivo = (negativo.get("motivo_final") or "").strip()
        if motivo:
            conteo[motivo] = conteo.get(motivo, 0) + 1
    if not conteo:
        lineas.append("- Sin motivos registrados")
    for motivo, cantidad in sorted(conteo.items(), key=lambda item: (-item[1], item[0])):
        lineas.append(f"- {motivo}: {cantidad}")

    lineas.append(
        f"Negativos excluidos (no atribuibles al agente): {periodo.get('negativos_excluidos') or 0} "
        f"de {periodo.get('negativos_total') or 0}"
    )
    lineas.append(f"Auditados a mano: {sum(1 for n in negativos if n.get('origen_decision') == 'humana')}")
    lineas.append(f"Aceptados de la IA: {sum(1 for n in negativos if n.get('origen_decision') == 'ia_aceptada')}")
    lineas.append(f"Negativos pendientes de confirmar: {periodo.get('negativos_pendientes') or 0}")

    lineas.append("Casos relevantes:")
    casos = _casos_relevantes(negativos)
    if not casos:
        lineas.append("- Sin casos auditados")
    for caso in casos:
        decision = "excluido (no atribuible al agente)" if caso.get("decision_final") == "SÍ" else "atribuible al agente"
        partes = [
            f"- Conversación {caso.get('conversation_id')} ({caso.get('agente_nombre') or 'Sin agente'}): {decision}",
            f"comentario: {_recortar(caso.get('comentario')) or 'sin comentario'}",
            f"motivo: {caso.get('motivo_final') or 'sin motivo'}",
        ]
        respaldo = _recortar(caso.get("nota_auditor") or caso.get("ia_evidencia"))
        if respaldo:
            partes.append(f"evidencia/nota: {respaldo}")
        lineas.append("; ".join(partes))

    lineas.append(_linea_anterior(anterior))
    return "\n".join(lineas)


def datos_periodo_anterior(store, chatwoot, periodo, tz_name):
    inicio, fin = _fecha(periodo["fecha_inicio"]), _fecha(periodo["fecha_fin"])
    tipo = periodo.get("tipo_periodo") or "personalizado"
    ini_ant, fin_ant = periodo_anterior(tipo, inicio, fin)
    texto = formatear_periodo(ini_ant, fin_ant)

    guardado = None
    if store is not None:
        try:
            guardado = store.buscar_periodo(ini_ant, fin_ant)
        except Exception:
            guardado = None
    if guardado:
        return {
            "periodo": texto,
            "csat_real": float(guardado.get("csat_real") or 0),
            "csat_ajustado": guardado.get("csat_ajustado"),
            "total": int(guardado.get("total_encuestas") or 0),
            "auditado": True,
        }

    try:
        rango = construir_rango_chatwoot_fechas(ini_ant.isoformat(), fin_ant.isoformat())
        metricas = chatwoot.metricas_csat(rango.since, rango.until)
        ratings = (metricas or {}).get("ratings_count") or {}
        total = sum(int(valor or 0) for valor in ratings.values())
        positivos = int(ratings.get("4") or 0) + int(ratings.get("5") or 0)
    except Exception:
        return {"periodo": texto, "error": "sin datos"}
    return {
        "periodo": texto,
        "csat_real": _calcular_csat(positivos, total),
        "csat_ajustado": None,
        "total": total,
        "auditado": False,
    }


def bloque_desde_estado(estado, chatwoot, tz_name):
    from utils.auditoria_csat_chatwoot import negativos_para_guardar, resumen_para_guardar

    filas = estado.get("rows") or []
    periodo = {
        "tipo_periodo": estado.get("tipo_periodo") or "personalizado",
        "fecha_inicio": estado["fecha_inicio"],
        "fecha_fin": estado["fecha_fin"],
        **resumen_para_guardar(filas),
    }
    anterior = datos_periodo_anterior(None, chatwoot, periodo, tz_name)
    return construir_bloque_csat(periodo, negativos_para_guardar(filas), anterior)
