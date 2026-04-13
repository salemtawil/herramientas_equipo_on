import io
import logging
import os
import re
import unicodedata

import pandas as pd
from flask import Blueprint, Response, render_template, request

from utils.archivos import leer_csv_subido
from utils.transformaciones import (
    convertir_a_numero,
    limpiar_texto,
    segundos_a_minutos,
    validar_columnas,
)
from utils.turnos import cargar_turnos_fijos, obtener_turno

comparar_csv_bp = Blueprint("comparar_csv", __name__)
logger = logging.getLogger(__name__)
MAX_FILAS_VISTA_PREVIA = 500

# Turnos que NO deben aparecer en la comparativa
TURNOS_EXCLUIDOS_COMPARATIVA = [
    "Admin",
    "Otros",
]

# Si luego quieres excluir agentes específicos además del turno, agrégalos aquí
AGENTES_EXCLUIDOS_COMPARATIVA = [
    # "Nombre Apellido",
]

# Alias de meses que se reconocerán dentro del nombre del archivo.
# El valor es el nombre que se mostrará en la columna.
MESES_ALIAS = {
    "enero": "enero",
    "ene": "enero",
    "january": "january",
    "jan": "january",

    "febrero": "febrero",
    "feb": "febrero",
    "february": "february",

    "marzo": "marzo",
    "mar": "marzo",
    "march": "march",

    "abril": "abril",
    "abr": "abril",
    "april": "april",
    "apr": "april",

    "mayo": "mayo",
    "may": "may",

    "junio": "junio",
    "jun": "junio",
    "june": "june",

    "julio": "julio",
    "jul": "julio",
    "july": "july",

    "agosto": "agosto",
    "ago": "agosto",
    "augosto": "agosto",
    "august": "august",
    "aug": "august",

    "septiembre": "septiembre",
    "setiembre": "septiembre",
    "sep": "septiembre",
    "sept": "septiembre",
    "september": "september",

    "octubre": "octubre",
    "oct": "octubre",
    "october": "october",

    "noviembre": "noviembre",
    "nov": "noviembre",
    "november": "november",

    "diciembre": "diciembre",
    "dic": "diciembre",
    "december": "december",
    "dec": "december",
}


def quitar_acentos(texto):
    texto = str(texto or "")
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def detectar_mes_en_nombre_archivo(nombre_archivo):
    nombre_limpio = quitar_acentos(os.path.basename(nombre_archivo or "")).lower()

    # Ordenar de mayor a menor evita que "mar" gane antes que "march", etc.
    aliases_ordenados = sorted(MESES_ALIAS.items(), key=lambda x: len(x[0]), reverse=True)

    for alias, etiqueta in aliases_ordenados:
        patron = rf"(?<![a-z]){re.escape(alias)}(?![a-z])"
        if re.search(patron, nombre_limpio):
            return etiqueta

    return None


def etiqueta_desde_nombre_archivo(nombre_archivo, fallback):
    mes = detectar_mes_en_nombre_archivo(nombre_archivo)
    return mes if mes else fallback


def preparar_dataframe(df, turnos_config):
    df = df.copy()
    df = validar_columnas(df)

    df["First Name"] = df["First Name"].apply(limpiar_texto)
    df["Last Name"] = df["Last Name"].apply(limpiar_texto)
    df["Agente"] = (df["First Name"] + " " + df["Last Name"]).str.strip()

    for col in ["Calls", "Outgoing calls", "Missed calls", "Call seconds", "Outgoing call seconds"]:
        df[col] = convertir_a_numero(df[col])

    df["Call minutes"] = df["Call seconds"].apply(segundos_a_minutos)
    df["Outgoing call minutes"] = df["Outgoing call seconds"].apply(segundos_a_minutos)
    df["Turno"] = df["Agente"].apply(lambda nombre: obtener_turno(nombre, turnos_config))

    return df[
        [
            "Agente",
            "Turno",
            "Calls",
            "Outgoing calls",
            "Missed calls",
            "Call minutes",
            "Outgoing call minutes",
        ]
    ].rename(
        columns={
            "Calls": "Llamadas",
            "Outgoing calls": "Salientes",
            "Missed calls": "Perdidas",
            "Call minutes": "Mins llamadas",
            "Outgoing call minutes": "Mins salientes",
        }
    )


def filtrar_agentes_excluidos(df_final):
    if df_final is None or df_final.empty:
        return df_final

    df_filtrado = df_final.copy()

    if TURNOS_EXCLUIDOS_COMPARATIVA:
        df_filtrado = df_filtrado[~df_filtrado["Turno"].isin(TURNOS_EXCLUIDOS_COMPARATIVA)]

    if AGENTES_EXCLUIDOS_COMPARATIVA:
        df_filtrado = df_filtrado[~df_filtrado["Agente"].isin(AGENTES_EXCLUIDOS_COMPARATIVA)]

    return df_filtrado


