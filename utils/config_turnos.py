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
        "Simeon",
        "Diego",
        "Eva",
        "Genessis Marin",
        "Homero",
        "Jolmarys",
        "Oscar Chirino",
        "Simon",
    ],
    "Madrugada": [
        "Caridad",
        "Maria",
        "Camila Paez",
        "Nathali",
    ],
    "Media noche": [
        "Antonio",
        "Zahra",
        "Rigoberto",
    ],
    "Tarde/Noche": [
        "Alex",
        "Ana",
        "Augusto",
        "Julio",
        "Valentina",
        "Luis",
        "Mary",
        "Maykro",
        "Michael",
        "Minerva",
        "Moises",
        "Paola",
        "Roberth",
        "Rolmer",
        
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