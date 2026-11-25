"""Modelo de vista de la auditoría CSAT: pasos, KPIs, fichas y pestañas."""

TEXTO_DECISION = {
    "SÍ": "No fue culpa del agente",
    "NO": "Sí fue culpa del agente",
    "TAL VEZ": "Dudoso",
}

TITULOS_PASOS = (
    ("encuestas", "Encuestas"),
    ("ia", "La IA revisa"),
    ("confirmar", "Tú confirmas"),
    ("resultado", "Resultado"),
)

ORIGEN_TEXTO = {"humana": "tú", "ia_aceptada": "aceptado de la IA"}


def _negativos(filas):
    return [f for f in filas if f.get("tipo_rating") == "Negativo"]


def construir_kpis(metricas):
    real = metricas.get("csat_original", 0)
    ajustado = metricas.get("csat_actualizado", 0)
    return {
        "csat_real": real,
        "csat_ajustado": ajustado,
        "delta": round(ajustado - real, 2),
        "excluidos": metricas.get("negativos_si", 0),
        "negativos": metricas.get("negativos", 0),
        "por_confirmar": metricas.get("negativos_pendientes", 0),
    }


def construir_pasos(filas):
    negativos = _negativos(filas)
    neg = len(negativos)
    por_revisar = [f for f in negativos if f.get("origen_decision") != "humana"]
    con_propuesta = sum(1 for f in por_revisar if f.get("ia_justificable"))
    confirmadas = sum(1 for f in negativos if f.get("justificable"))
    hecho_ia = con_propuesta == len(por_revisar)
    hecho_confirmar = confirmadas == neg
    detalles = {
        "encuestas": (bool(filas), f"{len(filas)} encuestas · {neg} negativas"),
        "ia": (
            hecho_ia,
            f"{con_propuesta} de {len(por_revisar)} con propuesta" if por_revisar else "Sin negativos por revisar",
        ),
        "confirmar": (hecho_confirmar, f"{confirmadas} de {neg} confirmadas"),
        "resultado": (hecho_confirmar, "CSAT final e informe"),
    }
    pasos = []
    hay_actual = False
    for clave, titulo in TITULOS_PASOS:
        hecho, detalle = detalles[clave]
        if hecho:
            estado = "hecho"
        elif not hay_actual:
            estado, hay_actual = "actual", True
        else:
            estado = "pendiente"
        pasos.append({"clave": clave, "titulo": titulo, "estado": estado, "detalle": detalle})
    return pasos


def _estrellas(calificacion):
    try:
        return max(0, min(5, int(calificacion)))
    except (TypeError, ValueError):
        return 0


def _ficha(fila):
    ia_decision = fila.get("ia_justificable") or ""
    ia = None
    if ia_decision:
        ia = {
            "decision": ia_decision,
            "texto": TEXTO_DECISION.get(ia_decision, ia_decision),
            "motivo": fila.get("ia_motivo", ""),
            "confianza": fila.get("ia_confianza", ""),
            "evidencia": fila.get("ia_evidencia", ""),
        }
    justificable = fila.get("justificable") or ""
    return {
        "row_id": fila.get("row_id"),
        "agente": fila.get("agente", ""),
        "estrellas": _estrellas(fila.get("calificacion")),
        "fecha": fila.get("fecha_registrada", ""),
        "comentario": fila.get("comentario", ""),
        "conversation_id": fila.get("conversation_id") or None,
        "enlace": fila.get("enlace_conversacion", ""),
        "ia": ia,
        "justificable": justificable,
        "decision_texto": TEXTO_DECISION.get(justificable, ""),
        "motivo": fila.get("motivo_inconformidad") or fila.get("ia_motivo", ""),
        "nota": fila.get("comentario_auditor", ""),
        "origen_texto": ORIGEN_TEXTO.get(fila.get("origen_decision"), ""),
        "confirmada": bool(justificable),
    }


def construir_fichas(filas):
    negativos = sorted(
        _negativos(filas),
        key=lambda f: (bool(f.get("justificable")), f.get("fecha_iso") or ""),
    )
    return [_ficha(f) for f in negativos]


def contar_pestanas(filas):
    negativos = _negativos(filas)
    confirmados = sum(1 for f in negativos if f.get("justificable"))
    return {
        "por_confirmar": len(negativos) - confirmados,
        "confirmados": confirmados,
        "todos": len(negativos),
    }


def construir_vista(filas, metricas):
    return {
        "kpis": construir_kpis(metricas),
        "pasos": construir_pasos(filas),
        "fichas": construir_fichas(filas),
        "pestanas": contar_pestanas(filas),
    }
