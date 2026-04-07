import pandas as pd
from flask import Blueprint, render_template, request

from utils.archivos import extraer_agentes, leer_csv_subido
from utils.transformaciones import (
    COLUMNAS_VISIBLES,
    TRADUCCIONES,
    convertir_a_numero,
    limpiar_texto,
    segundos_a_minutos,
    validar_columnas,
)
from utils.turnos import cargar_turnos_fijos, detectar_repetidos, obtener_turno

reporte_agentes_bp = Blueprint("reporte_agentes", __name__)


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

    df_final = df[
        [
            "Turno",
            "First Name",
            "Calls",
            "Outgoing calls",
            "Missed calls",
            "Call minutes",
            "Outgoing call minutes",
            "Agente",
        ]
    ].copy()

    return df_final.rename(columns=TRADUCCIONES)


def html_tabla(df):
    if df.empty:
        return None
    return df.to_dict(orient="records")


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


def construir_resumen_turnos(df_final):
    resumen_turnos = (
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

    orden_turnos = list(cargar_turnos_fijos().keys()) + ["Sin asignar"]
    resumen_turnos["orden_turno"] = resumen_turnos["Turno"].apply(
        lambda x: orden_turnos.index(x) if x in orden_turnos else 999
    )
    resumen_turnos = resumen_turnos.sort_values(by="orden_turno").drop(columns=["orden_turno"])

    return resumen_turnos


def normalizar_serie_0_100(serie):
    serie = serie.fillna(0).astype(float)
    minimo = serie.min()
    maximo = serie.max()

    if maximo == minimo:
        return pd.Series([50.0] * len(serie), index=serie.index)

    return ((serie - minimo) / (maximo - minimo)) * 100


def construir_ranking_agentes(df_final):
    columnas_base = [
        "Agente",
        "Turno",
        "Llamadas",
        "Salientes",
        "Perdidas",
        "Mins llamadas",
        "Mins salientes",
    ]

    df_ranking = df_final[columnas_base].copy()

    agrupado = (
        df_ranking.groupby(["Agente", "Turno"], dropna=False)
        .agg(
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

    agrupado["score_llamadas"] = normalizar_serie_0_100(agrupado["Llamadas"])
    agrupado["score_salientes"] = normalizar_serie_0_100(agrupado["Salientes"])
    agrupado["score_mins_llamadas"] = normalizar_serie_0_100(agrupado["Mins llamadas"])
    agrupado["score_mins_salientes"] = normalizar_serie_0_100(agrupado["Mins salientes"])
    agrupado["score_perdidas"] = 100 - normalizar_serie_0_100(agrupado["Perdidas"])

    agrupado["Score"] = (
        agrupado["score_llamadas"] * 0.25
        + agrupado["score_salientes"] * 0.20
        + agrupado["score_mins_llamadas"] * 0.20
        + agrupado["score_mins_salientes"] * 0.20
        + agrupado["score_perdidas"] * 0.15
    ).round(2)

    columnas_salida = [
        "Agente",
        "Turno",
        "Llamadas",
        "Salientes",
        "Perdidas",
        "Mins llamadas",
        "Mins salientes",
        "Score",
    ]

    ranking = agrupado[columnas_salida].sort_values(
        by=["Score", "Llamadas", "Salientes"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    top_5_mejores = ranking.head(5).copy()
    top_5_peores = ranking.sort_values(
        by=["Score", "Perdidas"],
        ascending=[True, False],
    ).head(5).copy()

    return ranking, top_5_mejores, top_5_peores


@reporte_agentes_bp.route("/reporte-agentes", methods=["GET", "POST"])
def reporte_agentes():
    mensaje = ""
    advertencia = ""
    resumen = None
    tabla_general = None
    secciones_turnos = []
    tabla_resumen_turnos = None
    lista_agentes = []
    agentes_sin_asignar = []
    turnos_config = cargar_turnos_fijos()

    totales_tabla_general = None
    totales_resumen_turnos = None

    top_5_mejores = None
    top_5_peores = None
    columnas_ranking = [
        "Agente",
        "Turno",
        "Llamadas",
        "Salientes",
        "Perdidas",
        "Mins llamadas",
        "Mins salientes",
        "Score",
    ]

    if request.method == "POST":
        archivo = request.files.get("archivo")

        if not archivo or not archivo.filename:
            advertencia = "Selecciona un archivo CSV."
        else:
            try:
                df = leer_csv_subido(archivo)
                lista_agentes = extraer_agentes(df)

                repetidos = detectar_repetidos(turnos_config)
                if repetidos:
                    advertencia = "Estos agentes están repetidos en la configuración de turnos: " + ", ".join(repetidos)

                df_final = preparar_dataframe(df, turnos_config)

                resumen = {
                    "Agentes": int(df_final["Agente"].nunique()),
                    "Llamadas": int(df_final["Llamadas"].sum()),
                    "Salientes": int(df_final["Salientes"].sum()),
                    "Perdidas": int(df_final["Perdidas"].sum()),
                    "Mins llamadas": int(df_final["Mins llamadas"].sum()),
                    "Mins salientes": int(df_final["Mins salientes"].sum()),
                }

                df_tabla_general = df_final[COLUMNAS_VISIBLES].copy()
                tabla_general = html_tabla(df_tabla_general)
                totales_tabla_general = construir_fila_totales(df_tabla_general, COLUMNAS_VISIBLES, etiqueta="TOTAL")

                df_resumen_turnos = construir_resumen_turnos(df_final)
                tabla_resumen_turnos = html_tabla(df_resumen_turnos)

                columnas_resumen_turnos = [
                    "Turno",
                    "Agentes",
                    "Llamadas",
                    "Salientes",
                    "Perdidas",
                    "Mins llamadas",
                    "Mins salientes",
                ]
                totales_resumen_turnos = construir_fila_totales(
                    df_resumen_turnos,
                    columnas_resumen_turnos,
                    etiqueta="TOTAL",
                )

                _, df_top_5_mejores, df_top_5_peores = construir_ranking_agentes(df_final)
                top_5_mejores = html_tabla(df_top_5_mejores)
                top_5_peores = html_tabla(df_top_5_peores)

                for turno in sorted(turnos_config.keys()):
                    columnas_turno = [c for c in COLUMNAS_VISIBLES if c != "Turno"]
                    bloque = df_final[df_final["Turno"] == turno][columnas_turno].copy()
                    if not bloque.empty:
                        secciones_turnos.append(
                            {
                                "nombre": turno,
                                "filas": html_tabla(bloque),
                                "totales": construir_fila_totales(bloque, columnas_turno, etiqueta="TOTAL"),
                            }
                        )

                columnas_turno = [c for c in COLUMNAS_VISIBLES if c != "Turno"]
                bloque_sin = df_final[df_final["Turno"] == "Sin asignar"][columnas_turno].copy()
                if not bloque_sin.empty:
                    secciones_turnos.append(
                        {
                            "nombre": "Sin asignar",
                            "filas": html_tabla(bloque_sin),
                            "totales": construir_fila_totales(bloque_sin, columnas_turno, etiqueta="TOTAL"),
                        }
                    )

                agentes_configurados = set()
                for agentes in turnos_config.values():
                    for agente in agentes:
                        agentes_configurados.add(agente)

                agentes_sin_asignar = [ag for ag in lista_agentes if ag not in agentes_configurados]

                mensaje = "CSV procesado correctamente."

            except Exception as e:
                advertencia = f"No se pudo procesar el archivo: {e}"

    return render_template(
        "reporte_agentes.html",
        mensaje=mensaje,
        advertencia=advertencia,
        resumen=resumen,
        tabla_general=tabla_general,
        columnas_visibles=COLUMNAS_VISIBLES,
        secciones_turnos=secciones_turnos,
        turnos_config=turnos_config,
        agentes_sin_asignar=agentes_sin_asignar,
        tabla_resumen_turnos=tabla_resumen_turnos,
        totales_tabla_general=totales_tabla_general,
        totales_resumen_turnos=totales_resumen_turnos,
        top_5_mejores=top_5_mejores,
        top_5_peores=top_5_peores,
        columnas_ranking=columnas_ranking,
    )