import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import hmac
import json
import os
import time

import boto3
from botocore import UNSIGNED
from botocore.config import Config
import requests


ENDPOINT_MULTIADMIN = "https://pti24ew7fbrhm55ftbbbc5hk6i0meyek.lambda-url.us-east-1.on.aws/"
MULTIADMIN_API_BASE_URL = (
    os.getenv("MULTIADMIN_API_BASE_URL")
    or "https://7b9q0ttttb.execute-api.us-east-1.amazonaws.com"
)
MULTIADMIN_ID_TOKEN = os.getenv("MULTIADMIN_ID_TOKEN", "")
MULTIADMIN_REFRESH_TOKEN = os.getenv("MULTIADMIN_REFRESH_TOKEN", "")
MULTIADMIN_PROVISIONED_TOKEN = os.getenv("MULTIADMIN_PROVISIONED_TOKEN", "")
MULTIADMIN_CLIENT_ID = os.getenv("MULTIADMIN_CLIENT_ID") or "24nnt1psojm5aqotu1ckj9jk9g"
MULTIADMIN_CLIENT_SECRET = os.getenv("MULTIADMIN_CLIENT_SECRET", "")
MULTIADMIN_USERNAME = os.getenv("MULTIADMIN_USERNAME", "") or os.getenv("MULTIADMIN_PHONE", "")
MULTIADMIN_PASSWORD = os.getenv("MULTIADMIN_PASSWORD", "")
MULTIADMIN_USER_POOL_ID = os.getenv("MULTIADMIN_USER_POOL_ID") or "us-east-1_ViIazRdoA"
MULTIADMIN_AWS_REGION = os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
MULTIADMIN_USERS_SINCE_EXPIRATION = int(
    os.getenv("MULTIADMIN_USERS_SINCE_EXPIRATION") or "1746057600000"
)
COMPINCHE_ADMIN_OFFSET = 44

KNOWN_SYSTEM_KEYS = {
    "compinche",
    "paripe",
    "camarada",
    "complice",
    "secuaz",
    "ready4drive",
    "chispita",
}

DIRECT_SYSTEMS = {
    "Compinche": {
        "api_key": "compinche",
        "endpoint_key": "compinche",
        "items_key": "Items",
        "exclude_admins": True,
    },
    "Paripe": {
        "api_key": "paripe",
        "endpoint_key": "paripe",
        "items_key": "Items",
    },
    "ready4drive": {
        "api_key": "ready4drive",
        "endpoint_key": "ready4drive",
        "items_key": "Items",
    },
    "complice": {
        "api_key": "veho",
        "endpoint_key": "complice",
        "items_key": "items",
    },
    "camarada": {
        "api_key": "shipt",
        "endpoint_key": "camarada",
        "items_key": "Items",
    },
    "secuaz": {
        "api_key": "zifty",
        "endpoint_key": "secuaz",
        "items_key": "Items",
    },
    "chispita": {
        "api_key": "chispita",
        "endpoint_key": "chispita",
        "items_key": "Items",
    },
}

_TOKEN_CACHE = {
    "id_token": None,
    "access_token": None,
    "refresh_token": None,
}


def _safe_dict(value):
    return value if isinstance(value, dict) else {}


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _restar_admins_compinche(active_users):
    return max(_to_int(active_users) - COMPINCHE_ADMIN_OFFSET, 0)


def _valor_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "si", "sí", "active", "activo"}
    return bool(value)


def _normalizar_timestamp(value):
    if isinstance(value, (int, float)):
        return value if value > 1000000000000 else value * 1000
    if isinstance(value, str):
        texto = value.strip()
        if not texto:
            return None
        if texto.isdigit():
            numero = int(texto)
            return numero if numero > 1000000000000 else numero * 1000
        try:
            fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
            return fecha.timestamp() * 1000
        except ValueError:
            return None
    return None


def _es_hoy(timestamp_ms):
    timestamp_ms = _normalizar_timestamp(timestamp_ms)
    if timestamp_ms is None:
        return False

    fecha = time.localtime(timestamp_ms / 1000)
    hoy = time.localtime()
    return (
        fecha.tm_year == hoy.tm_year
        and fecha.tm_mon == hoy.tm_mon
        and fecha.tm_mday == hoy.tm_mday
    )


