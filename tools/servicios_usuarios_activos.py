from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.api_multiadmin import obtener_metricas_multiadmin
from utils.estado_temporal import cargar_json_temporal
from utils.estado_temporal import guardar_json_temporal

EASTERN_TIMEZONE = ZoneInfo("America/New_York")
SNAPSHOT_NAMESPACE = "usuarios_activos"
SNAPSHOT_ID = "latest"


def obtener_timestamp_eastern(formato="%Y-%m-%d %H:%M:%S"):
    return datetime.now(EASTERN_TIMEZONE).strftime(formato)


def _estado_base():
    return {
        "Compinche": {
            "system": "Compinche",
            "active_users": 0,
            "running_users": 0,
            "active_by_promo_users": 0,
            "bonus_stats": None,
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
    ahora = obtener_timestamp_eastern()

    tareas = {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        tareas[executor.submit(obtener_metricas_multiadmin)] = "Multiadmin"

        for future in as_completed(tareas):
            nombre = tareas[future]
            try:
                if nombre == "Multiadmin":
                    _aplicar_metricas_multiadmin(estado, future.result(), ahora)
            except Exception as e:
                if nombre == "Multiadmin":
                    _marcar_error_multiadmin(estado, ahora, str(e))


def _aplicar_metricas_multiadmin(estado, metricas, ahora):
    _actualizar_estado(
        estado,
        "Compinche",
        active_users=metricas.get("Compinche", {}).get("active_users", 0),
        running_users=metricas.get("Compinche", {}).get("running_users", 0),
        active_by_promo_users=metricas.get("Compinche", {}).get("active_by_promo_users", 0),
        bonus_stats=metricas.get("Compinche", {}).get("bonus_stats"),
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


def _marcar_error_multiadmin(estado, ahora, error):
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


def _obtener_updated_at_desde_data(data):
    for item in data:
        updated_at = item.get("updated_at")
        if updated_at and updated_at != "-":
            return updated_at
    return obtener_timestamp_eastern("%H:%M")


def _guardar_snapshot(data):
    snapshot = {
        "data": data,
        "updated_at": _obtener_updated_at_desde_data(data),
        "source": "snapshot",
    }
    guardar_json_temporal(snapshot, namespace=SNAPSHOT_NAMESPACE, state_id=SNAPSHOT_ID)
    return snapshot


def _cargar_snapshot():
    snapshot = cargar_json_temporal(SNAPSHOT_ID, namespace=SNAPSHOT_NAMESPACE)
    if not isinstance(snapshot, dict):
        return None
    if not isinstance(snapshot.get("data"), list):
        return None
    return snapshot


def iniciar_actualizacion_dashboard():
    data = _ejecutar_actualizacion_total()
    return _guardar_snapshot(data)


def obtener_estado_inicial_dashboard():
    snapshot = _cargar_snapshot()
    if snapshot:
        return snapshot

    return {
        "data": list(_estado_base().values()),
        "updated_at": "-",
        "source": "base",
    }


def obtener_estado_actual_con_metadata():
    snapshot = _cargar_snapshot()
    if snapshot:
        return snapshot
    return {
        "data": list(_estado_base().values()),
        "updated_at": "-",
        "source": "base",
    }


def obtener_estado_actual():
    return obtener_estado_actual_con_metadata()["data"]


def iniciar_actualizacion():
    return iniciar_actualizacion_dashboard()["data"]
