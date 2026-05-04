import requests

ENDPOINT_MULTIADMIN = "https://pti24ew7fbrhm55ftbbbc5hk6i0meyek.lambda-url.us-east-1.on.aws/"

def obtener_metricas_multiadmin():
    response = requests.get(ENDPOINT_MULTIADMIN, timeout=30)
    response.raise_for_status()

    data = response.json()

    return {
        "Compinche": data.get("shipt", {}),
        "Paripe": data.get("shipt", {}),
        "camarada": data.get("shipt", {}),
        "complice": data.get("veho", {}),
        "secuaz": data.get("zifty", {}),
        "ready4drive": data.get("ready", {}),
    }