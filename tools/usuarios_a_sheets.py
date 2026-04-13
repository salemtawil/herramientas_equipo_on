import io
import os
import re
import json
import logging
import unicodedata

import pandas as pd
import requests
from flask import Blueprint, Response, current_app, render_template, request
from itsdangerous import BadData, URLSafeSerializer

from utils.archivos import _leer_csv_desde_bytes
from utils.turnos import cargar_turnos_fijos

usuarios_a_sheets_bp = Blueprint("usuarios_a_sheets", __name__)
logger = logging.getLogger(__name__)

FORM_KEY_PAYLOAD = "usuarios_a_sheets_payload"

COLUMNAS_FINALES = [
    "Nombre",
    "Telefono",
    "Preferido",
    "Perfil",
    "Region",
    "TZ",
    "Agente",
    "Contesto",
    "SMS",
    "Ticket",
    "Nota",
]

ALIAS_COLUMNAS = {
    "usuario": [
        "usuario",
        "user",
        "username",
        "nombre",
        "name",
        "full name",
        "nombre completo",
        "customer name",
        "client name",
        "nombre del usuario",
        "user name",
    ],
    "telefono": [
        "telefono",
        "teléfono",
        "phone",
        "phone number",
        "telefono principal",
        "teléfono principal",
        "mobile",
        "mobile phone",
        "celular",
        "numero",
        "número",
        "numero de telefono",
        "número de teléfono",
    ],
    "numero_preferencial": [
        "numero preferencial",
        "número preferencial",
        "preferred number",
        "preferred phone",
        "preferred phone number",
        "telefono preferencial",
        "teléfono preferencial",
        "telefono secundario",
        "teléfono secundario",
        "alternate phone",
        "secondary phone",
        "other phone",
    ],
    "region": [
        "region",
        "región",
        "area",
        "área",
        "market",
        "zona",
        "state",
        "estado",
        "country region",
        "region name",
    ],
}

REQUIRED_MIN = ["telefono", "numero_preferencial", "region"]

