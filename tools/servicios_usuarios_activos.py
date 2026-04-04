from datetime import datetime
from threading import Thread, Lock
from concurrent.futures import ThreadPoolExecutor

from tools.api_compinche import obtener_metricas_compinche_api
from tools.api_paripe import obtener_metricas_paripe_api
from tools.api_multiadmin import obtener_metricas_multiadmin

estado_lock = Lock()

estado_actual = {
    "Compinche": {
        "system": "Compinche",
        "active_users": 0,
        "running_users": 0,
        "updated_at": "-",
        "progress": "Pendiente",
        "error": None
    },
    "Paripe": {
        "system": "Paripe",
        "good_standing_users": 0,
        "photo_pool": 0,
        "updated_at": "-",
        "progress": "Pendiente",
        "error": None
    },
    "camarada": {
        "system": "camarada",
        "active_users": 0,
        "running_users": 0,
        "updated_at": "-",
        "progress": "Pendiente",
        "error": None
    },
    "complice": {
        "system": "complice",
        "active_users": 0,
        "running_users": 0,
        "updated_at": "-",
        "progress": "Pendiente",
        "error": None
    },
    "secuaz": {
        "system": "secuaz",
        "active_users": 0,
        "running_users": 0,
        "updated_at": "-",
        "progress": "Pendiente",
        "error": None
    },
    "ready4drive": {
        "system": "ready4drive",
        "active_users": 0,
        "running_users": 0,
        "updated_at": "-",
        "progress": "Pendiente",
        "error": None
    }
}

def actualizar_estado(system, **kwargs):
    with estado_lock:
        if system not in estado_actual:
            estado_actual[system] = {"system": system}
        estado_actual[system].update(kwargs)

def obtener_estado_actual():
    with estado_lock:
        return list(estado_actual.values())

def proceso_compinche():
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        actualizar_estado("Compinche", progress="Consultando API interna...", error=None)

        metricas = obtener_metricas_compinche_api()

        actualizar_estado(
            "Compinche",
            active_users=metricas.get("active_users", 0),
            running_users=metricas.get("running_users", 0),
            updated_at=ahora,
            progress="Completado",
            error=None
        )

    except Exception as e:
        actualizar_estado(
            "Compinche",
            updated_at=ahora,
            progress="Error",
            error=str(e)
        )

def proceso_paripe():
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        actualizar_estado("Paripe", progress="Consultando API interna...", error=None)

        metricas = obtener_metricas_paripe_api()

        actualizar_estado(
            "Paripe",
            good_standing_users=metricas.get("good_standing_users", 0),
            photo_pool=metricas.get("photo_pool", 0),
            updated_at=ahora,
            progress="Completado",
            error=None
        )

    except Exception as e:
        actualizar_estado(
            "Paripe",
            updated_at=ahora,
            progress="Error",
            error=str(e)
        )

def proceso_multiadmin():
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        actualizar_estado("camarada", progress="Consultando API...", error=None)
        actualizar_estado("complice", progress="Consultando API...", error=None)
        actualizar_estado("secuaz", progress="Consultando API...", error=None)
        actualizar_estado("ready4drive", progress="Consultando API...", error=None)

        metricas = obtener_metricas_multiadmin()

        actualizar_estado(
            "camarada",
            active_users=metricas.get("camarada", {}).get("activeUsers", 0),
            running_users=metricas.get("camarada", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None
        )

        actualizar_estado(
            "complice",
            active_users=metricas.get("complice", {}).get("activeUsers", 0),
            running_users=metricas.get("complice", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None
        )

        actualizar_estado(
            "secuaz",
            active_users=metricas.get("secuaz", {}).get("activeUsers", 0),
            running_users=metricas.get("secuaz", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None
        )

        actualizar_estado(
            "ready4drive",
            active_users=metricas.get("ready4drive", {}).get("activeUsers", 0),
            running_users=metricas.get("ready4drive", {}).get("runningUsers", 0),
            updated_at=ahora,
            progress="Completado",
            error=None
        )

    except Exception as e:
        actualizar_estado("camarada", updated_at=ahora, progress="Error", error=str(e))
        actualizar_estado("complice", updated_at=ahora, progress="Error", error=str(e))
        actualizar_estado("secuaz", updated_at=ahora, progress="Error", error=str(e))
        actualizar_estado("ready4drive", updated_at=ahora, progress="Error", error=str(e))

def ejecutar_actualizacion_total():
    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.submit(proceso_compinche)
        executor.submit(proceso_paripe)
        executor.submit(proceso_multiadmin)

def iniciar_actualizacion():
    actualizar_estado("Compinche", progress="Iniciando actualizacion...", error=None)
    actualizar_estado("Paripe", progress="Iniciando actualizacion...", error=None)
    actualizar_estado("camarada", progress="Iniciando actualizacion...", error=None)
    actualizar_estado("complice", progress="Iniciando actualizacion...", error=None)
    actualizar_estado("secuaz", progress="Iniciando actualizacion...", error=None)
    actualizar_estado("ready4drive", progress="Iniciando actualizacion...", error=None)

    hilo = Thread(target=ejecutar_actualizacion_total, daemon=True)
    hilo.start()