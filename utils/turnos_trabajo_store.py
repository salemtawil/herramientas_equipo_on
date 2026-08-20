import csv
import json
import os
import uuid
from datetime import datetime

from utils.config_turnos import obtener_turnos_fijos


LOCAL_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
STORE_FILENAME = "turnos_trabajo.json"
SIN_TURNO_ID = "sin-turno"
SIN_TURNO_LABEL = "Sin turno"


def obtener_store_path():
    configured_path = str(os.getenv("TURNOS_TRABAJO_STORE_PATH") or "").strip()
    if configured_path:
        return configured_path

    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        return os.path.join("/tmp", STORE_FILENAME)

    return os.path.join(LOCAL_DATA_DIR, STORE_FILENAME)


def _ahora_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def normalizar_texto(valor):
    return " ".join(str(valor or "").strip().lower().split())


def nombre_completo(agent):
    nombre = str(agent.get("first_name") or "").strip()
    apellido = str(agent.get("last_name") or "").strip()
    return f"{nombre} {apellido}".strip() or str(agent.get("user_id") or "").strip()


def _slug_turno(nombre):
    base = normalizar_texto(nombre).replace("/", "-").replace(" ", "-")
    return base or f"turno-{uuid.uuid4().hex[:8]}"


def _agent_id_from_name(nombre):
    return f"legacy:{normalizar_texto(nombre)}"


def _nuevo_estado_desde_config():
    turnos = []
    agents = {}
    assignments = {}

    for orden, (nombre_turno, nombres_agentes) in enumerate(obtener_turnos_fijos().items()):
        shift_id = _slug_turno(nombre_turno)
        turnos.append(
            {
                "id": shift_id,
                "name": nombre_turno,
                "order": orden,
                "active": True,
            }
        )

        for nombre in nombres_agentes:
            nombre_limpio = str(nombre or "").strip()
            if not nombre_limpio:
                continue

            agent_id = _agent_id_from_name(nombre_limpio)
            if agent_id not in agents:
                partes = nombre_limpio.split(" ", 1)
                agents[agent_id] = {
                    "user_id": agent_id,
                    "email": "",
                    "first_name": partes[0],
                    "last_name": partes[1] if len(partes) > 1 else "",
                    "role_name": "",
                    "system_name": "",
                    "department_ids": "",
                    "active": True,
                    "source": "config",
                    "created_at": _ahora_iso(),
                    "updated_at": _ahora_iso(),
                }
            assignments[agent_id] = shift_id

    turnos.append(
        {
            "id": SIN_TURNO_ID,
            "name": SIN_TURNO_LABEL,
            "order": len(turnos),
            "active": True,
        }
    )

    return {
        "version": 1,
        "created_at": _ahora_iso(),
        "updated_at": _ahora_iso(),
        "shifts": turnos,
        "agents": agents,
        "assignments": assignments,
        "history": [
            {
                "id": uuid.uuid4().hex,
                "at": _ahora_iso(),
                "action": "bootstrap",
                "detail": "Estado inicial generado desde utils/config_turnos.py",
            }
        ],
    }