def resumir_por_agente(df_final):
    return (
        df_final.groupby("Agente", dropna=False)
        .agg(
            Turno=("Turno", "first"),
            Llamadas=("Llamadas", "sum"),
            Salientes=("Salientes", "sum"),
            Perdidas=("Perdidas", "sum"),
            **{
                "Mins llamadas": ("Mins llamadas", "sum"),
                "Mins salientes": ("Mins salientes", "sum"),
            }
        )
        .reset_index()
    )


def resumir_por_turno(df_final):
    return (
        df_final.groupby("Turno", dropna=False)
        .agg(
            Agentes=("Agente", "nunique"),
            Llamadas=("Llamadas", "sum"),
            Salientes=("Salientes", "sum"),
            Perdidas=("Perdidas", "sum"),
            **{
                "Mins llamadas": ("Mins llamadas", "sum"),
                "Mins salientes": ("Mins salientes", "sum"),
            }
        )
        .reset_index()
    )


def calcular_variacion_porcentual(valor_base, valor_actual):
    valor_base = float(valor_base or 0)
    valor_actual = float(valor_actual or 0)

    if valor_base == 0 and valor_actual == 0:
        return 0.0
    if valor_base == 0 and valor_actual != 0:
        return 100.0

    return round(((valor_actual - valor_base) / valor_base) * 100, 2)


def construir_comparativa(df_base_final, df_actual_final, etiqueta_base="base", etiqueta_actual="comparar"):
    base = resumir_por_agente(df_base_final).copy()
    actual = resumir_por_agente(df_actual_final).copy()

    metricas = [
        ("Llamadas", f"Llamadas {etiqueta_base}", f"Llamadas {etiqueta_actual}", "Dif. llamadas", "% llamadas"),
        ("Salientes", f"Salientes {etiqueta_base}", f"Salientes {etiqueta_actual}", "Dif. salientes", "% salientes"),
        ("Perdidas", f"Perdidas {etiqueta_base}", f"Perdidas {etiqueta_actual}", "Dif. perdidas", "% perdidas"),
        (
            "Mins llamadas",
            f"Mins llamadas {etiqueta_base}",
            f"Mins llamadas {etiqueta_actual}",
            "Dif. mins llamadas",
            "% mins llamadas",
        ),
        (
            "Mins salientes",
            f"Mins salientes {etiqueta_base}",
            f"Mins salientes {etiqueta_actual}",
            "Dif. mins salientes",
            "% mins salientes",
        ),
    ]

    comparativa = pd.merge(
        base,
        actual,
        on="Agente",
        how="outer",
        suffixes=("_base", "_actual"),
    ).fillna(0)

    df_final = pd.DataFrame()
    df_final["Agente"] = comparativa["Agente"]

    for metrica, nombre_base, nombre_actual, nombre_diff, nombre_pct in metricas:
        col_base = f"{metrica}_base"
        col_actual = f"{metrica}_actual"

        df_final[nombre_base] = comparativa[col_base]
        df_final[nombre_actual] = comparativa[col_actual]
        df_final[nombre_diff] = comparativa[col_actual] - comparativa[col_base]
        df_final[nombre_pct] = comparativa.apply(
            lambda fila: calcular_variacion_porcentual(fila[col_base], fila[col_actual]),
            axis=1,
        )

    return df_final.sort_values(by="Agente").reset_index(drop=True)


def construir_comparativa_turnos(df_base_final, df_actual_final, etiqueta_base="base", etiqueta_actual="comparar"):
    base = resumir_por_turno(df_base_final).copy()
    actual = resumir_por_turno(df_actual_final).copy()

    metricas = [
        ("Llamadas", f"Llamadas {etiqueta_base}", f"Llamadas {etiqueta_actual}", "Dif. llamadas", "% llamadas"),
        ("Salientes", f"Salientes {etiqueta_base}", f"Salientes {etiqueta_actual}", "Dif. salientes", "% salientes"),
        ("Perdidas", f"Perdidas {etiqueta_base}", f"Perdidas {etiqueta_actual}", "Dif. perdidas", "% perdidas"),
        (
            "Mins llamadas",
            f"Mins llamadas {etiqueta_base}",
            f"Mins llamadas {etiqueta_actual}",
            "Dif. mins llamadas",
            "% mins llamadas",
        ),
        (
            "Mins salientes",
            f"Mins salientes {etiqueta_base}",
            f"Mins salientes {etiqueta_actual}",
            "Dif. mins salientes",
            "% mins salientes",
        ),
    ]

    comparativa = pd.merge(
        base,
        actual,
        on="Turno",
        how="outer",
        suffixes=("_base", "_actual"),
    ).fillna(0)

    orden_turnos = list(cargar_turnos_fijos().keys()) + ["Sin asignar"]

    df_final = pd.DataFrame()
    df_final["Turno"] = comparativa["Turno"]

    for metrica, nombre_base, nombre_actual, nombre_diff, nombre_pct in metricas:
        col_base = f"{metrica}_base"
        col_actual = f"{metrica}_actual"

        df_final[nombre_base] = comparativa[col_base]
        df_final[nombre_actual] = comparativa[col_actual]
        df_final[nombre_diff] = comparativa[col_actual] - comparativa[col_base]
        df_final[nombre_pct] = comparativa.apply(
            lambda fila: calcular_variacion_porcentual(fila[col_base], fila[col_actual]),
            axis=1,
        )

    df_final["orden_turno"] = df_final["Turno"].apply(
        lambda x: orden_turnos.index(x) if x in orden_turnos else 999
    )
    df_final = df_final.sort_values(by=["orden_turno", "Turno"]).drop(columns=["orden_turno"]).reset_index(drop=True)

    return df_final