REGION_TIMEZONE_MAP = {
    # East / ET
    "new york": "ET",
    "brooklyn": "ET",
    "queens": "ET",
    "bronx": "ET",
    "manhattan": "ET",
    "staten island": "ET",
    "newark": "ET",
    "jersey city": "ET",
    "wilmington": "ET",
    "wilmington, de": "ET",
    "philadelphia": "ET",
    "pittsburgh": "ET",
    "baltimore": "ET",
    "greater washington d.c. area": "ET",
    "washington d.c.": "ET",
    "washington dc": "ET",
    "dc": "ET",
    "miami": "ET",
    "orlando": "ET",
    "tampa": "ET",
    "jacksonville": "ET",
    "atlanta": "ET",
    "charlotte": "ET",
    "raleigh": "ET",
    "detroit": "ET",
    "indianapolis": "ET",
    "columbus": "ET",
    "cleveland": "ET",
    "cincinnati": "ET",
    "louisville": "ET",
    "richmond": "ET",
    "norfolk": "ET",
    "virginia beach": "ET",
    "boston": "ET",
    "hartford": "ET",
    "buffalo": "ET",
    "rochester": "ET",
    "albany": "ET",
    "grand rapids-kalamazoo": "ET",
    "akron": "ET",
    "trenton & freehold township": "ET",
    "trenton and freehold township": "ET",
    "savannah": "ET",
    "new jersey": "ET",
    "myrtle beach": "ET",
    "lakeland-winter haven": "ET",
    "charleston": "ET",
    "yonkers/white plains": "ET",
    "yonkers white plains": "ET",
    "greenville-spartanburg": "ET",
    "altamont": "CT",
    "asheville": "ET",
    "bad axe-croswell": "ET",
    "bath-corning": "ET",
    "bristol-kingsport": "ET",
    "brunswick": "ET",
    "burlington": "ET",
    "dayton": "ET",
    "fayetteville-lumberton": "ET",
    "florence": "ET",
    "fort myers": "ET",
    "gainesville": "ET",
    "glens falls-granville": "ET",
    "greater west palm beach area": "ET",
    "west palm beach": "ET",
    "greensboro": "ET",
    "hamilton": "ET",
    "kentucky": "ET",
    "lima-findlay": "ET",
    "melbourne": "ET",
    "mount pleasant-midland": "ET",
    "ottawa": "ET",
    "pennsylvania": "ET",
    "poughkeepsie-middletown": "ET",
    "providence": "ET",
    "saginaw": "ET",
    "salisbury-seaford": "ET",
    "sterling": "ET",
    "syracuse": "ET",
    "terre haute": "ET",
    "toronto": "ET",
    "utica-rome": "ET",
    "warsaw-kilmarnock": "ET",
    "waterloo/kitchener/cambridge": "ET",
    "waterloo kitchener cambridge": "ET",
    "wilkes-barre/scranton": "ET",
    "wilkes barre scranton": "ET",
    "scranton": "ET",
    "williamsport-montgomery": "ET",
    "white plains": "ET",

    # Central / CT
    "chicago": "CT",
    "houston": "CT",
    "dallas": "CT",
    "dallas-ft. worth": "CT",
    "dallas-fort worth": "CT",
    "fort worth": "CT",
    "austin": "CT",
    "san antonio": "CT",
    "st. louis": "CT",
    "saint louis": "CT",
    "nashville": "CT",
    "memphis": "CT",
    "birmingham": "CT",
    "new orleans": "CT",
    "baton rouge": "CT",
    "omaha": "CT",
    "des moines": "CT",
    "kansas city": "CT",
    "milwaukee": "CT",
    "madison": "CT",
    "minneapolis": "CT",
    "saint paul": "CT",
    "st paul": "CT",
    "little rock": "CT",
    "oklahoma city": "CT",
    "tulsa": "CT",
    "wichita": "CT",
    "waco": "CT",
    "peoria": "CT",
    "champaign-urbana": "CT",
    "churchill": "CT",
    "columbia-jefferson city": "CT",
    "corpus christi": "CT",
    "eau claire": "CT",
    "fargo": "CT",
    "fayetteville-springdale": "CT",
    "fergus falls-alexandria": "CT",
    "lafayette-flora": "CT",
    "lubbock": "CT",
    "nacogdoches": "CT",
    "odessa-midland": "CT",
    "midland": "CT",
    "paris": "CT",
    "pensacola": "CT",
    "prairie du chien": "CT",
    "sioux falls": "CT",
    "st. cloud": "CT",
    "saint cloud": "CT",
    "waterloo-cedar falls": "CT",
    "wausau-weston": "CT",

    # Mountain / MT
    "denver": "MT",
    "colorado springs": "MT",
    "salt lake city": "MT",
    "albuquerque": "MT",
    "boise": "MT",
    "el paso": "MT",
    "cheyenne": "MT",
    "provo-orem": "MT",
    "utah": "MT",
    "st. george": "MT",
    "new mexico": "MT",
    "grand junction": "MT",
    "idaho falls": "MT",
    "ogden ut": "MT",
    "ogden": "MT",
    "richfield": "MT",
    "calgary": "MT",
    "edmonton": "MT",

    # Arizona / AZ
    "phoenix": "AZ",
    "tucson": "AZ",
    "mesa": "AZ",
    "scottsdale": "AZ",
    "tempe": "AZ",
    "prescott valley": "AZ",

    # Pacific / PT
    "greater seattle area": "PT",
    "seattle": "PT",
    "tacoma": "PT",
    "bellevue": "PT",
    "spokane": "PT",
    "portland": "PT",
    "eugene": "PT",
    "san diego": "PT",
    "los angeles": "PT",
    "orange county": "PT",
    "anaheim": "PT",
    "riverside": "PT",
    "san bernardino": "PT",
    "san francisco": "PT",
    "oakland": "PT",
    "san jose": "PT",
    "sacramento": "PT",
    "fresno": "PT",
    "las vegas": "PT",
    "vancouver": "PT",
    "grants pass-medford": "PT",
    "union gap-yakima": "PT",
    "wenatchee": "PT",
    "kitsap": "PT",
    "bellingham": "PT",
    "kennewick-richland": "PT",
    "palmdale & lancaster": "PT",
    "palmdale and lancaster": "PT",
    "stockton": "PT",
    "temecula-hemet": "PT",

    # Hawaii / HT
    "honolulu hi": "HT",
    "honolulu": "HT",
}

