# =========================================
# CONFIGURACION MANUAL DEL RANKING
# EDITA SOLO ESTA SECCION CUANDO NECESITES
# CAMBIAR LA VALORACION POR TURNO
# =========================================

# IMPORTANTE:
# - Los valores positivos suman puntos.
# - "perdidas" resta puntos directamente.
# - Puedes usar valores distintos por turno.
# - Si un turno no aparece aqui, se usa "default".

CONFIG_RANKING_TURNOS = {
    "default": {
        "llamadas": 0.30,
        "salientes": 0.20,
        "mins_llamadas": 0.20,
        "mins_salientes": 0.15,
        "perdidas": 0.25,
    },
    "Madrugada": {
        "llamadas": 0.20,
        "salientes": 0.15,
        "mins_llamadas": 0.30,
        "mins_salientes": 0.20,
        "perdidas": 0.35,
    },
    "Media noche": {
        "llamadas": 0.20,
        "salientes": 0.10,
        "mins_llamadas": 0.35,
        "mins_salientes": 0.20,
        "perdidas": 0.35,
    },
    "Oficina": {
        "llamadas": 0.30,
        "salientes": 0.20,
        "mins_llamadas": 0.20,
        "mins_salientes": 0.15,
        "perdidas": 0.25,
    },
    "Tarde/Noche": {
        "llamadas": 0.30,
        "salientes": 0.20,
        "mins_llamadas": 0.20,
        "mins_salientes": 0.15,
        "perdidas": 0.25,
    },
    "Ventas": {
        "llamadas": 0.25,
        "salientes": 0.30,
        "mins_llamadas": 0.15,
        "mins_salientes": 0.20,
        "perdidas": 0.25,
    },
    "Shift Leaders": {
        "llamadas": 0.20,
        "salientes": 0.15,
        "mins_llamadas": 0.20,
        "mins_salientes": 0.15,
        "perdidas": 0.30,
    },
    "Sin asignar": {
        "llamadas": 0.30,
        "salientes": 0.20,
        "mins_llamadas": 0.20,
        "mins_salientes": 0.15,
        "perdidas": 0.25,
    },
}


def obtener_config_ranking_turnos():
    return CONFIG_RANKING_TURNOS


def obtener_pesos_turno(turno):
    config = CONFIG_RANKING_TURNOS
    return config.get(turno, config["default"])