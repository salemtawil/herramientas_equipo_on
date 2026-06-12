import io
import logging
import os
from pathlib import Path

import requests
from flask import Blueprint, render_template, request

from utils.archivos import formatear_tamano_bytes

informe_semanal_cs_bp = Blueprint("informe_semanal_cs", __name__)
logger = logging.getLogger(__name__)

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
GEMINI_GENERATE_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_WEEKLY_REPORT_MODEL_DEFAULT = "gpt-4.1-mini"
GEMINI_WEEKLY_REPORT_MODEL_DEFAULT = "gemini-2.5-flash"
OLLAMA_BASE_URL_DEFAULT = "http://127.0.0.1:11434"
OLLAMA_WEEKLY_REPORT_MODEL_DEFAULT = "qwen2.5:7b"
REQUEST_TIMEOUT = 90
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
MAX_TEXT_CHARS = 120000
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log"}
UNSUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".xls", ".ods"}

REPORT_STRUCTURE = [
    {
        "title": "Actividades en la semana",
        "guidance": "apertura operativa del período y lista de actividades relevantes.",
    },
    {
        "title": "Reunión semanal / Town Hall",
        "guidance": "puntos principales tratados, con desarrollo por tema.",
    },
    {
        "title": "NPS, Auditoría interna",
        "guidance": "resultado actual, resultado anterior, variación, lectura ejecutiva y conclusión.",
    },
    {
        "title": "CSAT y Chats con negativos, Auditoría interna",
        "guidance": "semana anterior, semana actual, distribución de calificaciones, resumen comparativo, auditoría de negativos, clasificación, casos relevantes, CSAT ajustado y conclusión general.",
    },
    {
        "title": "Stats semanal de llamadas",
        "guidance": "resumen por turnos, totales generales, llamadas perdidas, lectura de cobertura y conclusión.",
    },
    {
        "title": "Incidencias",
        "guidance": "separar al menos entre agentes/procedimientos y sistemas/plataformas/producto cuando haya datos.",
    },
    {
        "title": "Leaderboard en Call Analysis",
        "guidance": "top performers, volumen, nivel general, menor score, oportunidades puntuales y conclusión.",
    },
    {
        "title": "Resumen semanal de conversaciones y tiempos de atención",
        "guidance": "volumen Chatwoot, mensajes, primera respuesta, resolución, espera, análisis y conclusión.",
    },
    {
        "title": "Pendientes",
        "guidance": "lista accionable de seguimientos abiertos.",
    },
    {
        "title": "Conclusión ejecutiva",
        "guidance": "lectura global de operación, NPS, CSAT, llamadas, conversaciones, incidencias, riesgos y prioridades.",
    },
]
REPORT_SECTIONS = [section["title"] for section in REPORT_STRUCTURE]


def limpiar_texto(valor):
    return str(valor or "").strip()


def limitar_texto(texto, max_chars=MAX_TEXT_CHARS):
    texto = limpiar_texto(texto)
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars] + "\n[Texto truncado por límite operativo]"


def decodificar_texto(contenido):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return contenido.decode(encoding)
        except UnicodeDecodeError:
            continue
    return contenido.decode("latin-1", errors="replace")


def leer_bytes_archivo(file_storage, max_bytes=MAX_UPLOAD_BYTES):
    stream = getattr(file_storage, "stream", None)
    if stream and hasattr(stream, "tell") and hasattr(stream, "seek"):
        posicion = stream.tell()
        try:
            stream.seek(0, os.SEEK_END)
            tamano = stream.tell()
        finally:
            stream.seek(posicion)

        if tamano > max_bytes:
            raise ValueError(
                f"El archivo supera el límite permitido de {formatear_tamano_bytes(max_bytes)}."
            )

    contenido = file_storage.read()
    if hasattr(file_storage, "seek"):
        file_storage.seek(0)

    if len(contenido) > max_bytes:
        raise ValueError(
            f"El archivo supera el límite permitido de {formatear_tamano_bytes(max_bytes)}."
        )
    return contenido


def extract_text_from_pdf(contenido, nombre_archivo):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError(
            "Falta instalar pypdf para extraer texto de PDF."
        ) from exc

    reader = PdfReader(io.BytesIO(contenido))
    textos = []
    for indice, page in enumerate(reader.pages, start=1):
        texto = limpiar_texto(page.extract_text())
        if texto:
            textos.append(f"--- Página {indice} de {nombre_archivo} ---\n{texto}")

    if not textos:
        return "", f"{nombre_archivo}: no se pudo extraer texto del PDF."
    return "\n\n".join(textos), ""


def extract_text_from_image(_contenido, nombre_archivo):
    return "", f"{nombre_archivo}: imagen recibida, pero esta V1 no extrae texto de imágenes."


