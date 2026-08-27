import base64
import gzip
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta

from itsdangerous import BadData, URLSafeSerializer

INLINE_STATE_MAX_BYTES = 120 * 1024
STATE_ID_PATTERN = re.compile(r"^[a-z0-9_-]{1,80}$")


def _temp_root():
    return os.getenv("TEMP") or os.getenv("TMP") or tempfile.gettempdir()


def _validar_namespace(namespace):
    texto = str(namespace or "").strip().lower()
    if not STATE_ID_PATTERN.fullmatch(texto):
        raise ValueError("Namespace temporal invalido.")
    return texto


def _validar_state_id(state_id):
    texto = str(state_id or "").strip().lower()
    if not STATE_ID_PATTERN.fullmatch(texto):
        raise ValueError("Identificador temporal invalido.")
    return texto


def obtener_directorio_estado(namespace):
    namespace = _validar_namespace(namespace)
    base_dir = os.path.join(_temp_root(), "herramientas_equipo_on", namespace)
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def limpiar_estados_temporales_expirados(namespace, ttl_hours=24):
    ahora = datetime.utcnow()
    ttl = timedelta(hours=ttl_hours)
    base_dir = obtener_directorio_estado(namespace)

    for nombre in os.listdir(base_dir):
        ruta = os.path.join(base_dir, nombre)
        if not os.path.isfile(ruta):
            continue

        try:
            modificado = datetime.utcfromtimestamp(os.path.getmtime(ruta))
        except OSError:
            continue

        if ahora - modificado > ttl:
            try:
                os.remove(ruta)
            except OSError:
                continue


def ruta_estado_temporal(namespace, state_id):
    state_id = _validar_state_id(state_id)
    return os.path.join(obtener_directorio_estado(namespace), f"{state_id}.json")


def guardar_json_temporal(data, namespace, state_id=None):
    state_id = _validar_state_id(state_id or str(uuid.uuid4()))

    with open(ruta_estado_temporal(namespace, state_id), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)

    return state_id


def cargar_json_temporal(state_id, namespace):
    if not state_id:
        return None

    try:
        ruta = ruta_estado_temporal(namespace, state_id)
    except ValueError:
        return None

    if not os.path.exists(ruta):
        return None

    with open(ruta, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _serializar_inline(data):
    data_bytes = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    comprimido = gzip.compress(data_bytes)
    return base64.urlsafe_b64encode(comprimido).decode("ascii")


def _deserializar_inline(value):
    comprimido = base64.urlsafe_b64decode(value.encode("ascii"))
    return json.loads(gzip.decompress(comprimido).decode("utf-8"))


def guardar_estado_temporal(
    data,
    *,
    secret_key,
    salt,
    namespace,
    ttl_hours=24,
    inline_limit_bytes=INLINE_STATE_MAX_BYTES,
):
    limpiar_estados_temporales_expirados(namespace, ttl_hours=ttl_hours)

    serializer = URLSafeSerializer(secret_key, salt=salt)
    data_inline = _serializar_inline(data)

    if len(data_inline.encode("ascii")) <= inline_limit_bytes:
        payload = {
            "mode": "inline",
            "data": data_inline,
        }
    else:
        state_id = guardar_json_temporal(data, namespace=namespace)
        payload = {
            "mode": "file",
            "state_id": state_id,
        }

    return serializer.dumps(payload)


def cargar_estado_temporal(token, *, secret_key, salt, namespace):
    if not token:
        return None

    serializer = URLSafeSerializer(secret_key, salt=salt)

    try:
        payload = serializer.loads(token)
    except BadData:
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("mode") == "inline":
        data = payload.get("data")
        if not data:
            return None
        try:
            return _deserializar_inline(data)
        except Exception:
            return None

    if payload.get("mode") == "file":
        return cargar_json_temporal(payload.get("state_id"), namespace=namespace)

    return None
