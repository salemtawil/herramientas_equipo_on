import requests

ENDPOINT_MULTIADMIN = "https://pti24ew7fbrhm55ftbbbc5hk6i0meyek.lambda-url.us-east-1.on.aws/"


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


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

    return {
        "Compinche": {
            "active_users": compinche.get("active", 0) or 0,
            "running_users": compinche.get("running", 0) or 0,
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


if __name__ == "__main__":
    print(obtener_metricas_multiadmin())