def _usuario_good_standing(user):
    return _valor_bool(user.get("goodStanding"))


def _usuario_running(user):
    status = user.get("status")
    return isinstance(status, str) and status.strip().lower() == "start"


def _usuario_admin(user):
    return _valor_bool(user.get("isAdmin"))


def _usuario_tiene_promo(user):
    standing_type = user.get("standingType")
    return isinstance(standing_type, str) and standing_type.strip().lower().startswith("promo")


def _usuario_creado_hoy(user):
    return _es_hoy(
        user.get("createdAt")
        or user.get("createDateTimestamp")
        or user.get("timestamp")
    )


def _flatten_campos(data, prefix=""):
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, value
            if isinstance(value, (dict, list)):
                yield from _flatten_campos(value, path)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{prefix}[{index}]"
            yield path, value
            if isinstance(value, (dict, list)):
                yield from _flatten_campos(value, path)


def _campo_indica_plataforma(path, value, plataforma):
    plataforma = plataforma.lower()
    path_lower = str(path).lower()

    if plataforma in path_lower:
        if isinstance(value, (dict, list)):
            return bool(value)
        return _valor_bool(value)

    if isinstance(value, str):
        return plataforma in value.strip().lower()
    return False


def _usuario_chispita_plataforma(user, plataforma):
    return any(
        _campo_indica_plataforma(path, value, plataforma)
        for path, value in _flatten_campos(user)
    )


def _chispita_service_billing(user, service):
    services = user.get("services")
    if not isinstance(services, dict):
        return {}
    service_data = services.get(service)
    if not isinstance(service_data, dict):
        return {}
    billing = service_data.get("billing")
    return billing if isinstance(billing, dict) else {}


def _usuario_chispita_instacart_activo(user):
    if not _valor_bool(user.get("icEnrolled")):
        return False
    billing = _chispita_service_billing(user, "instacart")
    return _valor_bool(billing.get("goodStanding"))


def _chispita_status_fresco(timestamp_ms, ahora_ms=None):
    timestamp_ms = _normalizar_timestamp(timestamp_ms)
    if timestamp_ms is None:
        return False
    ahora_ms = ahora_ms or int(time.time() * 1000)
    return timestamp_ms <= ahora_ms + 60000 and ahora_ms - timestamp_ms <= 180000


def _usuario_chispita_reportado(user):
    return bool(
        user.get("statusLastTimestampUpdate")
        or user.get("dexVersion")
        or user.get("searchState")
        or user.get("lastSuccessfulPollAt")
    )


def _usuario_chispita_running(user, ahora_ms=None):
    if not _usuario_good_standing(user) or not _usuario_chispita_reportado(user):
        return False

    status = str(user.get("status") or "").strip().lower()
    search_state = str(user.get("searchState") or "").strip().upper()
    status_fresco = _chispita_status_fresco(user.get("statusLastTimestampUpdate"), ahora_ms)
    poll_fresco = _chispita_status_fresco(user.get("lastSuccessfulPollAt"), ahora_ms)

    if not status_fresco:
        return False
    if status in {"start", "active", "running"} and _valor_bool(user.get("isActive", True)):
        return search_state not in {
            "PAUSED_CAPTCHA",
            "PAUSED_BACKOFF",
            "PAUSED_FILTERS",
            "PAUSED_ACCOUNT",
            "PAUSED_SPARK_NOW",
            "PAUSED_ACTIVE_TRIP",
        }
    if status == "stop" and search_state == "PAUSED_ACTIVE_TRIP":
        return True
    if status == "stop" and (
        search_state in {"SEARCHING", "POLLING"}
        or _valor_bool(user.get("pollingEnabled"))
        or poll_fresco
    ):
        return False
    return False


def _estado_chispita_spark(user):
    return {
        "entitled": _usuario_good_standing(user),
        "running": _usuario_chispita_running(user),
    }


