"""Catálogo único de herramientas: alimenta la navegación y el panel principal."""

HERRAMIENTAS = [
    {
        "endpoint": "usuarios_activos.index",
        "prefijo": None,
        "grupo": "Monitoreo",
        "titulo": "Usuarios activos",
        "icono": "actividad",
        "descripcion": "Estado consolidado de cada sistema: activos, en ejecución y alertas en un solo tablero.",
        "destacada": True,
    },
    {
        "endpoint": "reporte_agentes.reporte_agentes",
        "prefijo": None,
        "grupo": "Reportes",
        "titulo": "Reporte de agentes",
        "icono": "reporte",
        "descripcion": "Reporte diario desde Chatwoot o CSV con resumen por turno y ranking de agentes.",
        "destacada": True,
    },
    {
        "endpoint": "informe_semanal_cs.informe_semanal_cs",
        "prefijo": None,
        "grupo": "Reportes",
        "titulo": "Informe Semanal CS",
        "icono": "documento",
        "descripcion": "Une la bitácora y el contexto de la semana y genera un informe editable.",
        "destacada": False,
    },
    {
        "endpoint": "auditoria_csat.auditoria_csat",
        "prefijo": None,
        "grupo": "Calidad",
        "titulo": "Auditoría CSAT",
        "icono": "calidad",
        "descripcion": "Revisa cada valoración, marca justificaciones y exporta el CSV auditado.",
        "destacada": False,
    },
    {
        "endpoint": "auditoria_salientes.auditoria_salientes",
        "prefijo": None,
        "grupo": "Calidad",
        "titulo": "Auditoría de salientes",
        "icono": "llamada",
        "descripcion": "Agrupa llamadas por caso y valida el cumplimiento por agente y turno.",
        "destacada": False,
    },
    {
        "endpoint": "comparar_csv.comparar_csv",
        "prefijo": None,
        "grupo": "Datos",
        "titulo": "Comparar CSV",
        "icono": "comparar",
        "descripcion": "Compara dos reportes y muestra variaciones por turno y por agente.",
        "destacada": False,
    },
    {
        "endpoint": "usuarios_a_sheets.usuarios_a_sheets",
        "prefijo": None,
        "grupo": "Datos",
        "titulo": "Usuarios a Sheets",
        "icono": "tabla",
        "descripcion": "Limpia una lista de usuarios y la descarga o la crea como Google Sheet.",
        "destacada": False,
    },
    {
        "endpoint": "turnos_trabajo.turnos_trabajo",
        "prefijo": "turnos_trabajo.",
        "grupo": "Equipo",
        "titulo": "Turnos de trabajo",
        "icono": "equipo",
        "descripcion": "Integrantes por turno: importa agentes, muévelos y revisa el historial.",
        "destacada": False,
    },
    {
        "endpoint": "break_admin.break_admin",
        "prefijo": None,
        "grupo": "Equipo",
        "titulo": "Breaks reservables",
        "icono": "reloj",
        "descripcion": "Turnos, horarios, cupos y reservas de breaks compartidos con los agentes.",
        "destacada": False,
    },
]

ORDEN_GRUPOS = ["Monitoreo", "Reportes", "Calidad", "Datos", "Equipo"]


def grupos_de_navegacion():
    """Herramientas agrupadas en el orden de la navegación."""
    return [
        {"nombre": grupo, "items": [h for h in HERRAMIENTAS if h["grupo"] == grupo]}
        for grupo in ORDEN_GRUPOS
    ]


def herramienta_activa(endpoint):
    endpoint = endpoint or ""
    for herramienta in HERRAMIENTAS:
        if endpoint == herramienta["endpoint"]:
            return herramienta
        if herramienta["prefijo"] and endpoint.startswith(herramienta["prefijo"]):
            return herramienta
    return None
