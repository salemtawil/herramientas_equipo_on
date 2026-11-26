"""Reglas puras de mala atención para Incidencias de chats (sin red ni IA)."""

import re
import unicodedata

from utils.auditoria_chats_transcripcion import (
    MENSAJE_ENTRANTE,
    MENSAJE_SALIENTE,
    _asignado_a,
    _es_cliente,
    _mismo_nombre,
    _ordenados,
    _texto,
    _ts_mensaje,
    anonimizar,
    es_llamada,
)

REGLAS_VERSION = "1"
PRIMERA_RESPUESTA_MAX = 600
ESPERA_MAX = 900
IGNORADO_MENSAJES = 3
IGNORADO_SEGUNDOS = 600
SIN_ATENCION_ESPERA = 600

ETIQUETAS = {
    "sin_atencion": ("Sin atención", "alta"),
    "cierre_sin_responder": ("Cierre sin responder", "alta"),
    "cliente_ignorado": ("Cliente ignorado", "media"),
    "primera_respuesta_tardia": ("Primera respuesta tardía", "media"),
    "espera_larga": ("Espera larga", "media"),
    "frustracion": ("Frustración del cliente", "media"),
    "csat_bajo": ("CSAT bajo", "media"),
}
SIN_ASIGNAR = "Sin asignar"
MAX_CITA = 120
MAX_EVIDENCIA = 200
CSAT_BAJO_MAX = 2

# BORRADOR: validar con el equipo
CATEGORIAS_CLIENTE = {
    "cobros": {
        "etiqueta": "Cobros",
        "severidad": "alta",
        "frases": ("me cobraron dos veces", "cobro doble", "cobro indebido", "reembolso", "devolucion de dinero"),
    },
    "fallas_app": {
        "etiqueta": "Fallas de la app",
        "severidad": "media",
        "frases": ("no funciona", "me sale error", "se cierra la app", "no carga", "se cae"),
    },
    "no_recibido": {
        "etiqueta": "No recibido",
        "severidad": "media",
        "frases": ("no me llego", "no recibi", "no se acredito", "sigue pendiente"),
    },
    "acceso_cuenta": {
        "etiqueta": "Acceso a la cuenta",
        "severidad": "media",
        "frases": ("no puedo entrar", "cuenta bloqueada", "no me llega el codigo"),
    },
    "reclamo_formal": {
        "etiqueta": "Reclamo formal",
        "severidad": "alta",
        "frases": ("reclamo", "denuncia", "demanda", "defensa del consumidor"),
    },
}
FRASES_FRUSTRACION = (
    "nadie me responde",
    "pesima atencion",
    "hablar con un supervisor",
    "no me ayudan",
    "muy mal servicio",
)
# Palabras de cortesía o cierre: un mensaje que solo las contiene no es un reclamo sin responder.
PALABRAS_CORTESIA = frozenset(
    "gracias muchas muchisimas mil ok okey okay listo perfecto dale genial excelente bueno vale chao adios".split()
)


def es_respuesta_humana(mensaje):
    """Saliente, público, con texto y escrito por un usuario (no bot, captain ni sin remitente)."""
    if mensaje.get("message_type") != MENSAJE_SALIENTE or mensaje.get("private") or not _texto(mensaje):
        return False
    sender = mensaje.get("sender")
    tipo = mensaje.get("sender_type") or (sender.get("type") if isinstance(sender, dict) else None)
    return str(tipo or "").strip().lower() == "user"


def agente_en(mensajes, ts, conversacion):
    """Agente a cargo en el instante `ts`: última asignación previa, o el asignado actual."""
    nombre = None
    for mensaje in _ordenados(mensajes):
        if _ts_mensaje(mensaje) >= ts:
            break
        asignado = _asignado_a(mensaje)
        if asignado:
            nombre = asignado

    assignee = ((conversacion or {}).get("meta") or {}).get("assignee") or {}
    assignee = assignee if isinstance(assignee, dict) else {}
    if not nombre:
        nombre = assignee.get("name")
    if not nombre:
        return {"id": None, "nombre": SIN_ASIGNAR}

    agente_id = None
    for mensaje in mensajes or []:
        sender = mensaje.get("sender")
        if es_respuesta_humana(mensaje) and isinstance(sender, dict) and _mismo_nombre(sender.get("name"), nombre):
            agente_id = sender.get("id")
            break
    if agente_id is None and _mismo_nombre(assignee.get("name"), nombre):
        agente_id = assignee.get("id")
    return {"id": agente_id, "nombre": nombre}


def _normalizar_con_mapa(texto):
    """Texto normalizado y, para cada carácter, su posición en el texto original."""
    texto = str(texto or "")
    letras, mapa, espacio = [], [], False
    for i, caracter in enumerate(texto):
        base = "".join(c for c in unicodedata.normalize("NFD", caracter.lower()) if not unicodedata.combining(c))
        for c in base:
            if c.isspace():
                if letras and not espacio:
                    letras.append(" ")
                    mapa.append(i)
                espacio = True
            else:
                letras.append(c)
                mapa.append(i)
                espacio = False
    if letras and letras[-1] == " ":
        letras.pop()
        mapa.pop()
    return "".join(letras), mapa