def extract_text_from_spreadsheet(_contenido, nombre_archivo):
    return "", f"{nombre_archivo}: hoja de cálculo recibida, pero esta V1 no extrae texto de spreadsheets."


def extract_text_from_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return "", []

    nombre = Path(file_storage.filename).name
    extension = Path(nombre).suffix.lower()
    contenido = leer_bytes_archivo(file_storage)

    if extension in TEXT_EXTENSIONS or not extension:
        texto = decodificar_texto(contenido)
        return f"\n\n--- Archivo: {nombre} ---\n{limitar_texto(texto)}", []

    if extension == ".pdf":
        texto, warning = extract_text_from_pdf(contenido, nombre)
        return texto, [warning] if warning else []

    if extension in {".png", ".jpg", ".jpeg", ".webp"}:
        texto, warning = extract_text_from_image(contenido, nombre)
        return texto, [warning] if warning else []

    if extension in {".xlsx", ".xls", ".ods"}:
        texto, warning = extract_text_from_spreadsheet(contenido, nombre)
        return texto, [warning] if warning else []

    if extension in UNSUPPORTED_EXTENSIONS:
        return "", [f"{nombre}: formato recibido, pero no se extrae texto en esta V1."]

    return "", [f"{nombre}: tipo de archivo no soportado para extracción de texto."]


def extract_text_from_files(files):
    textos = []
    warnings = []
    for file_storage in files:
        if not file_storage or not file_storage.filename:
            continue
        try:
            texto, file_warnings = extract_text_from_upload(file_storage)
            if texto:
                textos.append(texto)
            warnings.extend(file_warnings)
        except Exception as exc:
            warnings.append(f"{file_storage.filename}: no se pudo leer el archivo ({exc}).")
    return "\n".join(textos).strip(), warnings


def build_weekly_report_prompt(datos):
    secciones = "\n".join(f"{indice}. {titulo}" for indice, titulo in enumerate(REPORT_SECTIONS, start=1))
    molde = "\n".join(
        f"- {section['title']}: {section['guidance']}"
        for section in REPORT_STRUCTURE
    )
    return f"""
Genera un informe semanal ejecutivo de Customer Support en español.

Reglas obligatorias:
- Usa tono formal, ejecutivo, operativo, claro y profesional.
- No inventes datos, métricas, nombres, responsables, variaciones ni conclusiones no sustentadas.
- Respeta exactamente estas secciones y este orden:
{secciones}
- El título principal debe seguir este estilo: "Informe General CS semana del [período]."
- Si falta información de una sección, conserva el título y deja la sección sin desarrollo o indica "Pendiente" solo si la falta de información es clara.
- La sección "CSAT y Chats con negativos, Auditoría interna" solo debe completarse si hay datos de CSAT.
- La sección "Incidencias" debe conservar detalles importantes: nombres, usuarios, sistemas, errores, procedimientos, responsables, casos y seguimientos.
- Organiza las incidencias por categorías cuando sea posible, sin borrar detalles accionables.
- En leaderboard evita lenguaje punitivo. Usa formulaciones como "requiere revisión puntual" u "oportunidad de seguimiento".
- El resultado debe parecer un documento profesional, no una copia literal de la bitácora.
- Usa el informe anterior como referencia de estilo, extensión, forma de redactar, numeración y nivel de detalle, pero actualiza el contenido con los datos del nuevo período.
- Mantén párrafos ejecutivos y listas con viñetas cuando ayuden a conservar detalle operativo.
- Devuelve solo el informe final en Markdown, sin explicar el proceso.

Molde esperado por sección:
{molde}

Datos del informe:
Nombre: {datos["nombre_informe"] or "Sin nombre"}
Período: {datos["periodo"] or "Sin período indicado"}

Informe anterior o plantilla base:
{limitar_texto(datos["informe_anterior"]) or "Sin información."}

Bitácora del nuevo período:
{limitar_texto(datos["bitacora"]) or "Sin información."}

Archivos adicionales extraídos:
{limitar_texto(datos["archivos_adicionales"]) or "Sin información extraída."}

Notas manuales:
{limitar_texto(datos["notas"]) or "Sin notas."}
""".strip()


def extraer_texto_respuesta_openai(data):
    if data.get("output_text"):
        return limpiar_texto(data["output_text"])

    textos = []
    for item in data.get("output", []):
        for contenido in item.get("content", []):
            texto = contenido.get("text")
            if texto:
                textos.append(texto)
    return "\n".join(textos).strip()


def extraer_texto_respuesta_gemini(data):
    textos = []
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            texto = part.get("text")
            if texto:
                textos.append(texto)
    return "\n".join(textos).strip()


