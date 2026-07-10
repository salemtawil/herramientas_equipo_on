import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import re
import time
import requests
import boto3
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import NoCredentialsError

COMPINCHE_USERS_URL = "https://api.compinche.io/api/flex/v1/all-users-table"
COMPINCHE_ADMINS_URL = "https://api.compinche.io/api/flex/v1/admin"
COMPINCHE_BONUS_URL = "https://api.compinche.io/api/flex/v1/admin/bonus"

COMPINCHE_ID_TOKEN = os.getenv("COMPINCHE_ID_TOKEN", "")
COMPINCHE_REFRESH_TOKEN = os.getenv("COMPINCHE_REFRESH_TOKEN", "")
COMPINCHE_CLIENT_ID = os.getenv("COMPINCHE_CLIENT_ID") or "7qg7enbsnlm13pend7aeplivu2"
COMPINCHE_CLIENT_SECRET = os.getenv("COMPINCHE_CLIENT_SECRET", "")
COMPINCHE_USERNAME = os.getenv("COMPINCHE_USERNAME", "") or os.getenv("COMPINCHE_PHONE", "")
COMPINCHE_PASSWORD = os.getenv("COMPINCHE_PASSWORD", "")
COMPINCHE_USER_POOL_ID = os.getenv("COMPINCHE_USER_POOL_ID") or "us-east-1_KRph7TcMm"
COMPINCHE_AWS_REGION = os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
PROMO_FIELD_PATTERN = re.compile(
    r"promo|promoc|promotion|campaign|coupon|discount|offer|deal",
    re.IGNORECASE,
)
_TOKEN_CACHE = {
    "id_token": None,
    "access_token": None,
    "refresh_token": None,
}

def _cliente_cognito(requiere_credenciales=False):
    config = None
    if not requiere_credenciales:
        config = Config(signature_version=UNSIGNED)
    return boto3.client("cognito-idp", region_name=COMPINCHE_AWS_REGION, config=config)

def _secret_hash(username):
    if not COMPINCHE_CLIENT_SECRET:
        return None

    digest = hmac.new(
        COMPINCHE_CLIENT_SECRET.encode("utf-8"),
        f"{username}{COMPINCHE_CLIENT_ID}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")

def _auth_parameters(params):
    username = params.get("USERNAME")
    secret_hash = _secret_hash(username) if username else None
    if secret_hash:
        params["SECRET_HASH"] = secret_hash
    return params

def _guardar_tokens(auth):
    tokens = {
        "id_token": auth.get("IdToken"),
        "access_token": auth.get("AccessToken"),
        "refresh_token": auth.get("RefreshToken"),
    }
    for key, value in tokens.items():
        if value:
            _TOKEN_CACHE[key] = value
    return tokens

def _decodificar_jwt_payload(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8"))
    except Exception:
        return {}

def _obtener_user_pool_id():
    if COMPINCHE_USER_POOL_ID:
        return COMPINCHE_USER_POOL_ID

    payload = _decodificar_jwt_payload(COMPINCHE_ID_TOKEN)
    issuer = payload.get("iss", "")
    if "/" in issuer:
        return issuer.rstrip("/").split("/")[-1]
    return ""

def _token_expirado_o_por_expirar(token, margen_segundos=300):
    payload = _decodificar_jwt_payload(token)
    expira_en = payload.get("exp")
    if not isinstance(expira_en, (int, float)):
        return False
    return expira_en <= time.time() + margen_segundos

def refrescar_compinche_token():
    refresh_token = _TOKEN_CACHE.get("refresh_token") or COMPINCHE_REFRESH_TOKEN

    auth_parameters = {
        "REFRESH_TOKEN": refresh_token,
    }
    if COMPINCHE_USERNAME:
        auth_parameters["USERNAME"] = COMPINCHE_USERNAME

    response = _cliente_cognito().initiate_auth(
        ClientId=COMPINCHE_CLIENT_ID,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters=_auth_parameters(auth_parameters),
    )

    return _guardar_tokens(response["AuthenticationResult"])

def _iniciar_sesion_compinche_client():
    response = _cliente_cognito().initiate_auth(
        ClientId=COMPINCHE_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters=_auth_parameters({
            "USERNAME": COMPINCHE_USERNAME,
            "PASSWORD": COMPINCHE_PASSWORD,
        }),
    )

    return _guardar_tokens(response["AuthenticationResult"])

def _iniciar_sesion_compinche_admin():
    user_pool_id = _obtener_user_pool_id()
    if not user_pool_id:
        raise RuntimeError(
            "Configura COMPINCHE_USER_POOL_ID para usar ADMIN_USER_PASSWORD_AUTH."
        )

    try:
        response = _cliente_cognito(requiere_credenciales=True).admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=COMPINCHE_CLIENT_ID,
            AuthFlow="ADMIN_USER_PASSWORD_AUTH",
            AuthParameters=_auth_parameters({
                "USERNAME": COMPINCHE_USERNAME,
                "PASSWORD": COMPINCHE_PASSWORD,
            }),
        )
    except NoCredentialsError as error:
        raise RuntimeError(
            "Compinche necesita AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY para usar ADMIN_USER_PASSWORD_AUTH."
        ) from error

    return _guardar_tokens(response["AuthenticationResult"])

