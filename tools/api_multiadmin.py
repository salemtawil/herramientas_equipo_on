import requests

ENDPOINT_MULTIADMIN = "https://r80aom36fl.execute-api.us-east-1.amazonaws.com/shared-admin/public/stats"

def obtener_metricas_multiadmin():
    response = requests.get(ENDPOINT_MULTIADMIN, timeout=30)
    response.raise_for_status()

    data = response.json()

    return {
        "camarada": data.get("shipt", {}),
        "complice": data.get("veho", {}),
        "secuaz": data.get("zifty", {}),
        "ready4drive": data.get("ready", {}),
    }