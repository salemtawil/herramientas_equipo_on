"""Pauta de evaluación, mensajes para la IA y validación de su respuesta."""

import json
import unicodedata

PAUTA_VERSION = "1"

CRITERIOS = [
    ("saludo", "Saludo y presentación"),
    ("comprension", "Comprensión del problema"),
    ("exactitud", "Exactitud de la información"),
    ("resolucion", "Resolución"),
    ("tono", "Tono y empatía"),
    ("tiempos", "Tiempos de respuesta"),
    ("cierre", "Cierre"),
]

DESCRIPCIONES = {
    "saludo": "El agente saluda, se presenta y abre la conversación con cordialidad.",
    "comprension": "Entiende lo que pide el cliente, pregunta lo necesario y no lo hace repetir.",
    "exactitud": "La información y los pasos que da son correctos y claros.",
    "resolucion": "Resuelve el problema o deja un siguiente paso concreto.",
    "tono": "Trato respetuoso, empático y profesional durante todo el chat.",
    "tiempos": "Responde sin demoras injustificadas según las horas de los mensajes.",
    "cierre": "Confirma si queda algo pendiente y despide correctamente.",
}

SATISFACCION = ("satisfecho", "neutral", "insatisfecho", "no_se_puede_saber")
RESUELTO = ("si", "no", "parcial")
CONFIANZA = ("alta", "media", "baja")

MAX_EVIDENCIAS = 3


def _esquema_ejemplo():
    return {
        "criterios": {clave: 4 for clave, _ in CRITERIOS},
        "nota_global": 4,
        "satisfaccion_cliente": "|".join(SATISFACCION),
        "resuelto": "|".join(RESUELTO),
        "resumen": "Máximo 2 frases.",
        "fortalezas": ["..."],
        "mejoras": ["..."],
        "evidencias": ["cita literal corta del chat"],
        "confianza": "|".join(CONFIANZA),
    }


def construir_mensajes(transcripcion, agente_nombre):
    lineas_criterios = "\n".join(
        f"- {clave} ({etiqueta}): {DESCRIPCIONES[clave]}" for clave, etiqueta in CRITERIOS
    )
    sistema = (
        f"Eres auditor de calidad de un equipo de soporte al cliente (pauta versión {PAUTA_VERSION}).\n"
        "Evalúas SOLO el desempeño del agente humano en un chat, no al cliente ni al producto.\n"
        "Puntúa cada criterio de 1 (muy mal) a 5 (excelente):\n"
        f"{lineas_criterios}\n"
        "nota_global va de 1 a 5 y resume la atención completa.\n"
        "satisfaccion_cliente: cómo terminó el cliente según sus mensajes; usa no_se_puede_saber si no hay señales.\n"
        "resuelto: si el problema quedó resuelto.\n"
        f"evidencias: hasta {MAX_EVIDENCIAS} citas literales del chat de 20 palabras como máximo que justifiquen la nota.\n"
        "confianza: baja si el chat es muy corto, está incompleto o es ambiguo.\n"
        "Los datos personales aparecen ocultos como [correo], [teléfono] o [número]; no los penalices.\n"
        "Responde en español y SOLO con un objeto JSON con exactamente esta forma:\n"
        f"{json.dumps(_esquema_ejemplo(), ensure_ascii=False)}"
    )
    usuario = f"Agente: {agente_nombre}\n\nTranscripción:\n{transcripcion}"
    return [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]


def _normalizar_clave(valor):
    texto = unicodedata.normalize("NFKD", str(valor or "").strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return "_".join(texto.replace("-", " ").split())


def _nota(valor, campo):
    try:
        numero = int(float(str(valor).strip()))
    except (TypeError, ValueError):
        raise ValueError(f"La IA no dio una nota válida para «{campo}».")
    if not 1 <= numero <= 5:
        raise ValueError(f"La nota de «{campo}» está fuera de 1 a 5 ({numero}).")
    return numero


def _enumerado(valor, opciones, campo):
    clave = _normalizar_clave(valor)
    if clave not in opciones:
        raise ValueError(f"Valor no válido para «{campo}»: {valor!r}.")
    return clave


def _lista_textos(valor):
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return []
    return [str(item).strip() for item in valor if str(item or "").strip()]


def validar_resultado(data):
    if not isinstance(data, dict):
        raise ValueError("La respuesta de la IA no es un objeto.")
    criterios_crudos = data.get("criterios")
    if not isinstance(criterios_crudos, dict):
        raise ValueError("La IA no devolvió los criterios.")

    criterios = {}
    for clave, etiqueta in CRITERIOS:
        if clave not in criterios_crudos:
            raise ValueError(f"Falta el criterio «{etiqueta}».")
        criterios[clave] = _nota(criterios_crudos[clave], etiqueta)

    return {
        "criterios": criterios,
        "nota_global": _nota(data.get("nota_global"), "nota global"),
        "satisfaccion_cliente": _enumerado(data.get("satisfaccion_cliente"), SATISFACCION, "satisfacción"),
        "resuelto": _enumerado(data.get("resuelto"), RESUELTO, "resuelto"),
        "resumen": str(data.get("resumen") or "").strip(),
        "fortalezas": _lista_textos(data.get("fortalezas")),
        "mejoras": _lista_textos(data.get("mejoras")),
        "evidencias": _lista_textos(data.get("evidencias"))[:MAX_EVIDENCIAS],
        "confianza": _enumerado(data.get("confianza"), CONFIANZA, "confianza"),
    }


def requiere_revision(resultado, hubo_error):
    if hubo_error or not resultado:
        return True
    return (
        resultado["nota_global"] <= 3
        or resultado["satisfaccion_cliente"] == "insatisfecho"
        or resultado["confianza"] == "baja"
    )
