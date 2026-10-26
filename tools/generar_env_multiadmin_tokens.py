"""Renueva los tokens de Multiadmin (Cognito) para la app y para Vercel.

Uso normal: doble clic en ``tools/renovar_tokens_multiadmin.bat``.

Qué hace, en orden:
1. Intenta renovar con el refresh token guardado (no pide usuario, contraseña ni SMS).
2. Si el refresh token ya no sirve, inicia sesión con el usuario y la contraseña
   guardados en ``.env.multiadmin.local`` (archivo local, fuera de Git). La primera
   vez los pide y ofrece guardarlos. Si Cognito exige un código SMS, lo pide.
3. Escribe ``.env.vercel.multiadmin.tokens``, actualiza los tokens en ``.env`` y
   copia al portapapeles las variables que hay que pegar en Vercel.

Solo usa la biblioteca estándar de Python: no necesita boto3, requests ni
credenciales de AWS. Nunca muestra tokens ni contraseñas en pantalla.
"""

import argparse
import base64
from datetime import datetime
from datetime import timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import urllib.error
import urllib.request


RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO_CREDENCIALES = RAIZ / ".env.multiadmin.local"
ARCHIVO_TOKENS = RAIZ / ".env.vercel.multiadmin.tokens"
ARCHIVO_ENV = RAIZ / ".env"

DEFAULTS = {
    "MULTIADMIN_API_BASE_URL": "https://7b9q0ttttb.execute-api.us-east-1.amazonaws.com",
    "MULTIADMIN_CLIENT_ID": "24nnt1psojm5aqotu1ckj9jk9g",
    "MULTIADMIN_USER_POOL_ID": "us-east-1_ViIazRdoA",
    "MULTIADMIN_USERS_SINCE_EXPIRATION": "1746057600000",
    "AWS_DEFAULT_REGION": "us-east-1",
}

# Variables que hay que copiar a Vercel (Production) después de renovar.
VARIABLES_VERCEL = (
    "MULTIADMIN_ID_TOKEN",
    "MULTIADMIN_REFRESH_TOKEN",
)


class ErrorCognito(Exception):
    def __init__(self, codigo, mensaje):
        super().__init__(f"{codigo}: {mensaje}")
        self.codigo = codigo
        self.mensaje = mensaje


# ---------------------------------------------------------------------------
# Archivos .env
# ---------------------------------------------------------------------------


def leer_env(ruta):
    valores = {}
    if not ruta.exists():
        return valores
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        valor = valor.strip().strip('"').strip("'")
        if valor:
            valores[clave.strip()] = valor
    return valores


def actualizar_env(ruta, nuevos):
    """Reemplaza o añade variables conservando el resto del archivo y sus saltos de línea."""
    if ruta.exists():
        crudo = ruta.read_bytes().decode("utf-8-sig")
        salto = "\r\n" if "\r\n" in crudo else "\n"
        lineas = crudo.splitlines()
    else:
        salto, lineas = "\n", []
    pendientes = dict(nuevos)
    for i, linea in enumerate(lineas):
        clave = linea.split("=", 1)[0].strip()
        if "=" in linea and not linea.lstrip().startswith("#") and clave in pendientes:
            lineas[i] = f"{clave}={pendientes.pop(clave)}"
    lineas.extend(f"{clave}={valor}" for clave, valor in pendientes.items())
    ruta.write_bytes((salto.join(lineas) + salto).encode("utf-8"))


def configuracion():
    """Combina valores por defecto, .env, archivo de tokens, credenciales locales y entorno."""
    config = dict(DEFAULTS)
    for ruta in (ARCHIVO_ENV, ARCHIVO_TOKENS, ARCHIVO_CREDENCIALES):
        config.update(leer_env(ruta))
    for clave in list(DEFAULTS) + ["MULTIADMIN_USERNAME", "MULTIADMIN_PASSWORD",
                                   "MULTIADMIN_CLIENT_SECRET", "MULTIADMIN_REFRESH_TOKEN"]:
        if os.getenv(clave):
            config[clave] = os.getenv(clave).strip()
    return config


# ---------------------------------------------------------------------------
# Cognito por HTTPS (sin boto3 ni credenciales de AWS)
# ---------------------------------------------------------------------------