STATE_TIMEZONE_MAP = {
    "al": "CT", "ak": "AKT", "az": "AZ", "ar": "CT", "ca": "PT",
    "co": "MT", "ct": "ET", "de": "ET", "fl": "ET", "ga": "ET",
    "hi": "HT", "ia": "CT", "id": "MT", "il": "CT", "in": "ET",
    "ks": "CT", "ky": "ET", "la": "CT", "ma": "ET", "md": "ET",
    "me": "ET", "mi": "ET", "mn": "CT", "mo": "CT", "ms": "CT",
    "mt": "MT", "nc": "ET", "nd": "CT", "ne": "CT", "nh": "ET",
    "nj": "ET", "nm": "MT", "nv": "PT", "ny": "ET", "oh": "ET",
    "ok": "CT", "or": "PT", "pa": "ET", "ri": "ET", "sc": "ET",
    "sd": "CT", "tn": "CT", "tx": "CT", "ut": "MT", "va": "ET",
    "vt": "ET", "wa": "PT", "wi": "CT", "wv": "ET", "wy": "MT",
    "dc": "ET",
}


def leer_csv_generico(archivo):
    if not archivo:
        raise ValueError("No se recibió ningún archivo.")

    contenido = archivo.read()
    archivo.seek(0)

    if not contenido:
        raise ValueError("El archivo está vacío.")

    candidatos_encoding = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    candidatos_sep = [",", ";", "\t"]

    ultimo_error = None

    for encoding in candidatos_encoding:
        try:
            texto = contenido.decode(encoding)
        except Exception:
            continue

        for sep in candidatos_sep:
            try:
                df = pd.read_csv(io.StringIO(texto), sep=sep)
                if df is not None and len(df.columns) >= 1:
                    df.columns = [str(c).strip() for c in df.columns]
                    return df
            except Exception as e:
                ultimo_error = e

    raise ValueError(f"No se pudo interpretar el CSV: {ultimo_error}")


def leer_csv_generico(archivo):
    if not archivo:
        raise ValueError("No se recibió ningún archivo.")

    contenido = archivo.read()
    if hasattr(archivo, "seek"):
        archivo.seek(0)

    return _leer_csv_desde_bytes(contenido)


def normalizar_texto(texto):
    texto = str(texto or "").strip()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


