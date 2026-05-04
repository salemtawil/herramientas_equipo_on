from datetime import datetime

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


def _proceso_actualizacion_unica(estado):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        metricas = obtener_metricas_multiadmin()

        _actualizar_estado(
            estado,
            "Compinche",
            active_users=metricas.get("Compinche", {}).get("active_users", 0),
            running_users=metricas.get("Compinche", {}).get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "Paripe",
            good_standing_users=metricas.get("Paripe", {}).get("good_standing_users", 0),
            photo_pool=metricas.get("Paripe", {}).get("photo_pool", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "camarada",
            active_users=metricas.get("camarada", {}).get("active_users", 0),
            running_users=metricas.get("camarada", {}).get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "complice",
            active_users=metricas.get("complice", {}).get("active_users", 0),
            running_users=metricas.get("complice", {}).get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "secuaz",
            active_users=metricas.get("secuaz", {}).get("active_users", 0),
            running_users=metricas.get("secuaz", {}).get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

        _actualizar_estado(
            estado,
            "ready4drive",
            active_users=metricas.get("ready4drive", {}).get("active_users", 0),
            running_users=metricas.get("ready4drive", {}).get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None,
        )

    except Exception as e:
        error = str(e)

        _actualizar_estado(estado, "Compinche", updated_at=ahora, progress="Error", error=error)
        _actualizar_estado(estado, "Paripe", updated_at=ahora, progress="Error", error=error)
        _actualizar_estado(estado, "camarada", updated_at=ahora, progress="Error", error=error)
        _actualizar_estado(estado, "complice", updated_at=ahora, progress="Error", error=error)
        _actualizar_estado(estado, "secuaz", updated_at=ahora, progress="Error", error=error)
        _actualizar_estado(estado, "ready4drive", updated_at=ahora, progress="Error", error=error)


def _ejecutar_actualizacion_total():
    estado = _estado_base()
    _proceso_actualizacion_unica(estado)
    return list(estado.values())


def obtener_estado_actual():
    return list(_estado_base().values())


def iniciar_actualizacion():
    return _ejecutar_actualizacion_total()