def normalizar(texto):
    """Minúsculas, sin tildes y con espacios colapsados."""
    return _normalizar_con_mapa(texto)[0]


def _limpio(texto):
    return " ".join(anonimizar(texto).split())


def fragmento(texto, inicio, fin, maximo=MAX_EVIDENCIA):
    """Texto anonimizado centrado en texto[inicio:fin], con «…» donde se corta."""
    texto = str(texto or "")
    antes, centro, despues = _limpio(texto[:inicio]), _limpio(texto[inicio:fin])[:maximo], _limpio(texto[fin:])
    if antes and texto[:inicio][-1:].isspace():
        antes += " "
    if despues and texto[fin:][:1].isspace():
        despues = " " + despues
    margen = max(maximo - len(centro), 0)
    # Cada «…» ocupa un carácter del presupuesto; se reparte el contexto a ambos lados.
    izquierda = min(len(antes), margen // 2)
    derecha = min(len(despues), margen - izquierda)
    izquierda = min(len(antes), margen - derecha)
    while izquierda + derecha + len(centro) + (izquierda < len(antes)) + (derecha < len(despues)) > maximo:
        if derecha >= izquierda and derecha:
            derecha -= 1
        elif izquierda:
            izquierda -= 1
        else:
            break
    izq = antes[len(antes) - izquierda:] if izquierda else ""
    der = despues[:derecha]
    return ("…" if izquierda < len(antes) else "") + (izq + centro + der).strip() + ("…" if derecha < len(despues) else "")


def _incidencia(clave, evidencia, mensaje, mensajes, conversacion, tipo="atencion", coincidencia="", etiqueta=None, severidad=None):
    if etiqueta is None:
        etiqueta, severidad = ETIQUETAS[clave]
    ts = _ts_mensaje(mensaje)
    agente = agente_en(mensajes, ts, conversacion)
    return {
        "tipo": tipo,
        "clave": clave,
        "etiqueta": etiqueta,
        "severidad": severidad,
        "evidencia": evidencia,
        "coincidencia": coincidencia,
        "mensaje_id": mensaje.get("id"),
        "ts": ts,
        "agente_id": agente["id"],
        "agente_nombre": agente["nombre"],
        "origen": "reglas",
    }


def _cita(mensaje):
    texto = fragmento(_texto(mensaje), 0, 0, MAX_CITA)
    return f"«{texto}»" if texto else "un mensaje sin texto"


def es_cortesia(mensaje):
    """Mensaje del cliente que solo agradece o se despide (palabras de cortesía, emojis, signos)."""
    texto = _texto(mensaje)
    if not texto:
        return False
    return all(palabra in PALABRAS_CORTESIA for palabra in re.findall(r"[a-z0-9]+", normalizar(texto)))


def _minutos(segundos):
    return int(segundos // 60)


def reglas_atencion(mensajes, conversacion, ahora):
    conversacion = conversacion or {}
    ordenados = _ordenados(mensajes)
    if es_llamada(ordenados):
        return []

    # Solo cuentan los mensajes públicos del cliente y las respuestas humanas.
    eventos = [m for m in ordenados if _es_cliente(m) or es_respuesta_humana(m)]
    clientes = [m for m in eventos if m.get("message_type") == MENSAJE_ENTRANTE]
    if not clientes:
        return []

    abierto = str(conversacion.get("status") or "") != "resolved"
    resuelto = str(conversacion.get("status") or "") == "resolved"
    incidencias = []

    def agregar(clave, evidencia, mensaje):
        incidencias.append(_incidencia(clave, evidencia, mensaje, ordenados, conversacion))

    primero = clientes[0]
    if not any(es_respuesta_humana(m) for m in eventos):
        # Sin ninguna respuesta humana solo se marca sin_atencion, que absorbe las demás reglas.
        espera = ahora - _ts_mensaje(primero)
        if resuelto or (abierto and espera > SIN_ATENCION_ESPERA):
            if resuelto:
                evidencia = f"Chat cerrado sin respuesta de un agente. Cliente: {_cita(primero)}"
            else:
                evidencia = f"Cliente esperando {_minutos(espera)} min sin respuesta de un agente"
            agregar("sin_atencion", evidencia, primero)
        return incidencias

    # Esperas: del primer mensaje sin responder hasta la siguiente respuesta humana.
    esperas = []
    ignorado = None
    pendientes = []
    for mensaje in eventos:
        if mensaje.get("message_type") == MENSAJE_ENTRANTE:
            pendientes.append(mensaje)
            continue
        if pendientes:
            duracion = _ts_mensaje(mensaje) - _ts_mensaje(pendientes[0])
            esperas.append((duracion, pendientes[0]))
            if ignorado is None and len(pendientes) >= IGNORADO_MENSAJES and duracion >= IGNORADO_SEGUNDOS:
                ignorado = (duracion, pendientes[0], len(pendientes))
        pendientes = []

    if pendientes:
        if abierto:
            duracion = ahora - _ts_mensaje(pendientes[0])
            esperas.append((duracion, pendientes[0]))
            if ignorado is None and len(pendientes) >= IGNORADO_MENSAJES and duracion >= IGNORADO_SEGUNDOS:
                ignorado = (duracion, pendientes[0], len(pendientes))
        else:
            # Cerrado: el tramo final lo cubre cierre_sin_responder (sin duplicarlo con cliente_ignorado)
            # y los agradecimientos o despedidas finales no cuentan como un reclamo sin responder.
            sustantivos = [m for m in pendientes if not es_cortesia(m)]
            if sustantivos:
                agregar("cierre_sin_responder", f"El chat se cerró sin responder a {_cita(sustantivos[-1])}", sustantivos[-1])

    if ignorado:
        duracion, mensaje, cantidad = ignorado
        agregar("cliente_ignorado", f"{cantidad} mensajes del cliente sin respuesta en {_minutos(duracion)} min", mensaje)

    primera = next((m for m in eventos if es_respuesta_humana(m) and _ts_mensaje(m) >= _ts_mensaje(primero)), None)
    if primera:
        segundos = _ts_mensaje(primera) - _ts_mensaje(primero)
        if segundos > PRIMERA_RESPUESTA_MAX:
            agregar("primera_respuesta_tardia", f"Primera respuesta a los {_minutos(segundos)} min", primero)

    largas = [e for e in esperas if e[0] > ESPERA_MAX]
    if largas:
        duracion, mensaje = max(largas, key=lambda e: e[0])
        agregar("espera_larga", f"Espera de {_minutos(duracion)} min sin respuesta", mensaje)

    return incidencias


def _buscar(normal, mapa, original, frases):
    """Primera frase hallada en el texto normalizado: (evidencia, coincidencia) sobre el original."""
    hallazgos = [(normal.find(f), f) for f in frases if f in normal]
    if not hallazgos:
        return None
    pos, frase = min(hallazgos)
    inicio, fin = mapa[pos], mapa[pos + len(frase) - 1] + 1
    return fragmento(original, inicio, fin), _limpio(original[inicio:fin])


def reglas_cliente(mensajes, conversacion):
    """Reportes concretos del cliente (cobros, fallas...) y frustración; una por categoría y por chat."""
    pendientes = dict(CATEGORIAS_CLIENTE)
    buscar_frustracion = True
    incidencias = []
    ordenados = _ordenados(mensajes)
    for mensaje in ordenados:
        if not _es_cliente(mensaje):
            continue
        original = _texto(mensaje)
        normal, mapa = _normalizar_con_mapa(original)
        for clave in list(pendientes):
            categoria = pendientes[clave]
            hallazgo = _buscar(normal, mapa, original, categoria["frases"])
            if hallazgo:
                del pendientes[clave]
                incidencias.append(_incidencia(
                    clave, hallazgo[0], mensaje, ordenados, conversacion, tipo="cliente",
                    coincidencia=hallazgo[1], etiqueta=categoria["etiqueta"], severidad=categoria["severidad"],
                ))
        if buscar_frustracion:
            hallazgo = _buscar(normal, mapa, original, FRASES_FRUSTRACION)
            if hallazgo:
                buscar_frustracion = False
                incidencias.append(_incidencia("frustracion", hallazgo[0], mensaje, ordenados, conversacion, coincidencia=hallazgo[1]))
    return incidencias


def regla_csat(puntuacion, conversacion, mensajes):
    if puntuacion is None or not 1 <= puntuacion <= CSAT_BAJO_MAX:
        return []
    ordenados = _ordenados(mensajes)
    ultimo = ordenados[-1] if ordenados else {}
    return [_incidencia("csat_bajo", f"CSAT {puntuacion}/5", ultimo, ordenados, conversacion)]


def evaluar_chat(mensajes, conversacion, ahora, csat=None):
    conversacion = conversacion or {}
    agente = agente_en(mensajes, ahora, conversacion)
    resultado = {
        "descartado": None,
        "incidencias": [],
        "resuelto": str(conversacion.get("status") or "") == "resolved",
        "agente_id": agente["id"],
        "agente_nombre": agente["nombre"],
    }
    if es_llamada(mensajes):
        resultado["descartado"] = "llamada"
    elif not any(_es_cliente(m) for m in mensajes or []):
        resultado["descartado"] = "sin_cliente"
    else:
        resultado["incidencias"] = (
            reglas_atencion(mensajes, conversacion, ahora)
            + reglas_cliente(mensajes, conversacion)
            + regla_csat(csat, conversacion, mensajes)
        )
    return resultado