def _estado_chispita_instacart(user):
    if not _valor_bool(user.get("icEnrolled")):
        return None
    billing = _chispita_service_billing(user, "instacart")
    return {
        "entitled": _valor_bool(billing.get("goodStanding")),
        "running": str(user.get("icStatus") or "").strip().lower() == "start",
    }


def _estados_chispita_usuario(user, app):
    if app == "spark":
        return [_estado_chispita_spark(user)]
    if app == "instacart":
        estado = _estado_chispita_instacart(user)
        return [estado] if estado else []
    estados = [_estado_chispita_spark(user)]
    estado_instacart = _estado_chispita_instacart(user)
    if estado_instacart:
        estados.append(estado_instacart)
    return estados


def _metricas_chispita_app(usuarios, app):
    active_users = 0
    running_users = 0
    disconnected_users = 0
    new_users = 0

    for user in usuarios:
        if not isinstance(user, dict):
            continue
        estados = _estados_chispita_usuario(user, app)
        if not estados:
            continue
        activos = [estado for estado in estados if estado["entitled"]]
        if activos:
            active_users += 1
            if any(estado["running"] for estado in activos):
                running_users += 1
        else:
            disconnected_users += 1
        if _usuario_creado_hoy(user):
            new_users += 1

    return {
        "active_users": active_users,
        "running_users": running_users,
        "new_users": new_users,
        "disconnected_users": disconnected_users,
    }


def _metricas_chispita_por_plataforma(usuarios):
    all_stats = _metricas_chispita_app(usuarios, "all")
    spark_stats = _metricas_chispita_app(usuarios, "spark")
    instacart_stats = _metricas_chispita_app(usuarios, "instacart")
    return {
        "active_users": all_stats["active_users"],
        "running_users": all_stats["running_users"],
        "new_users": all_stats["new_users"],
        "disconnected_users": all_stats["disconnected_users"],
        "spark_users": spark_stats["active_users"],
        "spark_running_users": spark_stats["running_users"],
        "spark_new_users": spark_stats["new_users"],
        "spark_disconnected_users": spark_stats["disconnected_users"],
        "instacart_users": instacart_stats["active_users"],
        "instacart_running_users": instacart_stats["running_users"],
        "instacart_new_users": instacart_stats["new_users"],
        "instacart_disconnected_users": instacart_stats["disconnected_users"],
        "breakdown": [
            {"label": "Spark activos", "value": spark_stats["active_users"]},
            {"label": "Instacart activos", "value": instacart_stats["active_users"]},
        ],
    }


def _cliente_cognito():
    return boto3.client(
        "cognito-idp",
        region_name=MULTIADMIN_AWS_REGION,
        config=Config(signature_version=UNSIGNED),
    )


