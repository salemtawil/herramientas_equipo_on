import base64
from datetime import datetime
from datetime import timezone
import getpass
import hashlib
import hmac
import json
import os

import boto3
from botocore import UNSIGNED
from botocore.config import Config
import requests


API_BASE_URL = os.getenv(
    "MULTIADMIN_API_BASE_URL",
    "https://7b9q0ttttb.execute-api.us-east-1.amazonaws.com",
)
CLIENT_ID = os.getenv("MULTIADMIN_CLIENT_ID", "24nnt1psojm5aqotu1ckj9jk9g")
CLIENT_SECRET = os.getenv("MULTIADMIN_CLIENT_SECRET", "")
USER_POOL_ID = os.getenv("MULTIADMIN_USER_POOL_ID", "us-east-1_ViIazRdoA")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
SINCE_EXPIRATION = os.getenv("MULTIADMIN_USERS_SINCE_EXPIRATION", "1746057600000")
OUTPUT_FILE = ".env.vercel.multiadmin.tokens"


def secret_hash(username):
    if not CLIENT_SECRET:
        return None
    digest = hmac.new(
        CLIENT_SECRET.encode("utf-8"),
        f"{username}{CLIENT_ID}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def auth_parameters(username, password):
    params = {
        "USERNAME": username,
        "PASSWORD": password,
    }
    hash_value = secret_hash(username)
    if hash_value:
        params["SECRET_HASH"] = hash_value
    return params


def decode_payload(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))


def expires_at(token):
    payload = decode_payload(token)
    exp = payload.get("exp")
    if not exp:
        return "desconocido"
    return datetime.fromtimestamp(exp, tz=timezone.utc).isoformat()


def login(username, password):
    client = boto3.client(
        "cognito-idp",
        region_name=REGION,
        config=Config(signature_version=UNSIGNED),
    )
    response = client.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters=auth_parameters(username, password),
    )
    return response["AuthenticationResult"]


def request_json(path, id_token):
    url = f"{API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    response = requests.get(
        url,
        headers={
            "accept": "application/json",
            "authorization": f"Bearer {id_token}",
            "origin": "https://admin.camarada.io",
            "referer": "https://admin.camarada.io/",
            "user-agent": "Mozilla/5.0",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def count_items(data):
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("Items", "items", "data", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
    return 0


def write_env(username, auth):
    id_token = auth["IdToken"]
    refresh_token = auth.get("RefreshToken", "")
    access_token = auth.get("AccessToken", "")
    content = f"""# Tokens frescos de Multiadmin para Vercel.
# Archivo local sensible. No subir a Git.
# ID token expira en UTC: {expires_at(id_token)}

MULTIADMIN_API_BASE_URL={API_BASE_URL}
MULTIADMIN_CLIENT_ID={CLIENT_ID}
MULTIADMIN_USER_POOL_ID={USER_POOL_ID}
MULTIADMIN_USERS_SINCE_EXPIRATION={SINCE_EXPIRATION}
AWS_DEFAULT_REGION={REGION}

MULTIADMIN_USERNAME={username}
MULTIADMIN_ID_TOKEN={id_token}
MULTIADMIN_REFRESH_TOKEN={refresh_token}
MULTIADMIN_PROVISIONED_TOKEN=
MULTIADMIN_CLIENT_SECRET={CLIENT_SECRET}

# No es necesario para Vercel en este flujo, pero queda como referencia local.
MULTIADMIN_ACCESS_TOKEN={access_token}
"""
    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        file.write(content)


def main():
    username = input("Telefono o usuario Multiadmin: ").strip()
    password = getpass.getpass("Password Multiadmin: ")
    if not username or not password:
        raise SystemExit("Faltan usuario o password.")

    auth = login(username, password)
    users = request_json(f"/projects/chispita/users?sinceExpiration={SINCE_EXPIRATION}", auth["IdToken"])
    spark = request_json("/projects/chispita/offers/won?period=today&app=spark", auth["IdToken"])
    instacart = request_json("/projects/chispita/offers/won?period=today&app=instacart", auth["IdToken"])
    write_env(username, auth)

    print("Login correcto.")
    print(f"Chispita usuarios recibidos: {count_items(users)}")
    print(f"Ofertas Spark recibidas: {count_items(spark)}")
    print(f"Ofertas Instacart recibidas: {count_items(instacart)}")
    print(f"Archivo generado: {OUTPUT_FILE}")
    print("Copia esas variables a Vercel Production y haz Redeploy.")


if __name__ == "__main__":
    main()