def cognito(config, accion, cuerpo):
    region = config["AWS_DEFAULT_REGION"]
    peticion = urllib.request.Request(
        f"https://cognito-idp.{region}.amazonaws.com/",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": f"AWSCognitoIdentityProviderService.{accion}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            datos = json.loads(error.read().decode("utf-8"))
        except ValueError:
            datos = {}
        codigo = str(datos.get("__type", f"HTTP {error.code}")).split("#")[-1]
        raise ErrorCognito(codigo, datos.get("message") or datos.get("Message") or "") from None
    except urllib.error.URLError as error:
        raise ErrorCognito("SinConexion", str(error.reason)) from None


def secret_hash(config, usuario):
    secreto = config.get("MULTIADMIN_CLIENT_SECRET", "")
    if not secreto:
        return None
    digest = hmac.new(
        secreto.encode("utf-8"),
        f"{usuario}{config['MULTIADMIN_CLIENT_ID']}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def con_secret_hash(config, parametros, usuario):
    valor = secret_hash(config, usuario)
    if valor:
        parametros["SECRET_HASH"] = valor
    return parametros


# --- SRP (cuando el cliente de Cognito no admite contraseña directa) -------

N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA051015"
    "728E5A8AAAC42DAD33170D04507A33A85521ABDF1CBA64EC"
    "FB850458DBEF0A8AEA71575D060C7DB3970F85A6E1E4C7AB"
    "F5AE8CDB0933D71E8C94E04A25619DCEE3D2261AD2EE6BF"
    "12FFA06D98A0864D87602733EC86A64521F2B18177B200CB"
    "BE117577A615D6C770988C0BAD946E208E24FA074E5AB3143"
    "DB5BFCE0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF"
)
N = int(N_HEX, 16)
G = 2


def _hex_hash(valor_hex):
    return hashlib.sha256(bytearray.fromhex(valor_hex)).hexdigest()


def _pad_hex(valor):
    if isinstance(valor, int):
        valor = f"{valor:x}"
    if len(valor) % 2 == 1:
        valor = f"0{valor}"
    if valor[0] in "89ABCDEFabcdef":
        valor = f"00{valor}"
    return valor


def _hkdf(ikm, salt):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    info = bytearray("Caldera Derived Key", "utf-8") + bytearray(chr(1), "utf-8")
    return hmac.new(prk, info, hashlib.sha256).digest()[:16]


def _marca_tiempo_cognito():
    ahora = datetime.now(timezone.utc)
    dias = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    meses = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{dias[ahora.weekday()]} {meses[ahora.month - 1]} {ahora.day} {ahora:%H:%M:%S} UTC {ahora.year}"


class Srp:
    def __init__(self, config, usuario, password):
        pool = config["MULTIADMIN_USER_POOL_ID"]
        self.pool = pool.split("_", 1)[1] if "_" in pool else pool
        self.usuario = usuario
        self.password = password
        self.a = secrets.randbits(1024) % N
        self.A = pow(G, self.a, N)
        self.k = int(_hex_hash(_pad_hex(N) + _pad_hex(G)), 16)

    def parametros_inicio(self, config):
        return con_secret_hash(config, {"USERNAME": self.usuario, "SRP_A": f"{self.A:x}"}, self.usuario)

    def respuesta(self, config, desafio):
        usuario_srp = desafio["USER_ID_FOR_SRP"]
        B = int(desafio["SRP_B"], 16)
        if B % N == 0:
            raise RuntimeError("Respuesta SRP inválida de Cognito.")
        u = int(_hex_hash(_pad_hex(self.A) + _pad_hex(B)), 16)
        if u == 0:
            raise RuntimeError("Respuesta SRP inválida de Cognito.")
        x = int(_hex_hash(_pad_hex(desafio["SALT"]) + hashlib.sha256(
            f"{self.pool}{usuario_srp}:{self.password}".encode("utf-8")).hexdigest()), 16)
        s = pow((B - self.k * pow(G, x, N)) % N, self.a + u * x, N)
        clave = _hkdf(bytearray.fromhex(_pad_hex(s)), bytearray.fromhex(_pad_hex(u)))
        marca = _marca_tiempo_cognito()
        mensaje = (bytearray(self.pool, "utf-8") + bytearray(usuario_srp, "utf-8")
                   + bytearray(base64.b64decode(desafio["SECRET_BLOCK"])) + bytearray(marca, "utf-8"))
        firma = base64.b64encode(hmac.new(clave, mensaje, hashlib.sha256).digest()).decode("utf-8")
        return con_secret_hash(config, {
            "USERNAME": usuario_srp,
            "PASSWORD_CLAIM_SECRET_BLOCK": desafio["SECRET_BLOCK"],
            "TIMESTAMP": marca,
            "PASSWORD_CLAIM_SIGNATURE": firma,
        }, usuario_srp)


# ---------------------------------------------------------------------------
# Flujos de autenticación
# ---------------------------------------------------------------------------


def renovar_con_refresh(config):
    refresh = config.get("MULTIADMIN_REFRESH_TOKEN", "")
    if not refresh:
        return None
    parametros = {"REFRESH_TOKEN": refresh}
    usuario = config.get("MULTIADMIN_USERNAME", "")
    if usuario:
        parametros["USERNAME"] = usuario
        con_secret_hash(config, parametros, usuario)
    respuesta = cognito(config, "InitiateAuth", {
        "ClientId": config["MULTIADMIN_CLIENT_ID"],
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "AuthParameters": parametros,
    })
    resultado = respuesta["AuthenticationResult"]
    # Cognito no devuelve un refresh token nuevo al renovar: se conserva el actual.
    resultado.setdefault("RefreshToken", refresh)
    return resultado


def pedir_codigo(nombre_desafio):
    textos = {
        "SMS_MFA": "Código que llegó por SMS",
        "SOFTWARE_TOKEN_MFA": "Código de la app autenticadora",
        "CUSTOM_CHALLENGE": "Código de verificación",
        "EMAIL_OTP": "Código que llegó por correo",
    }
    if nombre_desafio not in textos:
        raise RuntimeError(f"Cognito pidió un paso que esta herramienta no sabe resolver: {nombre_desafio}.")
    return input(f"{textos[nombre_desafio]}: ").strip()


def iniciar_sesion(config, usuario, password):
    cliente = config["MULTIADMIN_CLIENT_ID"]
    srp = None
    try:
        respuesta = cognito(config, "InitiateAuth", {
            "ClientId": cliente,
            "AuthFlow": "USER_PASSWORD_AUTH",
            "AuthParameters": con_secret_hash(config, {"USERNAME": usuario, "PASSWORD": password}, usuario),
        })
    except ErrorCognito as error:
        if error.codigo != "InvalidParameterException" or "USER_PASSWORD_AUTH" not in error.mensaje:
            raise
        srp = Srp(config, usuario, password)
        respuesta = cognito(config, "InitiateAuth", {
            "ClientId": cliente,
            "AuthFlow": "USER_SRP_AUTH",
            "AuthParameters": srp.parametros_inicio(config),
        })

    while "ChallengeName" in respuesta:
        nombre = respuesta["ChallengeName"]
        datos = respuesta.get("ChallengeParameters", {})
        if nombre == "PASSWORD_VERIFIER":
            respuestas = srp.respuesta(config, datos)
        elif nombre == "NEW_PASSWORD_REQUIRED":
            raise RuntimeError("Multiadmin exige cambiar la contraseña. Cámbiala en admin.camarada.io y vuelve a ejecutar.")
        else:
            usuario_cognito = datos.get("USER_ID_FOR_SRP", usuario)
            campo = {"SMS_MFA": "SMS_MFA_CODE", "SOFTWARE_TOKEN_MFA": "SOFTWARE_TOKEN_MFA_CODE",
                     "EMAIL_OTP": "EMAIL_OTP_CODE"}.get(nombre, "ANSWER")
            respuestas = con_secret_hash(config, {"USERNAME": usuario_cognito, campo: pedir_codigo(nombre)},
                                         usuario_cognito)
        peticion = {"ClientId": cliente, "ChallengeName": nombre, "ChallengeResponses": respuestas}
        if respuesta.get("Session"):
            peticion["Session"] = respuesta["Session"]
        respuesta = cognito(config, "RespondToAuthChallenge", peticion)

    if "AuthenticationResult" not in respuesta:
        raise RuntimeError("Cognito no devolvió tokens.")
    return respuesta["AuthenticationResult"]


def explicar_error(error):
    textos = {
        "NotAuthorizedException": "Usuario o contraseña incorrectos, o la sesión ya no es válida.",
        "UserNotFoundException": "Ese usuario no existe en Multiadmin. Revisa el teléfono/usuario guardado.",
        "UserNotConfirmedException": "El usuario de Multiadmin no está confirmado.",
        "PasswordResetRequiredException": "Multiadmin exige restablecer la contraseña.",
        "CodeMismatchException": "El código de verificación no es correcto.",
        "ExpiredCodeException": "El código de verificación expiró. Vuelve a ejecutar.",
        "TooManyRequestsException": "Demasiados intentos. Espera unos minutos.",
        "LimitExceededException": "Demasiados intentos. Espera unos minutos.",
        "SinConexion": "No hay conexión con Cognito (revisa internet, VPN o proxy).",
    }
    base = textos.get(error.codigo, f"Cognito rechazó la petición ({error.codigo}).")
    if "SECRET_HASH" in error.mensaje:
        base = ("El cliente de Cognito exige un secreto. Agrega MULTIADMIN_CLIENT_SECRET a "
                ".env.multiadmin.local y vuelve a ejecutar.")
    return base


# ---------------------------------------------------------------------------
# Credenciales locales
# ---------------------------------------------------------------------------


def credenciales(config, preguntar):
    usuario = config.get("MULTIADMIN_USERNAME", "")
    password = config.get("MULTIADMIN_PASSWORD", "")
    if usuario and password and not preguntar:
        return usuario, password
    print()
    print("Inicio de sesión en Multiadmin")
    usuario = input(f"Teléfono o usuario{f' [{usuario}]' if usuario else ''}: ").strip() or usuario
    password = input("Contraseña: ").strip()
    if not usuario or not password:
        raise SystemExit("Faltan usuario o contraseña.")
    guardar = input("¿Guardar usuario y contraseña en este equipo para no volver a pedirlos? [S/n]: ").strip().lower()
    if guardar in ("", "s", "si", "sí", "y", "yes"):
        actualizar_env(ARCHIVO_CREDENCIALES, {"MULTIADMIN_USERNAME": usuario, "MULTIADMIN_PASSWORD": password})
        print(f"Guardadas en {ARCHIVO_CREDENCIALES.name} (solo en este equipo; Git lo ignora).")
    return usuario, password


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------


def expira(token):
    try:
        carga = token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        exp = json.loads(base64.urlsafe_b64decode(carga))["exp"]
        return datetime.fromtimestamp(exp, tz=timezone.utc).astimezone()
    except Exception:
        return None


def guardar_tokens(config, usuario, auth):
    id_token = auth["IdToken"]
    refresh = auth.get("RefreshToken", "")
    fecha = expira(id_token)
    contenido = f"""# Tokens frescos de Multiadmin para Vercel.
# Archivo local sensible. No subir a Git.
# Generado: {datetime.now().astimezone():%Y-%m-%d %H:%M}
# ID token expira: {fecha:%Y-%m-%d %H:%M %Z} (la app lo renueva sola con el refresh token)

MULTIADMIN_API_BASE_URL={config['MULTIADMIN_API_BASE_URL']}
MULTIADMIN_CLIENT_ID={config['MULTIADMIN_CLIENT_ID']}
MULTIADMIN_USER_POOL_ID={config['MULTIADMIN_USER_POOL_ID']}
MULTIADMIN_USERS_SINCE_EXPIRATION={config['MULTIADMIN_USERS_SINCE_EXPIRATION']}
AWS_DEFAULT_REGION={config['AWS_DEFAULT_REGION']}

MULTIADMIN_USERNAME={usuario}
MULTIADMIN_ID_TOKEN={id_token}
MULTIADMIN_REFRESH_TOKEN={refresh}
MULTIADMIN_CLIENT_SECRET={config.get('MULTIADMIN_CLIENT_SECRET', '')}
""" if fecha else ""
    if not contenido:
        raise RuntimeError("Cognito devolvió un ID token que no se puede leer.")
    ARCHIVO_TOKENS.write_text(contenido, encoding="utf-8")
    if ARCHIVO_ENV.exists():
        actualizar_env(ARCHIVO_ENV, {"MULTIADMIN_ID_TOKEN": id_token, "MULTIADMIN_REFRESH_TOKEN": refresh})
    return fecha


def copiar_para_vercel(auth):
    texto = "\n".join([
        f"MULTIADMIN_ID_TOKEN={auth['IdToken']}",
        f"MULTIADMIN_REFRESH_TOKEN={auth.get('RefreshToken', '')}",
    ]) + "\n"
    try:
        if sys.platform.startswith("win"):
            subprocess.run("clip", input=texto.encode("utf-16-le"), check=True, shell=True)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=texto.encode("utf-8"), check=True)
        else:
            return False
        return True
    except Exception:
        return False


