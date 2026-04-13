from datetime import datetime

from tools.api_compinche import obtener_metricas_compinche_api
from tools.api_paripe import obtener_metricas_paripe_api
from tools.api_multiadmin import obtener_metricas_multiadmin


def _estado_base():
    return {
        "Compinche": {
            "system": "Compinche",
            "active_users": 0,
            "running_users": 0,
            "updated_at": "-",
            "progress": "Pendiente",
            "error": None,
        },
        "Paripe": {
            "system": "Paripe",
            "good_standing_users": 0,
            "photo_pool": 0,
            "updated_at": "-",
            "progress": "Pendiente",
            "error": None,
        },
        "camarada": {
            "system": "camarada",
            "active_users": 0,
            "running_users": 0,
            "updated_at": "-",
            "progress": "Pendiente",
            "error": None,
        },
        "complice": {
            "system": "complice",
            "active_users": 0,
            "running_users": 0,
            "updated_at": "-",
            "progress": "Pendiente",
            "error": None,
        },
        "secuaz": {
            "system": "secuaz",
            "active_users": 0,
            "running_users": 0,
            "updated_at": "-",
            "progress": "Pendiente",
            "error": None,
        },
        "ready4drive": {
            "system": "ready4drive",
            "active_users": 0,
            "running_users": 0,
            "updated_at": "-",
            "progress": "Pendiente",
            "error": None,
        },
    }


def _actualizar_estado(estado, system, **kwargs):
    estado[system].update(kwargs)


def _proceso_compinche(estado):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        metricas = obtener_metricas_compinche_api()
        _actualizar_estado(
            estado,
            "Compinche",
            active_users=metricas.get("active_users", 0),
            running_users=metricas.get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )
    except Exception as e:
        _actualizar_estado(
            estado,
            "Compinche",
            updated_at=ahora,
            progress="Error",
            error=str(e),
        )


def _proceso_paripe(estado):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        metricas = obtener_metricas_paripe_api()
        _actualizar_estado(
            estado,
            "Paripe",
            good_standing_users=metricas.get("good_standing_users", 0),
            photo_pool=metricas.get("photo_pool", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )
    except Exception as e:
        _actualizar_estado(
            estado,
            "Paripe",
            updated_at=ahora,
            progress="Error",
            error=str(e),
        )


def _proceso_multiadmin(estado):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        metricas = obtener_metricas_multiadmin()

        _actualizar_estado(
            estado,
            "camarada",
            active_users=metricas.get("camarada", {}).get("activeUsers", 0),
            running_users=metricas.get("camarada", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "complice",
            active_users=metricas.get("complice", {}).get("activeUsers", 0),
            running_users=metricas.get("complice", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "secuaz",
            active_users=metricas.get("secuaz", {}).get("activeUsers", 0),
            running_users=metricas.get("secuaz", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "ready4drive",
            active_users=metricas.get("ready4drive", {}).get("activeUsers", 0),
            running_users=metricas.get("ready4drive", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )
    except Exception as e:
        _actualizar_estado(estado, "camarada", updated_at=ahora, progress="Error", error=str(e))
        _actualizar_estado(estado, "complice", updated_at=ahora, progress="Error", error=str(e))
        _actualizar_estado(estado, "secuaz", updated_at=ahora, progress="Error", error=str(e))
        _actualizar_estado(estado, "ready4drive", updated_at=ahora, progress="Error", error=str(e))


def _ejecutar_actualizacion_total():
    estado = _estado_base()
    _proceso_compinche(estado)
    _proceso_paripe(estado)
    _proceso_multiadmin(estado)
    return list(estado.values())


def obtener_estado_actual():
    return _ejecutar_actualizacion_total()


def iniciar_actualizacion():
    return _ejecutar_actualizacion_total()
