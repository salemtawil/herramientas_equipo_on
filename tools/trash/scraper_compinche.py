from playwright.sync_api import sync_playwright
import re
import time
import os

def limpiar_numero(texto):
    match = re.search(r"\d[\d,\.]*", texto)
    if not match:
        return None
    return int(match.group(0).replace(",", "").replace(".", ""))

def leer_valor_tarjeta(page, etiqueta, intentos=20, espera_segundos=2, callback_progreso=None):
    if callback_progreso:
        callback_progreso(f"Leyendo {etiqueta}...")

    for intento in range(intentos):
        try:
            card = page.locator(f"text={etiqueta}").first.locator("..")
            texto_card = card.inner_text()

            numero = limpiar_numero(texto_card)

            if numero is not None and numero > 0:
                return numero

        except Exception:
            pass

        time.sleep(espera_segundos)

    return None

def hacer_login_compinche(page, telefono, password, callback_progreso=None):
    if callback_progreso:
        callback_progreso("Abriendo login...")

    page.goto("https://old.compinche.io/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    if callback_progreso:
        callback_progreso("Completando credenciales...")

    inputs = page.locator("input")
    total_inputs = inputs.count()

    if total_inputs < 2:
        raise ValueError("No se encontraron los campos de login esperados.")

    phone_input = inputs.nth(0)
    password_input = page.locator('input[type="password"]')

    phone_input.fill(telefono)
    password_input.fill(password)

    if callback_progreso:
        callback_progreso("Iniciando sesion...")

    page.get_by_role("button", name="Iniciar sesión").click()
    page.wait_for_timeout(4000)

def obtener_metricas_compinche(callback_progreso=None):
    telefono = os.getenv("ARCHIVED_COMPINCHE_PHONE", "")
    password = os.getenv("ARCHIVED_COMPINCHE_PASSWORD", "")

    if not telefono or not password:
        raise RuntimeError(
            "Set ARCHIVED_COMPINCHE_PHONE and ARCHIVED_COMPINCHE_PASSWORD to run this archived scraper."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        hacer_login_compinche(page, telefono, password, callback_progreso=callback_progreso)

        if callback_progreso:
            callback_progreso("Entrando al admin...")

        page.goto("https://old.compinche.io/admin", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        active_users = leer_valor_tarjeta(
            page,
            "Active users",
            intentos=20,
            espera_segundos=2,
            callback_progreso=callback_progreso
        )

        running_users = leer_valor_tarjeta(
            page,
            "Running users",
            intentos=20,
            espera_segundos=2,
            callback_progreso=callback_progreso
        )

        browser.close()

        return {
            "active_users": active_users,
            "running_users": running_users
        }

if __name__ == "__main__":
    resultado = obtener_metricas_compinche(print)
    print("Resultado final:", resultado)
