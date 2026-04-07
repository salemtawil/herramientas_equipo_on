import os
import requests
import boto3

COMPINCHE_USERS_URL = "https://api.compinche.io/api/flex/v1/all-users-table"
COMPINCHE_ADMINS_URL = "https://api.compinche.io/api/flex/v1/admin"

COMPINCHE_ID_TOKEN = os.getenv("COMPINCHE_ID_TOKEN", "")
COMPINCHE_REFRESH_TOKEN = os.getenv("COMPINCHE_REFRESH_TOKEN", "")
COMPINCHE_CLIENT_ID = os.getenv("COMPINCHE_CLIENT_ID", "")

def refrescar_compinche_token():
    client = boto3.client("cognito-idp", region_name="us-east-1")

    response = client.initiate_auth(
        ClientId=COMPINCHE_CLIENT_ID,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters={
            "REFRESH_TOKEN": COMPINCHE_REFRESH_TOKEN
        }
    )

    auth = response["AuthenticationResult"]
    return {
        "id_token": auth.get("IdToken"),
        "access_token": auth.get("AccessToken")
    }

def _headers(token):
    return {
        "accept": "application/json, text/plain, */*",
        "authorization": token,
        "origin": "https://old.compinche.io",
        "referer": "https://old.compinche.io/",
        "user-agent": "Mozilla/5.0"
    }

def _request_json(url, token):
    response = requests.get(url, headers=_headers(token), timeout=30)
    response.raise_for_status()
    return response.json()

def _extraer_items(data):
    if isinstance(data, dict):
        return data.get("Items", [])
    return []

def obtener_usuarios_compinche(token):
    data = _request_json(COMPINCHE_USERS_URL, token)
    return _extraer_items(data)

def obtener_admins_compinche(token):
    data = _request_json(COMPINCHE_ADMINS_URL, token)
    return data if isinstance(data, list) else []

def obtener_metricas_compinche_api():
    token = COMPINCHE_ID_TOKEN

    try:
        usuarios = obtener_usuarios_compinche(token)
        admins = obtener_admins_compinche(token)
    except Exception:
        nuevos = refrescar_compinche_token()
        token = nuevos["id_token"]
        usuarios = obtener_usuarios_compinche(token)
        admins = obtener_admins_compinche(token)

    admin_phones = {
        admin.get("phoneNumber")
        for admin in admins
        if isinstance(admin, dict) and admin.get("phoneNumber")
    }

    usuarios_filtrados = [
        user for user in usuarios
        if isinstance(user, dict) and user.get("phoneNumber") not in admin_phones
    ]

    active_users = sum(
        1 for user in usuarios_filtrados
        if bool(user.get("goodStanding"))
    )

    running_users = sum(
        1 for user in usuarios_filtrados
        if bool(user.get("goodStanding")) and user.get("status") == "start"
    )

    return {
        "active_users": active_users,
        "running_users": running_users
    }

if __name__ == "__main__":
    print(obtener_metricas_compinche_api())