def validar(config, id_token):
    base = config["MULTIADMIN_API_BASE_URL"].rstrip("/")
    peticion = urllib.request.Request(
        f"{base}/projects/chispita/users?sinceExpiration={config['MULTIADMIN_USERS_SINCE_EXPIRATION']}",
        headers={"accept": "application/json", "authorization": f"Bearer {id_token}",
                 "origin": "https://admin.camarada.io", "referer": "https://admin.camarada.io/",
                 "user-agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
    if isinstance(datos, dict):
        datos = next((v for k, v in datos.items() if k in ("Items", "items", "data", "result")), datos)
    return len(datos) if isinstance(datos, list) else 0


def main(argv=None):
    opciones = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opciones.add_argument("--iniciar-sesion", action="store_true",
                          help="No usar el refresh token: iniciar sesión con usuario y contraseña.")
    opciones.add_argument("--cambiar-credenciales", action="store_true",
                          help="Volver a pedir usuario y contraseña y guardarlos.")
    opciones.add_argument("--sin-validar", action="store_true",
                          help="No comprobar los tokens contra la API de Chispita.")
    args = opciones.parse_args(argv)

    config = configuracion()
    usuario = config.get("MULTIADMIN_USERNAME", "")
    auth = None

    if not args.iniciar_sesion and not args.cambiar_credenciales and config.get("MULTIADMIN_REFRESH_TOKEN"):
        print("Renovando con el refresh token guardado...")
        try:
            auth = renovar_con_refresh(config)
            print("Renovado sin pedir contraseña.")
        except ErrorCognito as error:
            if error.codigo == "SinConexion":
                raise SystemExit(explicar_error(error))
            print("El refresh token venció o ya no es válido. Hay que iniciar sesión.")

    if auth is None:
        preguntar = args.cambiar_credenciales
        for intento in range(2):
            usuario, password = credenciales(config, preguntar=preguntar)
            try:
                auth = iniciar_sesion(config, usuario, password)
                break
            except ErrorCognito as error:
                credenciales_malas = error.codigo in ("NotAuthorizedException", "UserNotFoundException")
                if credenciales_malas and intento == 0:
                    print(f"No se pudo iniciar sesión: {explicar_error(error)}")
                    print("Vuelve a escribir el usuario y la contraseña.")
                    preguntar = True
                    continue
                raise SystemExit(f"No se pudo iniciar sesión: {explicar_error(error)}")
        if not auth.get("RefreshToken"):
            raise SystemExit("Cognito no devolvió refresh token; la app no podría renovarse sola.")

    fecha = guardar_tokens(config, usuario, auth)
    print()
    print("Tokens listos.")
    print(f"  - {ARCHIVO_TOKENS.name} actualizado")
    if ARCHIVO_ENV.exists():
        print("  - .env actualizado (app local)")
    print(f"  - El ID token vence {fecha:%d/%m/%Y %H:%M}; la app lo renueva sola mientras el refresh token siga vigente.")

    if not args.sin_validar:
        try:
            print(f"  - Comprobado contra Chispita: {validar(config, auth['IdToken'])} usuarios recibidos.")
        except Exception as error:
            print(f"  - Aviso: no se pudo comprobar contra Chispita ({type(error).__name__}).")

    print()
    if copiar_para_vercel(auth):
        print("Copiadas al portapapeles las 2 variables para Vercel (MULTIADMIN_ID_TOKEN y MULTIADMIN_REFRESH_TOKEN).")
    else:
        print(f"Copia MULTIADMIN_ID_TOKEN y MULTIADMIN_REFRESH_TOKEN desde {ARCHIVO_TOKENS.name}.")
    print("En Vercel: Settings > Environment Variables (Production), pégalas y haz Redeploy.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
