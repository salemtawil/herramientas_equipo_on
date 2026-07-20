import requests

ENDPOINT_MULTIADMIN = "https://pti24ew7fbrhm55ftbbbc5hk6i0meyek.lambda-url.us-east-1.on.aws/"
COMPINCHE_ADMIN_OFFSET = 44
KNOWN_SYSTEM_KEYS = {
    "compinche",
    "paripe",
    "camarada",
    "complice",
    "secuaz",
    "ready4drive",
}


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _restar_admins_compinche(active_users):
    return max(_to_int(active_users) - COMPINCHE_ADMIN_OFFSET, 0)


def _normalizar_sistema_generico(key, value):
    data = _safe_dict(value)
    return {
        "system": key,
        "display_name": str(key).replace("_", " ").replace("-", " ").title(),
        "active_users": _to_int(data.get("active")),
        "running_users": _to_int(data.get("running")),
    }


def obtener_metricas_multiadmin():
    response = requests.get(ENDPOINT_MULTIADMIN, timeout=30)
    response.raise_for_status()

    data = response.json()
    data = _safe_dict(data)

    compinche = _safe_dict(data.get("compinche"))
    paripe = _safe_dict(data.get("paripe"))
    camarada = _safe_dict(data.get("camarada"))
    complice = _safe_dict(data.get("complice"))
    secuaz = _safe_dict(data.get("secuaz"))
    ready4drive = _safe_dict(data.get("ready4drive"))
    paripe_images_bank = _safe_dict(paripe.get("images-bank"))

    metricas = {
        "Compinche": {
            "active_users": _restar_admins_compinche(compinche.get("active")),
            "running_users": _to_int(compinche.get("running")),
        },
        "Paripe": {
            "good_standing_users": paripe.get("active", 0) or 0,
            "photo_pool": paripe_images_bank.get("items", 0) or 0,
        },
        "camarada": {
            "active_users": camarada.get("active", 0) or 0,
            "running_users": camarada.get("running", 0) or 0,
        },
        "complice": {
            "active_users": complice.get("active", 0) or 0,
            "running_users": complice.get("running", 0) or 0,
        },
        "secuaz": {
            "active_users": secuaz.get("active", 0) or 0,
            "running_users": secuaz.get("running", 0) or 0,
        },
        "ready4drive": {
            "active_users": ready4drive.get("active", 0) or 0,
            "running_users": ready4drive.get("running", 0) or 0,
        },
    }

    for key, value in data.items():
        if key in KNOWN_SYSTEM_KEYS:
            continue
        if not isinstance(value, dict) or ("active" not in value and "running" not in value):
            continue
        sistema = _normalizar_sistema_generico(key, value)
        metricas[key] = sistema

    return metricas


if __name__ == "__main__":
    print(obtener_metricas_multiadmin())