def obtener_ia_config():
    provider = limpiar_texto(os.getenv("WEEKLY_REPORT_AI_PROVIDER")).lower()
    if not provider:
        if limpiar_texto(os.getenv("OPENAI_API_KEY")):
            provider = "openai"
        elif limpiar_texto(os.getenv("GEMINI_API_KEY")):
            provider = "gemini"
        else:
            provider = "none"
    if provider not in {"openai", "gemini", "ollama", "none"}:
        provider = "none"

    return {
        "provider": provider,
        "api_key": limpiar_texto(os.getenv("OPENAI_API_KEY")),
        "gemini_api_key": limpiar_texto(os.getenv("GEMINI_API_KEY")),
        "openai_model": limpiar_texto(os.getenv("OPENAI_WEEKLY_REPORT_MODEL")) or OPENAI_WEEKLY_REPORT_MODEL_DEFAULT,
        "gemini_model": limpiar_texto(os.getenv("GEMINI_WEEKLY_REPORT_MODEL")) or GEMINI_WEEKLY_REPORT_MODEL_DEFAULT,
        "ollama_model": limpiar_texto(os.getenv("OLLAMA_WEEKLY_REPORT_MODEL"))
        or limpiar_texto(os.getenv("OLLAMA_CSAT_MODEL"))
        or OLLAMA_WEEKLY_REPORT_MODEL_DEFAULT,
        "ollama_base_url": limpiar_texto(os.getenv("OLLAMA_BASE_URL")) or OLLAMA_BASE_URL_DEFAULT,
    }


def obtener_estado_ia():
    config = obtener_ia_config()

    if config["provider"] == "openai":
        return {
            "provider": "openai",
            "label": "IA OpenAI conectada" if config["api_key"] else "OpenAI sin API key",
            "model": config["openai_model"],
            "is_ready": bool(config["api_key"]),
        }

    if config["provider"] == "gemini":
        return {
            "provider": "gemini",
            "label": "IA Gemini conectada" if config["gemini_api_key"] else "Gemini sin API key",
            "model": config["gemini_model"],
            "is_ready": bool(config["gemini_api_key"]),
        }

    if config["provider"] == "ollama":
        return {
            "provider": "ollama",
            "label": "IA Ollama configurada",
            "model": config["ollama_model"],
            "is_ready": True,
        }

    return {
        "provider": "none",
        "label": "IA sin configurar",
        "model": "",
        "is_ready": False,
    }


