import json
import logging
import os

import requests
from flask import Blueprint, abort, render_template, request
from werkzeug.utils import secure_filename

agent_video_upload_bp = Blueprint("agent_video_upload", __name__)
logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_EXTENSIONS = {
    "mp4",
    "mov",
    "avi",
    "mkv",
    "webm",
    "m4v",
}


def _get_access_token():
    return (os.getenv("AGENT_VIDEO_ACCESS_TOKEN") or "").strip()


def _get_webhook_url():
    return (os.getenv("AGENT_VIDEO_WEBHOOK_URL") or "").strip()


def _get_webhook_token():
    return (os.getenv("AGENT_VIDEO_WEBHOOK_TOKEN") or "").strip()


def _get_drive_folder_id():
    return (os.getenv("AGENT_VIDEO_DRIVE_FOLDER_ID") or "").strip()


def _get_max_size_mb():
    raw_value = (os.getenv("AGENT_VIDEO_MAX_SIZE_MB") or "25").strip()
    try:
        value = int(raw_value)
    except ValueError:
        value = 25
    return max(value, 1)


def _get_max_size_bytes():
    return _get_max_size_mb() * 1024 * 1024


def _get_allowed_extensions():
    raw_value = (os.getenv("AGENT_VIDEO_ALLOWED_EXTENSIONS") or "").strip()
    if not raw_value:
        return DEFAULT_ALLOWED_EXTENSIONS

    values = {
        item.strip().lower().lstrip(".")
        for item in raw_value.split(",")
        if item.strip()
    }
    return values or DEFAULT_ALLOWED_EXTENSIONS


def _extract_access_token():
    return (
        (request.args.get("token") or "").strip()
        or (request.form.get("token") or "").strip()
    )


def _ensure_authorized():
    configured_token = _get_access_token()
    request_token = _extract_access_token()

    if not configured_token or request_token != configured_token:
        abort(403)

    return request_token


def _allowed_file(filename):
    filename = secure_filename(filename or "")
    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[-1].lower()
    return extension in _get_allowed_extensions()


def _validate_video_file(file_storage):
    if not file_storage or not file_storage.filename:
        raise ValueError("Debes seleccionar un archivo de video.")

    filename = secure_filename(file_storage.filename)
    if not filename:
        raise ValueError("El nombre del archivo no es valido.")

    if not _allowed_file(filename):
        allowed = ", ".join(sorted(_get_allowed_extensions()))
        raise ValueError(f"Formato no permitido. Usa uno de: {allowed}.")

    if request.content_length and request.content_length > (_get_max_size_bytes() + 1024 * 1024):
        raise ValueError(
            f"El archivo excede el limite permitido de {_get_max_size_mb()} MB."
        )

    content = file_storage.read()
    if not content:
        raise ValueError("El archivo esta vacio.")

    if len(content) > _get_max_size_bytes():
        raise ValueError(
            f"El archivo excede el limite permitido de {_get_max_size_mb()} MB."
        )

    return filename, content


def _send_video_to_webhook(filename, content, content_type, agent_name, notes):
    webhook_url = _get_webhook_url()
    webhook_token = _get_webhook_token()
    drive_folder_id = _get_drive_folder_id()

    if not webhook_url:
        raise RuntimeError("No esta configurada la variable AGENT_VIDEO_WEBHOOK_URL.")

    if not webhook_token:
        raise RuntimeError("No esta configurada la variable AGENT_VIDEO_WEBHOOK_TOKEN.")

    if not drive_folder_id:
        raise RuntimeError("No esta configurada la variable AGENT_VIDEO_DRIVE_FOLDER_ID.")

    data = {
        "webhook_token": webhook_token,
        "drive_folder_id": drive_folder_id,
        "agent_name": agent_name,
        "notes": notes,
        "original_filename": filename,
    }
    files = {
        "video": (
            filename,
            content,
            content_type or "application/octet-stream",
        )
    }

    try:
        response = requests.post(
            webhook_url,
            data=data,
            files=files,
            timeout=(20, 600),
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"No se pudo conectar con el servicio de videos: {exc}")

    if response.status_code != 200:
        raise RuntimeError(
            f"El servicio de videos respondio con estado {response.status_code}: {response.text}"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"El servicio de videos no devolvio JSON valido: {exc}")

    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "No se pudo subir el video.")

    return payload


@agent_video_upload_bp.route("/agentes/subir-video", methods=["GET", "POST"])
def upload_video():
    access_token = _ensure_authorized()
    message = ""
    error = ""
    upload_result = None
    agent_name = (request.form.get("agent_name") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    if request.method == "POST":
        try:
            video_file = request.files.get("video")
            filename, content = _validate_video_file(video_file)
            upload_result = _send_video_to_webhook(
                filename=filename,
                content=content,
                content_type=getattr(video_file, "mimetype", ""),
                agent_name=agent_name,
                notes=notes,
            )
            message = "Video enviado correctamente."
        except Exception as exc:
            logger.exception("Error subiendo video de agente")
            error = str(exc)

    return render_template(
        "agent_video_upload.html",
        access_token=access_token,
        message=message,
        error=error,
        upload_result=upload_result,
        agent_name=agent_name,
        notes=notes,
        max_size_mb=_get_max_size_mb(),
        allowed_extensions=sorted(_get_allowed_extensions()),
        webhook_configured=bool(_get_webhook_url() and _get_webhook_token() and _get_drive_folder_id()),
    )