def iniciar_sesion_compinche():
    if not COMPINCHE_USERNAME or not COMPINCHE_PASSWORD:
        raise RuntimeError(
            "Configura COMPINCHE_USERNAME y COMPINCHE_PASSWORD para renovar tokens vencidos."
        )

    try:
        return _iniciar_sesion_compinche_client()
    except Exception as error:
        if "USER_PASSWORD_AUTH flow not enabled" not in str(error):
            raise
        return _iniciar_sesion_compinche_admin()

def _obtener_token_compinche():
    token = _TOKEN_CACHE.get("id_token") or COMPINCHE_ID_TOKEN
    if token and _token_expirado_o_por_expirar(token):
        try:
            return _renovar_token_compinche()
        except Exception:
            return token
    return token

def _renovar_token_compinche():
    try:
        return refrescar_compinche_token()["id_token"]
    except Exception:
        return iniciar_sesion_compinche()["id_token"]

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

def obtener_bonus_compinche(token):
    return _normalizar_bonus_compinche(_request_json(COMPINCHE_BONUS_URL, token))

def _obtener_data_compinche():
    token = _obtener_token_compinche()

    try:
        usuarios, admins = _obtener_usuarios_y_admins_compinche(token)
    except Exception:
        token = _renovar_token_compinche()
        usuarios, admins = _obtener_usuarios_y_admins_compinche(token)

    return usuarios, admins

def _obtener_usuarios_y_admins_compinche(token):
    with ThreadPoolExecutor(max_workers=2) as executor:
        usuarios_future = executor.submit(obtener_usuarios_compinche, token)
        admins_future = executor.submit(obtener_admins_compinche, token)
        return usuarios_future.result(), admins_future.result()

def _obtener_bonus_stats_compinche():
    token = _obtener_token_compinche()

    try:
        return obtener_bonus_compinche(token)
    except Exception:
        try:
            return obtener_bonus_compinche(_renovar_token_compinche())
        except Exception:
            return None

def _usuarios_sin_admins(usuarios, admins):
    def normalizar_phone(value):
        if value is None:
            return ""
        return re.sub(r"\D", "", str(value))

    admin_phones = {
        normalizar_phone(admin.get("phoneNumber"))
        for admin in admins
        if isinstance(admin, dict) and normalizar_phone(admin.get("phoneNumber"))
    }

    return [
        user for user in usuarios
        if isinstance(user, dict) and normalizar_phone(user.get("phoneNumber")) not in admin_phones
    ]