def _secret_hash(username):
    if not MULTIADMIN_CLIENT_SECRET:
        return None

    digest = hmac.new(
        MULTIADMIN_CLIENT_SECRET.encode("utf-8"),
        f"{username}{MULTIADMIN_CLIENT_ID}".encode("utf-8"),
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


def _token_expirado_o_por_expirar(token, margen_segundos=300):
    payload = _decodificar_jwt_payload(token)
    expira_en = payload.get("exp")
    if not isinstance(expira_en, (int, float)):
        return False
    return expira_en <= time.time() + margen_segundos


def _hay_config_directa_multiadmin():
    return bool(
        MULTIADMIN_PROVISIONED_TOKEN
        or MULTIADMIN_ID_TOKEN
        or MULTIADMIN_REFRESH_TOKEN
        or (MULTIADMIN_USERNAME and MULTIADMIN_PASSWORD)
    )


def refrescar_multiadmin_token():
    refresh_token = _TOKEN_CACHE.get("refresh_token") or MULTIADMIN_REFRESH_TOKEN
    if not refresh_token:
        raise RuntimeError("Configura MULTIADMIN_REFRESH_TOKEN para renovar el token.")

    auth_parameters = {"REFRESH_TOKEN": refresh_token}
    if MULTIADMIN_USERNAME:
        auth_parameters["USERNAME"] = MULTIADMIN_USERNAME

    response = _cliente_cognito().initiate_auth(
        ClientId=MULTIADMIN_CLIENT_ID,
        AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters=_auth_parameters(auth_parameters),
    )
    return _guardar_tokens(response["AuthenticationResult"])


def iniciar_sesion_multiadmin():
    if not MULTIADMIN_USERNAME or not MULTIADMIN_PASSWORD:
        raise RuntimeError(
            "Configura MULTIADMIN_USERNAME y MULTIADMIN_PASSWORD para iniciar sesión."
        )

    response = _cliente_cognito().initiate_auth(
        ClientId=MULTIADMIN_CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters=_auth_parameters({
            "USERNAME": MULTIADMIN_USERNAME,
            "PASSWORD": MULTIADMIN_PASSWORD,
        }),
    )
    return _guardar_tokens(response["AuthenticationResult"])


def _renovar_token_multiadmin():
    try:
        return refrescar_multiadmin_token()["id_token"]
    except Exception:
        return iniciar_sesion_multiadmin()["id_token"]


def _obtener_token_multiadmin():
    if MULTIADMIN_PROVISIONED_TOKEN:
        return MULTIADMIN_PROVISIONED_TOKEN

    token = _TOKEN_CACHE.get("id_token") or MULTIADMIN_ID_TOKEN
    if token and _token_expirado_o_por_expirar(token):
        try:
            return _renovar_token_multiadmin()
        except Exception:
            return token
    if token:
        return token
    return _renovar_token_multiadmin()


def _headers_multiadmin(token):
    return {
        "accept": "application/json",
        "authorization": f"Bearer {token}",
        "origin": "https://admin.camarada.io",
        "referer": "https://admin.camarada.io/",
        "user-agent": "Mozilla/5.0",
    }


def _request_json_multiadmin(path, token):
    url = f"{MULTIADMIN_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    response = requests.get(url, headers=_headers_multiadmin(token), timeout=30)
    response.raise_for_status()
    return response.json()


def _error_autenticacion_multiadmin(error):
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) in (401, 403)


def _extraer_items(data, items_key):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get(items_key)
        if isinstance(items, list):
            return items
        for fallback_key in ("Items", "items"):
            items = data.get(fallback_key)
            if isinstance(items, list):
                return items
    return []


def _obtener_usuarios_directo(system_config, token):
    path = (
        f"/projects/{system_config['api_key']}/users"
        f"?sinceExpiration={MULTIADMIN_USERS_SINCE_EXPIRATION}"
    )
    data = _request_json_multiadmin(path, token)
    return _extraer_items(data, system_config["items_key"])


def _obtener_bonus_directo(token):
    data = _request_json_multiadmin("/projects/compinche/bonus", token)
    return _normalizar_bonus_multiadmin(data)


