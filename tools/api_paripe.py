import os
import requests
import boto3

PARIPE_USERS_URL = "https://k91kmrvwdh.execute-api.us-east-1.amazonaws.com/prod/api/admin/users"
PARIPE_IMAGE_BANK_URL = "https://k91kmrvwdh.execute-api.us-east-1.amazonaws.com/prod/api/admin/stats/image-bank"

PARIPE_ID_TOKEN = os.getenv("PARIPE_ID_TOKEN", "")
PARIPE_REFRESH_TOKEN = os.getenv("PARIPE_REFRESH_TOKEN", "")
PARIPE_CLIENT_ID = os.getenv("PARIPE_CLIENT_ID", "")

def refrescar_paripe_token():
    client = boto3.client("cognito-idp", region_name="us-east-1")

    response = client.initiate_auth(
        ClientId=PARIPE_CLIENT_ID,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters={
            "REFRESH_TOKEN": PARIPE_REFRESH_TOKEN
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
        "origin": "https://paripe.io",
        "referer": "https://paripe.io/",
        "user-agent": "Mozilla/5.0"
    }

def _request_json(url, token):
    response = requests.get(url, headers=_headers(token), timeout=30)
    response.raise_for_status()
    return response.json()

def obtener_usuarios_paripe(token):
    data = _request_json(PARIPE_USERS_URL, token)
    return data if isinstance(data, list) else []

def obtener_image_bank_paripe(token):
    data = _request_json(PARIPE_IMAGE_BANK_URL, token)
    return data if isinstance(data, dict) else {}

def obtener_metricas_paripe_api():
    token = PARIPE_ID_TOKEN

    try:
        usuarios = obtener_usuarios_paripe(token)
        image_bank = obtener_image_bank_paripe(token)
    except Exception:
        nuevos = refrescar_paripe_token()
        token = nuevos["id_token"]
        usuarios = obtener_usuarios_paripe(token)
        image_bank = obtener_image_bank_paripe(token)

    good_standing_users = sum(
        1 for user in usuarios
        if isinstance(user, dict) and bool(user.get("goodStanding"))
    )

    photo_pool = 0
    items = image_bank.get("items", [])
    if items and isinstance(items[0], dict):
        photo_pool = items[0].get("items", 0) or 0

    return {
        "good_standing_users": good_standing_users,
        "photo_pool": photo_pool
    }

if __name__ == "__main__":
    print(obtener_metricas_paripe_api())