def _valor_activo(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        limpio = value.strip().lower()
        return limpio not in {"", "0", "false", "no", "none", "null", "-", "n/a"}
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None

def _flatten_campos(data, prefix=""):
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, value
            if isinstance(value, dict):
                yield from _flatten_campos(value, path)
    elif isinstance(data, list):
        for index, value in enumerate(data[:3]):
            path = f"{prefix}[{index}]"
            if isinstance(value, dict):
                yield from _flatten_campos(value, path)

def _campos_promo(user):
    return [
        (path, value)
        for path, value in _flatten_campos(user)
        if PROMO_FIELD_PATTERN.search(path)
    ]

def _usuario_tiene_promo(user):
    standing_type = user.get("standingType")
    if isinstance(standing_type, str) and standing_type.startswith("promo"):
        return True
    return any(_valor_activo(value) for _, value in _campos_promo(user))

def _usuario_good_standing(user):
    value = user.get("goodStanding")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        limpio = value.strip().lower()
        if limpio in {"true", "1", "yes", "si", "sí", "good", "good_standing", "goodstanding", "active", "activo"}:
            return True
        if limpio in {"", "false", "0", "no", "none", "null", "-", "n/a", "bad", "inactive", "inactivo"}:
            return False
    return bool(value)

def _usuario_running(user):
    status = user.get("status")
    return isinstance(status, str) and status.strip().lower() == "start"

def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _normalizar_bonus_compinche(data):
    if not isinstance(data, dict):
        return None

    return {
        "total_gross_revenue": _to_number(data.get("totalGrossRevenue")),
        "goal_for_bonus": _to_number(data.get("goalForBonus")),
        "percentage_completed": _to_number(data.get("percentageCompleted")),
        "generated_at": data.get("generatedAtTimestamp"),
        "next_refresh_at": data.get("nextRefreshTimestamp"),
        "bonus_end_at": data.get("bonusEndTimestamp"),
        "compinche_gross_revenue": _to_number(data.get("compincheGrossRevenue")),
        "paripe_gross_revenue": _to_number(data.get("paripeGrossRevenue")),
        "other_gross_revenue": _to_number(data.get("otherGrossRevenue")),
    }

def obtener_metricas_compinche_api():
    with ThreadPoolExecutor(max_workers=2) as executor:
        data_future = executor.submit(_obtener_data_compinche)
        bonus_future = executor.submit(_obtener_bonus_stats_compinche)
        usuarios, admins = data_future.result()
        bonus_stats = bonus_future.result()

    usuarios_filtrados = _usuarios_sin_admins(usuarios, admins)

    active_users = sum(
        1 for user in usuarios_filtrados
        if _usuario_good_standing(user)
    )

    running_users = sum(
        1 for user in usuarios_filtrados
        if _usuario_good_standing(user) and _usuario_running(user)
    )

    hay_campos_promo = any(
        _campos_promo(user)
        or (
            isinstance(user.get("standingType"), str)
            and user.get("standingType").startswith("promo")
        )
        for user in usuarios_filtrados
    )
    active_by_promo_users = None
    if hay_campos_promo:
        active_by_promo_users = sum(
            1 for user in usuarios_filtrados
            if _usuario_good_standing(user) and _usuario_tiene_promo(user)
        )

    return {
        "active_users": active_users,
        "running_users": running_users,
        "active_by_promo_users": active_by_promo_users,
        "bonus_stats": bonus_stats,
    }

def obtener_diagnostico_promo_compinche():
    usuarios, admins = _obtener_data_compinche()
    usuarios_filtrados = _usuarios_sin_admins(usuarios, admins)
    campos_top_level = sorted({
        key
        for user in usuarios_filtrados
        if isinstance(user, dict)
        for key in user.keys()
    })
    resumen_promo = {}
    standing_type_counts = {}

    for user in usuarios_filtrados:
        is_active = _usuario_good_standing(user)
        standing_type = user.get("standingType")
        if isinstance(standing_type, str):
            item = standing_type_counts.setdefault(
                standing_type,
                {
                    "standingType": standing_type,
                    "usuarios": 0,
                    "usuarios_activos": 0,
                },
            )
            item["usuarios"] += 1
            if is_active:
                item["usuarios_activos"] += 1

        for path, value in _campos_promo(user):
            item = resumen_promo.setdefault(
                path,
                {
                    "campo": path,
                    "apariciones": 0,
                    "valores_activos": 0,
                    "usuarios_activos_con_valor": 0,
                    "tipos": set(),
                },
            )
            item["apariciones"] += 1
            item["tipos"].add(type(value).__name__)
            if _valor_activo(value):
                item["valores_activos"] += 1
                if is_active:
                    item["usuarios_activos_con_valor"] += 1

    campos_promo = []
    for item in resumen_promo.values():
        item["tipos"] = sorted(item["tipos"])
        campos_promo.append(item)

    campos_promo.sort(key=lambda item: item["campo"])

    return {
        "total_usuarios": len(usuarios_filtrados),
        "usuarios_activos": sum(1 for user in usuarios_filtrados if _usuario_good_standing(user)),
        "active_by_promo_users_detectado": sum(
            1 for user in usuarios_filtrados
            if _usuario_good_standing(user) and _usuario_tiene_promo(user)
        ),
        "campos_top_level": campos_top_level,
        "campos_promo_detectados": campos_promo,
        "standing_type_counts": sorted(
            standing_type_counts.values(),
            key=lambda item: item["standingType"],
        ),
        "nota": "No incluye valores de campos, telefonos, nombres, emails ni tokens.",
    }

if __name__ == "__main__":
    print(obtener_metricas_compinche_api())