def generate_weekly_report_openai(prompt, config):
    if not config["api_key"]:
        raise ValueError("Configura OPENAI_API_KEY para generar el informe con OpenAI.")

    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": config["openai_model"],
            "input": [
                {
                    "role": "system",
                    "content": "Eres un gerente senior de Customer Support que redacta informes ejecutivos semanales.",
                },
                {"role": "user", "content": prompt},
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 401:
        raise ValueError("OpenAI rechazó la API key. Revisa que OPENAI_API_KEY sea válida.")
    if response.status_code == 429:
        raise ValueError(
            "OpenAI respondió límite de uso o cuota insuficiente. Revisa crédito, billing o rate limits del proyecto."
        )
    if response.status_code >= 500:
        raise ValueError("OpenAI tuvo un error temporal. Intenta de nuevo en unos minutos.")
    response.raise_for_status()

    texto = extraer_texto_respuesta_openai(response.json())
    if not texto:
        raise ValueError("OpenAI no devolvió texto para el informe.")
    return texto


def generate_weekly_report_gemini(prompt, config):
    if not config["gemini_api_key"]:
        raise ValueError("Configura GEMINI_API_KEY para generar el informe con Gemini.")

    response = requests.post(
        GEMINI_GENERATE_URL_TEMPLATE.format(model=config["gemini_model"]),
        headers={
            "x-goog-api-key": config["gemini_api_key"],
            "Content-Type": "application/json",
        },
        json={
            "systemInstruction": {
                "parts": [
                    {
                        "text": "Eres un gerente senior de Customer Support que redacta informes ejecutivos semanales.",
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
        },
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code in {400, 401, 403}:
        raise ValueError("Gemini rechazó la solicitud. Revisa GEMINI_API_KEY, modelo y permisos del proyecto.")
    if response.status_code == 429:
        raise ValueError("Gemini respondió límite de uso o cuota insuficiente. Revisa billing, cuota o rate limits.")
    if response.status_code >= 500:
        raise ValueError("Gemini tuvo un error temporal. Intenta de nuevo en unos minutos.")
    response.raise_for_status()

    texto = extraer_texto_respuesta_gemini(response.json())
    if not texto:
        raise ValueError("Gemini no devolvió texto para el informe.")
    return texto


def generate_weekly_report_ollama(prompt, config):
    response = requests.post(
        config["ollama_base_url"].rstrip("/") + "/api/generate",
        json={
            "model": config["ollama_model"],
            "prompt": (
                "Eres un gerente senior de Customer Support que redacta informes ejecutivos semanales.\n\n"
                + prompt
            ),
            "stream": False,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    texto = limpiar_texto(response.json().get("response"))
    if not texto:
        raise ValueError("Ollama no devolvió texto para el informe.")
    return texto


def generar_informe_fallback(datos):
    base = limpiar_texto(datos["bitacora"]) or limpiar_texto(datos["notas"]) or limpiar_texto(datos["archivos_adicionales"])
    tiene_csat = "csat" in base.lower() or "chat negativo" in base.lower()
    lineas = [
        f"# {datos['nombre_informe'] or 'Informe Semanal CS'}",
        "",
        f"**Período:** {datos['periodo'] or 'Pendiente'}",
        "",
    ]

    for titulo in REPORT_SECTIONS:
        lineas.append(f"## {titulo}")
        if titulo == "Actividades en la semana" and base:
            lineas.append("Información base recibida para redactar esta sección:")
            lineas.append("")
            lineas.append(limitar_texto(base, 2500))
        elif titulo == "CSAT y Chats con negativos, Auditoría interna" and not tiene_csat:
            lineas.append("")
        else:
            lineas.append("Pendiente.")
        lineas.append("")

    return "\n".join(lineas).strip()


def generate_weekly_report(datos):
    prompt = build_weekly_report_prompt(datos)
    config = obtener_ia_config()

    if config["provider"] == "openai":
        return generate_weekly_report_openai(prompt, config), "openai", []
    if config["provider"] == "gemini":
        return generate_weekly_report_gemini(prompt, config), "gemini", []
    if config["provider"] == "ollama":
        return generate_weekly_report_ollama(prompt, config), "ollama", []

    warning = (
        "IA no configurada: define OPENAI_API_KEY, GEMINI_API_KEY o WEEKLY_REPORT_AI_PROVIDER=ollama para generar el informe completo. Por ahora se creó una base editable con la estructura obligatoria."
    )
    return generar_informe_fallback(datos), "fallback", [warning]


@informe_semanal_cs_bp.route("/informe-semanal-cs", methods=["GET", "POST"])
def informe_semanal_cs():
    mensaje = ""
    advertencia = ""
    warnings = []
    informe_generado = ""
    fuente_generacion = ""
    datos = {
        "nombre_informe": "",
        "periodo": "",
        "informe_anterior": "",
        "bitacora": "",
        "archivos_adicionales": "",
        "notas": "",
    }

    if request.method == "POST":
        datos.update(
            {
                "nombre_informe": limpiar_texto(request.form.get("nombre_informe")),
                "periodo": limpiar_texto(request.form.get("periodo")),
                "informe_anterior": limpiar_texto(request.form.get("informe_anterior")),
                "bitacora": limpiar_texto(request.form.get("bitacora")),
                "notas": limpiar_texto(request.form.get("notas")),
            }
        )

        try:
            texto_informe_anterior, warnings_anterior = extract_text_from_files(
                [request.files.get("informe_anterior_archivo")]
            )
            texto_bitacora, warnings_bitacora = extract_text_from_files(
                [request.files.get("bitacora_archivo")]
            )
            texto_adicional, warnings_adicionales = extract_text_from_files(
                request.files.getlist("archivos_adicionales")
            )
            warnings.extend(warnings_anterior + warnings_bitacora + warnings_adicionales)

            if texto_informe_anterior:
                datos["informe_anterior"] = (
                    datos["informe_anterior"] + "\n\n" + texto_informe_anterior
                ).strip()
            if texto_bitacora:
                datos["bitacora"] = (
                    datos["bitacora"] + "\n\n" + texto_bitacora
                ).strip()
            datos["archivos_adicionales"] = texto_adicional

            informe_generado, fuente_generacion, generation_warnings = generate_weekly_report(datos)
            warnings.extend(generation_warnings)
            mensaje = "Informe generado. Puedes editarlo, copiarlo o descargarlo."
        except Exception as exc:
            logger.exception("Error generando informe semanal CS")
            advertencia = f"No se pudo generar el informe: {exc}"

    return render_template(
        "informe_semanal_cs.html",
        mensaje=mensaje,
        advertencia=advertencia,
        warnings=warnings,
        datos=datos,
        informe_generado=informe_generado,
        fuente_generacion=fuente_generacion,
        ia_estado=obtener_estado_ia(),
    )