def construir_fila_totales(df, columnas, etiqueta="TOTAL"):
    fila_total = {}

    if df is None or df.empty:
        for i, col in enumerate(columnas):
            fila_total[col] = etiqueta if i == 0 else ""
        return fila_total

    for i, col in enumerate(columnas):
        if i == 0:
            fila_total[col] = etiqueta
        elif col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            total = df[col].fillna(0).sum()
            fila_total[col] = int(total) if float(total).is_integer() else round(total, 2)
        else:
            fila_total[col] = ""

    return fila_total


def respuesta_csv_desde_df(df, nombre_archivo):
    salida = io.StringIO()
    df.to_csv(salida, index=False, encoding="utf-8-sig")
    csv_texto = salida.getvalue()

    return Response(
        csv_texto,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nombre_archivo}"},
    )


def tabla_preview(df):
    if df is None or df.empty:
        return None
    return df.head(MAX_FILAS_VISTA_PREVIA).to_dict(orient="records")


@comparar_csv_bp.route("/comparar-csv", methods=["GET", "POST"])
def comparar_csv():
    mensaje = ""
    advertencia = ""

    tabla_comparativa_turnos = None
    columnas_comparativa_turnos = None
    totales_comparativa_turnos = None

    tabla_comparativa = None
    columnas_comparativa = None
    totales_comparativa = None

    if request.method == "POST":
        accion = request.form.get("accion", "comparar_csv")
        archivo_base = request.files.get("archivo_base")
        archivo_actual = request.files.get("archivo_actual")
        turnos_config = cargar_turnos_fijos()

        try:
            if not archivo_base or not archivo_base.filename or not archivo_actual or not archivo_actual.filename:
                advertencia = "Debes cargar el CSV base y el CSV a comparar."
            else:
                etiqueta_base = etiqueta_desde_nombre_archivo(archivo_base.filename, "base")
                etiqueta_actual = etiqueta_desde_nombre_archivo(archivo_actual.filename, "comparar")

                df_base = leer_csv_subido(archivo_base)
                df_actual = leer_csv_subido(archivo_actual)

                df_base_final = preparar_dataframe(df_base, turnos_config)
                df_actual_final = preparar_dataframe(df_actual, turnos_config)

                df_base_final = filtrar_agentes_excluidos(df_base_final)
                df_actual_final = filtrar_agentes_excluidos(df_actual_final)

                df_tabla_comparativa_turnos = construir_comparativa_turnos(
                    df_base_final,
                    df_actual_final,
                    etiqueta_base=etiqueta_base,
                    etiqueta_actual=etiqueta_actual,
                )
                columnas_comparativa_turnos = list(df_tabla_comparativa_turnos.columns)
                tabla_comparativa_turnos = tabla_preview(df_tabla_comparativa_turnos)
                totales_comparativa_turnos = construir_fila_totales(
                    df_tabla_comparativa_turnos,
                    columnas_comparativa_turnos,
                    etiqueta="TOTAL",
                )

                df_tabla_comparativa = construir_comparativa(
                    df_base_final,
                    df_actual_final,
                    etiqueta_base=etiqueta_base,
                    etiqueta_actual=etiqueta_actual,
                )
                columnas_comparativa = list(df_tabla_comparativa.columns)
                tabla_comparativa = tabla_preview(df_tabla_comparativa)
                totales_comparativa = construir_fila_totales(
                    df_tabla_comparativa,
                    columnas_comparativa,
                    etiqueta="TOTAL",
                )

                if accion == "descargar_comparativa":
                    return respuesta_csv_desde_df(df_tabla_comparativa, "comparativa_agentes.csv")

                mensaje = "Comparativa generada correctamente."
                if len(df_tabla_comparativa) > MAX_FILAS_VISTA_PREVIA:
                    mensaje += f" Mostrando las primeras {MAX_FILAS_VISTA_PREVIA} filas en la vista previa."

        except Exception as e:
            logger.exception("Error procesando comparar_csv con accion=%s", accion)
            advertencia = f"No se pudo procesar el archivo: {e}"

    return render_template(
        "comparar_csv.html",
        mensaje=mensaje,
        advertencia=advertencia,
        tabla_comparativa_turnos=tabla_comparativa_turnos,
        columnas_comparativa_turnos=columnas_comparativa_turnos,
        totales_comparativa_turnos=totales_comparativa_turnos,
        tabla_comparativa=tabla_comparativa,
        columnas_comparativa=columnas_comparativa,
        totales_comparativa=totales_comparativa,
    )
