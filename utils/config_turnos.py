# =========================================
# CONFIGURACION MANUAL DE TURNOS
# EDITA SOLO ESTA SECCION CUANDO NECESITES
# AGREGAR, QUITAR O MOVER AGENTES
# =========================================

TURNOS_FIJOS = {
    "Oficina": [
        "Abrahan",
        "Alejandro",
        "Alvaro",
        "Andreina",
        "Diego",
        "Eva",
        "Genessis Marin",
        "Homero",
        "Jolmarys",
        "Oscar Chirino",
    ],
    "Madrugada": [
        "Caridad",
        "Maria",
        "Mariana",
        "Nathali",
    ],
    "Media noche": [
        "Antonio",
        "Francis",
        "Nicolas",
    ],
    "Tarde/Noche": [
        "Alex",
        "Camila Paez",
        "Luis",
        "Mary",
        "Maykro",
        "Michael",
        "Minerva",
        "Moises",
        "Paola",
        "Roberth",
        "Rolmer",
        "Simeon",
    ],
    "Admin": [
        "Andrea",
        "Angelo Gerrvasi",
        "Compinche",
        "Daniel",
        "Diana",
        "Erick",
        "Isabel",
        "Josue",
        "Karlos",
        "Leopoldo",
        "Nadia",
        "Rene",
        "Thiago",
    ],
    "Ventas": [
        "Ana",
        "Augusto",
        "Jeimy",
        "Julio",
        "Simon",
        "Valentina",
        "Zahra",
    ],
    "Shift Leaders": [
        "Adriana",
        "Gaby",
        "Victoria",
    ],
    "Otros": [
        "Edilson",
        "Miguel",
    ],
}


def obtener_turnos_fijos():
    return TURNOS_FIJOS