def _normalizar_lista_multiadmin(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "items", "Items", "result"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _oferta_chispita_ganada(offer):
    status = str(offer.get("status") or "").strip().lower()
    return status in {"", "got"}


def _metricas_ofertas_chispita(data):
    ofertas = [
        offer for offer in _normalizar_lista_multiadmin(data)
        if isinstance(offer, dict) and _oferta_chispita_ganada(offer)
    ]
    usuarios = {
        offer.get("phoneNumber")
        for offer in ofertas
        if isinstance(offer.get("phoneNumber"), str) and offer.get("phoneNumber")
    }
    return {
        "offers": len(ofertas),
        "users": len(usuarios),
    }


def _obtener_ofertas_chispita_directo(token, app=None):
    suffix = f"&app={app}" if app else ""
    data = _request_json_multiadmin(f"/projects/chispita/offers/won?period=today{suffix}", token)
    return _metricas_ofertas_chispita(data)


def _obtener_metricas_ofertas_chispita(token):
    total = _obtener_ofertas_chispita_directo(token)
    spark = _obtener_ofertas_chispita_directo(token, "spark")
    instacart = _obtener_ofertas_chispita_directo(token, "instacart")
    return {
        "offers_won_today": total["offers"],
        "offers_won_today_users": total["users"],
        "spark_offers_won_today": spark["offers"],
        "spark_offers_won_today_users": spark["users"],
        "instacart_offers_won_today": instacart["offers"],
        "instacart_offers_won_today_users": instacart["users"],
    }


def _normalizar_bonus_multiadmin(data):
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


def _metricas_desde_usuarios(system, usuarios, exclude_admins=False):
    usuarios_validos = [user for user in usuarios if isinstance(user, dict)]
    if exclude_admins:
        usuarios_validos = [user for user in usuarios_validos if not _usuario_admin(user)]

    active_users = sum(1 for user in usuarios_validos if _usuario_good_standing(user))
    if system == "chispita":
        running_users = sum(1 for user in usuarios_validos if _usuario_chispita_running(user))
    else:
        running_users = sum(
            1 for user in usuarios_validos
            if _usuario_good_standing(user) and _usuario_running(user)
        )
    disconnected_users = sum(1 for user in usuarios_validos if not _usuario_good_standing(user))
    new_users = sum(1 for user in usuarios_validos if _usuario_creado_hoy(user))

    metricas = {
        "system": system,
        "display_name": str(system).replace("_", " ").replace("-", " ").title(),
        "active_users": active_users,
        "running_users": running_users,
        "total_users": len(usuarios_validos),
        "new_users": new_users,
        "disconnected_users": disconnected_users,
    }

    if system == "Compinche":
        metricas["active_by_promo_users"] = sum(
            1 for user in usuarios_validos
            if _usuario_good_standing(user) and _usuario_tiene_promo(user)
        )
    elif system == "chispita":
        metricas.update(_metricas_chispita_por_plataforma(usuarios_validos))

    return metricas


def _obtener_metricas_multiadmin_directo_con_token(token):
    metricas = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_system = {
            executor.submit(_obtener_usuarios_directo, config, token): (system, config)
            for system, config in DIRECT_SYSTEMS.items()
        }
        bonus_future = executor.submit(_obtener_bonus_directo, token)

        for future, (system, config) in future_to_system.items():
            usuarios = future.result()
            metricas[system] = _metricas_desde_usuarios(
                system,
                usuarios,
                exclude_admins=config.get("exclude_admins", False),
            )

        bonus_stats = bonus_future.result()

    try:
        paripe_legacy = _obtener_metricas_multiadmin_legacy().get("Paripe", {})
    except Exception:
        paripe_legacy = {}
    metricas["Paripe"]["good_standing_users"] = metricas["Paripe"]["active_users"]
    metricas["Paripe"]["photo_pool"] = paripe_legacy.get("photo_pool", 0)
    metricas["Compinche"]["bonus_stats"] = bonus_stats
    if "chispita" in metricas:
        try:
            ofertas_chispita = _obtener_metricas_ofertas_chispita(token)
        except Exception:
            ofertas_chispita = None
        if ofertas_chispita:
            metricas["chispita"].update(ofertas_chispita)
            metricas["chispita"].setdefault("breakdown", []).extend([
                {"label": "Spark ofertas ganadas hoy", "value": ofertas_chispita["spark_offers_won_today"]},
                {"label": "Instacart ofertas ganadas hoy", "value": ofertas_chispita["instacart_offers_won_today"]},
            ])

    return metricas


def _obtener_metricas_multiadmin_directo():
    token = _obtener_token_multiadmin()

    try:
        return _obtener_metricas_multiadmin_directo_con_token(token)
    except requests.HTTPError as error:
        if (
            _error_autenticacion_multiadmin(error)
            and MULTIADMIN_USERNAME
            and MULTIADMIN_PASSWORD
        ):
            tokens = iniciar_sesion_multiadmin()
            return _obtener_metricas_multiadmin_directo_con_token(tokens["id_token"])
        raise


def _normalizar_sistema_generico(key, value):
    data = _safe_dict(value)
    return {
        "system": key,
        "display_name": str(key).replace("_", " ").replace("-", " ").title(),
        "active_users": _to_int(data.get("active")),
        "running_users": _to_int(data.get("running")),
    }


def _extraer_ofertas_chispita_legacy(chispita):
    for key in (
        "offersWonToday",
        "usersWithOffersWonToday",
        "capturedOrdersToday",
        "ordersCapturedToday",
        "ordersWonToday",
        "ofertasGanadasHoy",
        "ordenesCapturadasHoy",
    ):
        if key in chispita:
            return _to_int(chispita.get(key))
    return None


def _obtener_metricas_multiadmin_legacy():
    response = requests.get(ENDPOINT_MULTIADMIN, timeout=30)
    response.raise_for_status()

    data = _safe_dict(response.json())

    compinche = _safe_dict(data.get("compinche"))
    paripe = _safe_dict(data.get("paripe"))
    camarada = _safe_dict(data.get("camarada"))
    complice = _safe_dict(data.get("complice"))
    secuaz = _safe_dict(data.get("secuaz"))
    ready4drive = _safe_dict(data.get("ready4drive"))
    chispita = _safe_dict(data.get("chispita"))
    paripe_images_bank = _safe_dict(paripe.get("images-bank"))

    metricas = {
        "Compinche": {
            "active_users": _restar_admins_compinche(compinche.get("active")),
            "running_users": _to_int(compinche.get("running")),
            "active_by_promo_users": None,
            "bonus_stats": None,
        },
        "Paripe": {
            "active_users": _to_int(paripe.get("active")),
            "good_standing_users": _to_int(paripe.get("active")),
            "photo_pool": _to_int(paripe_images_bank.get("items")),
        },
        "camarada": {
            "active_users": _to_int(camarada.get("active")),
            "running_users": _to_int(camarada.get("running")),
        },
        "complice": {
            "active_users": _to_int(complice.get("active")),
            "running_users": _to_int(complice.get("running")),
        },
        "secuaz": {
            "active_users": _to_int(secuaz.get("active")),
            "running_users": _to_int(secuaz.get("running")),
        },
        "ready4drive": {
            "active_users": _to_int(ready4drive.get("active")),
            "running_users": _to_int(ready4drive.get("running")),
        },
    }

    if chispita:
        metricas["chispita"] = {
            "system": "chispita",
            "display_name": "Chispita",
            "active_users": _to_int(chispita.get("active")),
            "running_users": _to_int(chispita.get("running")),
        }
        ofertas_ganadas = _extraer_ofertas_chispita_legacy(chispita)
        if any(key in chispita for key in ("spark", "sparkUsers", "instacart", "instacartUsers")):
            metricas["chispita"]["spark_users"] = _to_int(chispita.get("spark") or chispita.get("sparkUsers"))
            metricas["chispita"]["instacart_users"] = _to_int(
                chispita.get("instacart") or chispita.get("instacartUsers")
            )
            metricas["chispita"]["breakdown"] = [
                {"label": "Spark", "value": metricas["chispita"]["spark_users"]},
                {"label": "Instacart", "value": metricas["chispita"]["instacart_users"]},
            ]
        if ofertas_ganadas is not None:
            metricas["chispita"]["offers_won_today_users"] = ofertas_ganadas
            metricas["chispita"].setdefault("breakdown", []).append(
                {"label": "Ofertas ganadas hoy", "value": ofertas_ganadas}
            )

    for key, value in data.items():
        if key in KNOWN_SYSTEM_KEYS:
            continue
        if not isinstance(value, dict) or ("active" not in value and "running" not in value):
            continue
        metricas[key] = _normalizar_sistema_generico(key, value)

    return metricas


def obtener_metricas_multiadmin():
    if _hay_config_directa_multiadmin():
        try:
            return _obtener_metricas_multiadmin_directo()
        except Exception:
            metricas = _obtener_metricas_multiadmin_legacy()
            if "chispita" not in metricas:
                metricas["chispita"] = {
                    "system": "chispita",
                    "display_name": "Chispita",
                    "active_users": 0,
                    "running_users": 0,
                    "progress": "Error",
                    "error": (
                        "No se pudo consultar Chispita desde Multiadmin directo. "
                        "Revisa MULTIADMIN_USERNAME y MULTIADMIN_PASSWORD en Vercel."
                    ),
                }
            return metricas
    return _obtener_metricas_multiadmin_legacy()


if __name__ == "__main__":
    print(obtener_metricas_multiadmin())