def cargar_estado():
    store_path = obtener_store_path()
    if not os.path.exists(store_path):
        estado = _nuevo_estado_desde_config()
        guardar_estado(estado)
        return estado

    with open(store_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def guardar_estado(estado):
    store_path = obtener_store_path()
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    estado["updated_at"] = _ahora_iso()
    with open(store_path, "w", encoding="utf-8") as fh:
        json.dump(estado, fh, ensure_ascii=False, indent=2)


def agregar_historial(estado, action, detail, agent_id=None, before=None, after=None):
    estado.setdefault("history", []).insert(
        0,
        {
            "id": uuid.uuid4().hex,
            "at": _ahora_iso(),
            "action": action,
            "detail": detail,
            "agent_id": agent_id,
            "before": before,
            "after": after,
        },
    )


def obtener_turnos_ordenados(estado):
    return sorted(estado.get("shifts", []), key=lambda item: (item.get("order", 999), item.get("name", "")))


def obtener_agentes_ordenados(estado):
    agents = list(estado.get("agents", {}).values())
    return sorted(agents, key=lambda item: normalizar_texto(nombre_completo(item)))


def construir_tablero(estado):
    turnos = obtener_turnos_ordenados(estado)
    agents = estado.get("agents", {})
    assignments = estado.get("assignments", {})
    tablero = []

    for turno in turnos:
        filas = []
        for agent_id, agent in agents.items():
            if assignments.get(agent_id, SIN_TURNO_ID) == turno["id"]:
                filas.append({**agent, "display_name": nombre_completo(agent)})

        tablero.append(
            {
                **turno,
                "agents": sorted(filas, key=lambda item: normalizar_texto(item["display_name"])),
            }
        )

    return tablero


def mover_agente(agent_id, shift_id):
    estado = cargar_estado()
    agents = estado.get("agents", {})
    shifts = {shift["id"]: shift for shift in estado.get("shifts", [])}

    if agent_id not in agents:
        raise ValueError("El agente indicado no existe.")
    if shift_id not in shifts:
        raise ValueError("El turno indicado no existe.")

    antes = estado.setdefault("assignments", {}).get(agent_id, SIN_TURNO_ID)
    estado["assignments"][agent_id] = shift_id

    agents[agent_id]["active"] = True
    agents[agent_id]["updated_at"] = _ahora_iso()
    agregar_historial(
        estado,
        "move_agent",
        f"{nombre_completo(agents[agent_id])} movido a {shifts[shift_id]['name']}.",
        agent_id=agent_id,
        before=antes,
        after=shift_id,
    )
    guardar_estado(estado)


def set_agente_activo(agent_id, active):
    estado = cargar_estado()
    agents = estado.get("agents", {})
    if agent_id not in agents:
        raise ValueError("El agente indicado no existe.")

    agents[agent_id]["active"] = bool(active)
    agents[agent_id]["updated_at"] = _ahora_iso()
    agregar_historial(
        estado,
        "activate_agent" if active else "deactivate_agent",
        f"{nombre_completo(agents[agent_id])} {'reactivado' if active else 'desactivado'}.",
        agent_id=agent_id,
        after=bool(active),
    )
    guardar_estado(estado)


def _leer_agents_csv(file_storage):
    contenido = file_storage.read()
    if hasattr(file_storage, "seek"):
        file_storage.seek(0)

    texto = contenido.decode("utf-8-sig")
    return list(csv.DictReader(texto.splitlines()))


def importar_agents_csv(file_storage):
    filas = _leer_agents_csv(file_storage)
    estado = cargar_estado()
    agents = estado.setdefault("agents", {})
    assignments = estado.setdefault("assignments", {})

    nuevos = []
    actualizados = []
    vinculados = []
    sin_user_id = []

    def nombre_desde_fila(fila):
        return f"{str(fila.get('First Name') or '').strip()} {str(fila.get('Last Name') or '').strip()}".strip()

    def construir_indice_legacy():
        por_nombre = {}
        por_primer_nombre = {}
        for agent_id, agent in agents.items():
            if not str(agent_id).startswith("legacy:"):
                continue

            display_name = nombre_completo(agent)
            nombre_norm = normalizar_texto(display_name)
            primer_nombre = normalizar_texto(display_name.split(" ", 1)[0])
            if nombre_norm:
                por_nombre[nombre_norm] = agent_id
            if primer_nombre:
                por_primer_nombre.setdefault(primer_nombre, agent_id)
        return por_nombre, por_primer_nombre

    for fila in filas:
        user_id = str(fila.get("User ID") or "").strip()
        if not user_id:
            sin_user_id.append(fila)
            continue

        payload = {
            "user_id": user_id,
            "email": str(fila.get("Email") or "").strip(),
            "first_name": str(fila.get("First Name") or "").strip(),
            "last_name": str(fila.get("Last Name") or "").strip(),
            "role_name": str(fila.get("Role Name") or "").strip(),
            "system_name": str(fila.get("System Name") or "").strip(),
            "department_ids": str(fila.get("Department IDs") or "").strip(),
            "active": True,
            "source": "agents_csv",
            "updated_at": _ahora_iso(),
        }

        if user_id in agents:
            agents[user_id].update(payload)
            actualizados.append(user_id)
        else:
            por_nombre, por_primer_nombre = construir_indice_legacy()
            nombre_norm = normalizar_texto(nombre_desde_fila(fila))
            primer_nombre = normalizar_texto(str(fila.get("First Name") or "").strip())
            legacy_id = por_nombre.get(nombre_norm) or por_primer_nombre.get(primer_nombre)

            if legacy_id and legacy_id in agents:
                anterior = agents.pop(legacy_id)
                payload["created_at"] = anterior.get("created_at") or _ahora_iso()
                agents[user_id] = payload
                assignments[user_id] = assignments.pop(legacy_id, SIN_TURNO_ID)
                vinculados.append(user_id)
            else:
                payload["created_at"] = _ahora_iso()
                agents[user_id] = payload
                assignments[user_id] = SIN_TURNO_ID
                nuevos.append(user_id)

    agregar_historial(
        estado,
        "import_agents_csv",
        (
            f"CSV importado: {len(nuevos)} nuevos, {len(vinculados)} vinculados, "
            f"{len(actualizados)} actualizados, {len(sin_user_id)} sin User ID."
        ),
        after={
            "new": len(nuevos),
            "linked": len(vinculados),
            "updated": len(actualizados),
            "missing_user_id": len(sin_user_id),
        },
    )
    guardar_estado(estado)

    return {
        "filas": len(filas),
        "nuevos": len(nuevos),
        "vinculados": len(vinculados),
        "actualizados": len(actualizados),
        "sin_user_id": len(sin_user_id),
    }