def limpiar_valor(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def solo_digitos(valor):
    return re.sub(r"\D+", "", limpiar_valor(valor))


def nombre_columna_normalizado(columna):
    columna = normalizar_texto(columna)
    columna = re.sub(r"\s+", " ", columna)
    return columna


def resolver_columnas(df):
    columnas_originales = list(df.columns)
    columnas_normalizadas = {
        nombre_columna_normalizado(col): col for col in columnas_originales
    }

    resultado = {}

    for canonica, alias_list in ALIAS_COLUMNAS.items():
        encontrada = None

        for alias in alias_list:
            alias_norm = nombre_columna_normalizado(alias)
            if alias_norm in columnas_normalizadas:
                encontrada = columnas_normalizadas[alias_norm]
                break

        if encontrada is None:
            for col_norm, col_original in columnas_normalizadas.items():
                if any(nombre_columna_normalizado(alias) in col_norm for alias in alias_list):
                    encontrada = col_original
                    break

        resultado[canonica] = encontrada

    faltantes = [c for c in REQUIRED_MIN if not resultado.get(c)]
    return resultado, faltantes


def extraer_estado_desde_region(region):
    region_limpia = limpiar_valor(region)
    partes = [p.strip() for p in region_limpia.split(",") if p.strip()]

    if len(partes) >= 2:
        posible_estado = partes[-1].strip().lower()
        posible_estado = re.sub(r"[^a-z]", "", posible_estado)
        if len(posible_estado) == 2 and posible_estado in STATE_TIMEZONE_MAP:
            return posible_estado

    return ""


def timezone_desde_region(region):
    region_limpia = normalizar_texto(region)

    if not region_limpia:
        return "Sin asignar"

    region_limpia = region_limpia.replace("–", "-").replace("—", "-")
    region_limpia = region_limpia.replace("&", " and ")
    region_limpia = region_limpia.replace("/", " / ")
    region_limpia = re.sub(r"\s+", " ", region_limpia).strip()

    if region_limpia in REGION_TIMEZONE_MAP:
        return REGION_TIMEZONE_MAP[region_limpia]

    for clave, tz in REGION_TIMEZONE_MAP.items():
        if clave in region_limpia or region_limpia in clave:
            return tz

    estado = extraer_estado_desde_region(region_limpia)
    if estado and estado in STATE_TIMEZONE_MAP:
        return STATE_TIMEZONE_MAP[estado]

    return "Sin asignar"


def construir_link_perfil(telefono):
    telefono_limpio = solo_digitos(telefono)
    if not telefono_limpio:
        return ""
    return f"https://old.compinche.io/admin/users/{telefono_limpio}"


def telefono_llamable(row):
    telefono = row["telefono_limpio"]
    preferencial = row["preferencial_limpio"]

    if telefono:
        return telefono
    if preferencial:
        return preferencial
    return ""


def construir_clave_duplicado(row):
    principal = row["llamable"]
    if principal:
        return f"tel:{principal}"

    nombre = normalizar_texto(row["Nombre"])
    region = normalizar_texto(row["Region"])
    return f"sin_tel:{nombre}|{region}"


def obtener_agentes_configurados():
    turnos_config = cargar_turnos_fijos()
    agentes = []
    turnos_excluidos = {"Admin", "Otros"}

    for turno, lista_agentes in turnos_config.items():
        if str(turno).strip() in turnos_excluidos:
            continue

        for agente in lista_agentes:
            nombre = str(agente or "").strip()
            if nombre:
                agentes.append(nombre)

    return [""] + sorted(set(agentes), key=lambda x: x.lower())


def preparar_dataframe_usuarios(df):
    df = df.copy()
    columnas_resueltas, faltantes = resolver_columnas(df)

    if faltantes:
        raise ValueError("Faltan columnas requeridas en el CSV: " + ", ".join(faltantes))

    col_usuario = columnas_resueltas.get("usuario")
    col_telefono = columnas_resueltas["telefono"]
    col_preferencial = columnas_resueltas["numero_preferencial"]
    col_region = columnas_resueltas["region"]

    df_salida = pd.DataFrame()
    df_salida["Nombre"] = df[col_usuario].apply(limpiar_valor) if col_usuario else ""
    df_salida["Telefono"] = df[col_telefono].apply(limpiar_valor)
    df_salida["Preferido"] = df[col_preferencial].apply(limpiar_valor)
    df_salida["Region"] = df[col_region].apply(limpiar_valor)

    df_salida = df_salida[
        ~(
            (df_salida["Nombre"] == "")
            & (df_salida["Telefono"] == "")
            & (df_salida["Preferido"] == "")
            & (df_salida["Region"] == "")
        )
    ].copy()

    df_salida["telefono_limpio"] = df_salida["Telefono"].apply(solo_digitos)
    df_salida["preferencial_limpio"] = df_salida["Preferido"].apply(solo_digitos)
    df_salida["llamable"] = df_salida.apply(telefono_llamable, axis=1)

    filas_utiles = len(df_salida)
    filas_sin_nombre = int((df_salida["Nombre"] == "").sum())
    filas_sin_telefono = int((df_salida["llamable"] == "").sum())

    df_salida["Telefono"] = df_salida["telefono_limpio"]
    df_salida["Preferido"] = df_salida["preferencial_limpio"]
    df_salida["TZ"] = df_salida["Region"].apply(timezone_desde_region)
    df_salida["Perfil"] = df_salida["Telefono"].apply(construir_link_perfil)
    df_salida["Agente"] = ""
    df_salida["Contesto"] = False
    df_salida["SMS"] = False
    df_salida["Ticket"] = ""
    df_salida["Nota"] = ""

    regiones_sin_tz = sorted(
        {
            limpiar_valor(region)
            for region, tz in zip(df_salida["Region"], df_salida["TZ"])
            if tz == "Sin asignar" and limpiar_valor(region)
        }
    )

    df_salida["clave_duplicado"] = df_salida.apply(construir_clave_duplicado, axis=1)
    df_dedup = df_salida.drop_duplicates(subset=["clave_duplicado"], keep="first").copy()

    duplicados_eliminados = filas_utiles - len(df_dedup)
    usuarios_unicos_llamables = int(df_dedup["llamable"].ne("").sum())

    df_final = df_dedup[COLUMNAS_FINALES].reset_index(drop=True)

    resumen = {
        "Filas originales": int(len(df)),
        "Filas utiles": int(filas_utiles),
        "Usuarios unicos llamables": int(usuarios_unicos_llamables),
        "Filas sin nombre": int(filas_sin_nombre),
        "Filas sin telefono": int(filas_sin_telefono),
        "Duplicados eliminados": int(duplicados_eliminados),
        "Regiones sin timezone": int(len(regiones_sin_tz)),
        "Columnas finales": int(len(df_final.columns)),
    }

    return df_final, resumen, regiones_sin_tz


def respuesta_csv_desde_df(df, nombre_archivo):
    salida = io.StringIO()
    df.to_csv(salida, index=False, encoding="utf-8-sig")
    csv_texto = salida.getvalue()

    return Response(
        csv_texto,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


def enviar_a_apps_script(df, nombre_hoja):
    webhook_url = (os.getenv("APPS_SCRIPT_WEBHOOK_URL") or "").strip()
    webhook_token = (os.getenv("APPS_SCRIPT_WEBHOOK_TOKEN") or "").strip()

    if not webhook_url:
        raise RuntimeError("No está configurada la variable APPS_SCRIPT_WEBHOOK_URL.")

    if not webhook_token:
        raise RuntimeError("No está configurada la variable APPS_SCRIPT_WEBHOOK_TOKEN.")

    payload = {
        "sheet_name": nombre_hoja or "Usuarios limpiados",
        "headers": COLUMNAS_FINALES,
        "rows": df.fillna("").values.tolist(),
        "agent_options": obtener_agentes_configurados(),
        "webhook_token": webhook_token,
    }

    try:
        respuesta = requests.post(webhook_url, json=payload, timeout=(20, 180))
    except requests.exceptions.ReadTimeout:
        raise RuntimeError(
            "La creación de la hoja tardó demasiado en responder. "
            "Es posible que Google Sheets sí se haya creado en tu carpeta. "
            "Revisa Drive y, si necesitas, vuelve a intentarlo."
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"No se pudo conectar con Apps Script: {e}")

    if respuesta.status_code != 200:
        raise RuntimeError(
            f"Apps Script respondió con estado {respuesta.status_code}: {respuesta.text}"
        )

    data = respuesta.json()

    if not data.get("ok"):
        raise RuntimeError(data.get("error") or "No se pudo crear el Google Sheet.")

    return data.get("spreadsheet_url", ""), data.get("spreadsheet_name", "")


def serializar_resultado(df, resumen, regiones_sin_tz):
    serializer = URLSafeSerializer(
        current_app.secret_key,
        salt="usuarios-a-sheets-payload",
    )
    return serializer.dumps(
        {
            "df_json": df.to_json(orient="records", force_ascii=False),
            "resumen": resumen,
            "regiones_sin_tz": regiones_sin_tz,
        }
    )


def cargar_desde_payload(payload):
    if not payload:
        return None, None, []

    serializer = URLSafeSerializer(
        current_app.secret_key,
        salt="usuarios-a-sheets-payload",
    )

    try:
        item = serializer.loads(payload)
    except BadData:
        return None, None, []

    if not item or "df_json" not in item:
        return None, None, []

    df = pd.DataFrame(json.loads(item["df_json"]))
    return df, item["resumen"], item["regiones_sin_tz"]


@usuarios_a_sheets_bp.route("/usuarios-a-sheets", methods=["GET", "POST"])
def usuarios_a_sheets():
    mensaje = ""
    advertencia = ""
    tabla_previa = None
    columnas_previa = COLUMNAS_FINALES
    resumen = None
    spreadsheet_url = ""
    spreadsheet_title = ""
    regiones_sin_tz = []
    payload_cache = ""
    apps_script_configurado = bool((os.getenv("APPS_SCRIPT_WEBHOOK_URL") or "").strip())

    if request.method == "POST":
        accion = (request.form.get("accion") or "").strip()

        try:
            if accion == "analizar_csv":
                archivo = request.files.get("archivo")

                if not archivo or not archivo.filename:
                    advertencia = "Selecciona un archivo CSV."
                else:
                    df = leer_csv_generico(archivo)
                    df_final, resumen, regiones_sin_tz = preparar_dataframe_usuarios(df)
                    payload_cache = serializar_resultado(df_final, resumen, regiones_sin_tz)
                    tabla_previa = df_final.head(80).to_dict(orient="records")
                    mensaje = "CSV analizado correctamente."

            elif accion == "descargar_csv":
                payload_cache = (request.form.get(FORM_KEY_PAYLOAD) or "").strip()
                df_final, resumen, regiones_sin_tz = cargar_desde_payload(payload_cache)
                if df_final is None:
                    advertencia = "Primero analiza un CSV."
                else:
                    return respuesta_csv_desde_df(df_final, "usuarios_limpiados.csv")

            elif accion == "crear_sheet":
                nombre_hoja = (request.form.get("nombre_hoja") or "").strip()
                payload_cache = (request.form.get(FORM_KEY_PAYLOAD) or "").strip()
                df_final, resumen, regiones_sin_tz = cargar_desde_payload(payload_cache)

                if df_final is None:
                    advertencia = "Primero analiza un CSV."
                else:
                    spreadsheet_url, spreadsheet_title = enviar_a_apps_script(
                        df_final,
                        nombre_hoja=nombre_hoja or "Usuarios limpiados",
                    )
                    tabla_previa = df_final.head(80).to_dict(orient="records")
                    mensaje = "Google Sheet creado correctamente."

            elif accion == "limpiar":
                mensaje = "Se limpió la previsualización actual."

            else:
                payload_cache = (request.form.get(FORM_KEY_PAYLOAD) or "").strip()
                df_final, resumen, regiones_sin_tz = cargar_desde_payload(payload_cache)
                if df_final is not None:
                    tabla_previa = df_final.head(80).to_dict(orient="records")

        except Exception as e:
            logger.exception("Error procesando usuarios_a_sheets con accion=%s", accion)
            advertencia = f"No se pudo procesar el archivo: {e}"
            if payload_cache:
                try:
                    df_final, resumen, regiones_sin_tz = cargar_desde_payload(payload_cache)
                    if df_final is not None:
                        tabla_previa = df_final.head(80).to_dict(orient="records")
                except Exception:
                    pass

    return render_template(
        "usuarios_a_sheets.html",
        mensaje=mensaje,
        advertencia=advertencia,
        tabla_previa=tabla_previa,
        columnas_previa=columnas_previa,
        resumen=resumen,
        spreadsheet_url=spreadsheet_url,
        spreadsheet_title=spreadsheet_title,
        apps_script_configurado=apps_script_configurado,
        regiones_sin_tz=regiones_sin_tz,
        payload_cache=payload_cache,
    )
