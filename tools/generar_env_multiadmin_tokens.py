import base64
from datetime import datetime
from datetime import timezone
import getpass
import hashlib
import hmac
import json
import os
import secrets

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import ClientError
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
POOL_NAME = USER_POOL_ID.split("_", 1)[1] if "_" in USER_POOL_ID else USER_POOL_ID

N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA051015"
    "728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64EC"
    "FB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7AB"
    "F5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6BF"
    "12FFA06D98A0864D87602733EC86A64521F2B18177B200CB"
    "BE117577A615D6C770988C0BAD946E208E24FA074E5AB3143"
    "DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF"
)
N = int(N_HEX, 16)
G = 2


def secret_hash(username):
    if not CLIENT_SECRET:
        return None
    digest = hmac.new(
        CLIENT_SECRET.encode("utf-8"),
        f"{username}{CLIENT_ID}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def agregar_secret_hash(params, username):
    hash_value = secret_hash(username)
    if hash_value:
        params["SECRET_HASH"] = hash_value
    return params


def auth_parameters(username, password):
    return agregar_secret_hash(
        {
            "USERNAME": username,
            "PASSWORD": password,
        },
        username,
    )


def hex_hash(hex_value):
    return hashlib.sha256(bytearray.fromhex(hex_value)).hexdigest()


def hex_to_long(hex_value):
    return int(hex_value, 16)


def long_to_hex(value):
    return f"{value:x}"


def pad_hex(value):
    if isinstance(value, int):
        value = long_to_hex(value)
    if len(value) % 2 == 1:
        value = f"0{value}"
    if "89ABCDEFabcdef".find(value[0]) != -1:
        value = f"00{value}"
    return value


def hash_sha256(value):
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def compute_hkdf(ikm, salt):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    info_bits = bytearray("Caldera Derived Key", "utf-8") + bytearray(chr(1), "utf-8")
    return hmac.new(prk, info_bits, hashlib.sha256).digest()[:16]


def cognito_timestamp():
    now = datetime.now(timezone.utc)
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return (
        f"{weekdays[now.weekday()]} {months[now.month - 1]} {now.day} "
        f"{now:%H:%M:%S} UTC {now.year}"
    )


class CognitoSrp:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.a = secrets.randbits(1024) % N
        self.A = pow(G, self.a, N)
        self.k = hex_to_long(hex_hash(pad_hex(N) + pad_hex(G)))

    def get_auth_params(self):
        return agregar_secret_hash(
            {
                "USERNAME": self.username,
                "SRP_A": long_to_hex(self.A),
            },
            self.username,
        )

    def get_password_verifier_params(self, challenge):
        username_for_srp = challenge["USER_ID_FOR_SRP"]
        salt_hex = challenge["SALT"]
        srp_b_hex = challenge["SRP_B"]
        secret_block = base64.b64decode(challenge["SECRET_BLOCK"])

        B = hex_to_long(srp_b_hex)
        if B % N == 0:
            raise RuntimeError("Respuesta SRP invalida: SRP_B modulo N es cero.")

        u = hex_to_long(hex_hash(pad_hex(self.A) + pad_hex(B)))
        if u == 0:
            raise RuntimeError("Respuesta SRP invalida: U es cero.")

        username_password = f"{POOL_NAME}{username_for_srp}:{self.password}"
        username_password_hash = hash_sha256(username_password)
        x = hex_to_long(hex_hash(pad_hex(salt_hex) + username_password_hash))
        g_mod_pow_xn = pow(G, x, N)
        int_value2 = (B - self.k * g_mod_pow_xn) % N
        s_value = pow(int_value2, self.a + u * x, N)
        hkdf = compute_hkdf(
            bytearray.fromhex(pad_hex(s_value)),
            bytearray.fromhex(pad_hex(u)),
        )

        timestamp = cognito_timestamp()
        message = bytearray(POOL_NAME, "utf-8")
        message += bytearray(username_for_srp, "utf-8")
        message += bytearray(secret_block)
        message += bytearray(timestamp, "utf-8")
        signature = base64.b64encode(
            hmac.new(hkdf, message, hashlib.sha256).digest()
        ).decode("utf-8")

        return agregar_secret_hash(
            {
                "USERNAME": username_for_srp,
                "PASSWORD_CLAIM_SECRET_BLOCK": challenge["SECRET_BLOCK"],
                "TIMESTAMP": timestamp,
                "PASSWORD_CLAIM_SIGNATURE": signature,
            },
            username_for_srp,
        )


def challenge_parameters(username, response):
    challenge_name = response.get("ChallengeName")
    cognito_username = response.get("ChallengeParameters", {}).get(
        "USER_ID_FOR_SRP",
        username,
    )

    params = {"USERNAME": cognito_username}
    if challenge_name == "SMS_MFA":
        params["SMS_MFA_CODE"] = input("Codigo SMS Multiadmin: ").strip()
    elif challenge_name == "SOFTWARE_TOKEN_MFA":
        params["SOFTWARE_TOKEN_MFA_CODE"] = input("Codigo MFA Multiadmin: ").strip()
    elif challenge_name == "CUSTOM_CHALLENGE":
        params["ANSWER"] = input("Codigo de verificacion Multiadmin: ").strip()
    else:
        raise RuntimeError(f"Desafio de login no soportado: {challenge_name}")

    return agregar_secret_hash(params, cognito_username)


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
    try:
        response = client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters=auth_parameters(username, password),
        )
        srp = None
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        message = error.response.get("Error", {}).get("Message", "")
        if code != "InvalidParameterException" or "USER_PASSWORD_AUTH" not in message:
            raise

        print("El cliente no permite password directo. Probando login SRP...")
        srp = CognitoSrp(username, password)
        response = client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_SRP_AUTH",
            AuthParameters=srp.get_auth_params(),
        )

    while "ChallengeName" in response:
        challenge_name = response["ChallengeName"]
        if challenge_name == "PASSWORD_VERIFIER":
            if srp is None:
                raise RuntimeError("Cognito pidio PASSWORD_VERIFIER sin flujo SRP activo.")
            challenge_responses = srp.get_password_verifier_params(
                response["ChallengeParameters"]
            )
        else:
            challenge_responses = challenge_parameters(username, response)

        response = client.respond_to_auth_challenge(
            ClientId=CLIENT_ID,
            ChallengeName=challenge_name,
            Session=response["Session"],
            ChallengeResponses=challenge_responses,
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
# El refresh token permite renovar sin iniciar sesion ni pedir SMS.

MULTIADMIN_API_BASE_URL={API_BASE_URL}
MULTIADMIN_CLIENT_ID={CLIENT_ID}
MULTIADMIN_USER_POOL_ID={USER_POOL_ID}
MULTIADMIN_USERS_SINCE_EXPIRATION={SINCE_EXPIRATION}
AWS_DEFAULT_REGION={REGION}

MULTIADMIN_USERNAME={username}
MULTIADMIN_PASSWORD=
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
