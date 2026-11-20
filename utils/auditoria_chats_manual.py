"""Manual de procedimientos para la auditoría de chats: corte por secciones y selección por chat.

El texto del manual es de uso interno: se guarda en Supabase y solo lo lee el backend.
"""

import os
import re

from utils.auditoria_chats_rubrica import PROCEDIMIENTOS, SECCIONES_GENERALES

VERSION_MANUAL_DEFAULT = "3.0"
TOPE_MANUAL = 30000
DEPARTAMENTOS_AUDITABLES = ("1", "4")  # Customer Service y Finanzas

_RE_ENTRADA_INDICE = re.compile(
    r"(\d+(?:\.\d+)+)\.?\s+(.+?)\s+(\d{1,3})(?=\s+\d+(?:\.\d+)+\.?\s|\s*$)"
)
_RE_CORTE_TITULO = re.compile(r"\s\d{1,3}\s+(?=\d+\.|[A-ZÁÉÍÓÚÑ¿])")
_RE_FIN_BLOQUE = re.compile(r"\s\d\.\s+Departamento\s+de\s|\sRecursos\s+Audiovisuales\b")
MIN_ENTRADAS_INDICE = 3


def version_manual():
    return (os.getenv("AUDITORIA_CHATS_MANUAL_VERSION") or "").strip() or VERSION_MANUAL_DEFAULT


def _normalizar(texto):
    return " ".join(str(texto or "").split())


def _entradas_indice(texto):
    entradas = []
    for codigo, titulo, _ in _RE_ENTRADA_INDICE.findall(_normalizar(texto)):
        titulo = _RE_CORTE_TITULO.split(titulo)[0].strip()
        entradas.append((codigo, titulo))
    return entradas


def _paginas_indice(paginas):
    inicio = next((i for i, p in enumerate(paginas) if "ÍNDICE" in str(p).upper()), None)
    if inicio is None:
        return []
    indices = [inicio]
    for i in range(inicio + 1, len(paginas)):
        if len(_entradas_indice(paginas[i])) < MIN_ENTRADAS_INDICE:
            break
        indices.append(i)
    return indices


def cortar_manual(paginas):
    """Divide el texto (una cadena por página) en secciones {codigo, titulo, texto, orden}.

    Los títulos salen del índice; en el cuerpo cada encabezado se busca en orden, después del
    anterior, para no confundirlo con referencias cruzadas. Solo se conservan Customer Service
    y Finanzas.
    """
    indices = _paginas_indice(paginas)
    if not indices:
        raise ValueError("No se encontró el índice del manual.")
    entradas = []
    for i in indices:
        entradas.extend(_entradas_indice(paginas[i]))
    entradas = [(c, t) for c, t in entradas if c.split(".")[0] in DEPARTAMENTOS_AUDITABLES]
    cuerpo = " " + _normalizar(" ".join(str(p) for p in paginas[indices[-1] + 1 :])) + " "

    encontrados, posicion = [], 0
    for codigo, titulo in entradas:
        exige_punto = titulo.endswith(".")
        patron = re.escape(codigo) + r"\.?\s+" + re.escape(titulo.rstrip(".")) + (r"\." if exige_punto else r"\.?")
        coincidencia = re.compile(patron, re.IGNORECASE).search(cuerpo, posicion)
        if not coincidencia:
            continue
        encontrados.append((codigo, titulo.rstrip("."), coincidencia.start(), coincidencia.end()))
        posicion = coincidencia.end()

    secciones = []
    for orden, (codigo, titulo, _, fin_titulo) in enumerate(encontrados):
        fin = encontrados[orden + 1][2] if orden + 1 < len(encontrados) else len(cuerpo)
        corte = _RE_FIN_BLOQUE.search(cuerpo, fin_titulo, fin)
        if corte:
            fin = corte.start()
        secciones.append({"codigo": codigo, "titulo": titulo, "texto": cuerpo[fin_titulo:fin].strip(), "orden": orden})
    return secciones


def expandir_codigos(codigos, disponibles):
    """Un código padre («1.7») trae también sus subsecciones, en el orden del manual."""
    salida = []
    for codigo in codigos:
        for disponible in disponibles:
            if (disponible == codigo or disponible.startswith(codigo + ".")) and disponible not in salida:
                salida.append(disponible)
    return salida


def codigos_para(clasificacion, disponibles):
    """Códigos agrupados por prioridad: generales, procedimientos y extra (sin repetir)."""
    generales = expandir_codigos(SECCIONES_GENERALES, disponibles)
    procedimientos = []
    for codigo in (clasificacion or {}).get("procedimientos") or []:
        procedimientos.extend(PROCEDIMIENTOS.get(codigo, ("", []))[1])
    procedimientos = [c for c in expandir_codigos(procedimientos, disponibles) if c not in generales]
    extra = [
        c
        for c in expandir_codigos((clasificacion or {}).get("secciones_extra") or [], disponibles)
        if c not in generales and c not in procedimientos
    ]
    return generales, procedimientos, extra


def seleccionar_secciones(clasificacion, secciones, tope=TOPE_MANUAL):
    """Secciones a enviar a la IA dentro del tope: se recortan primero las extra, luego los
    procedimientos desde el final; las generales nunca."""
    por_codigo = {s["codigo"]: s for s in secciones}
    generales, procedimientos, extra = codigos_para(clasificacion, [s["codigo"] for s in secciones])

    def largo(codigos):
        return sum(len(por_codigo[c].get("texto") or "") for c in codigos)

    while extra and largo(generales + procedimientos + extra) > tope:
        extra.pop()
    while procedimientos and largo(generales + procedimientos) > tope:
        procedimientos.pop()
    return [por_codigo[c] for c in generales + procedimientos + extra]
