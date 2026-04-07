from playwright.sync_api import sync_playwright
import re
import time

def limpiar_numero(texto):
    match = re.search(r"\d[\d,\.]*", texto)
    if not match:
        return None
    return int(match.group(0).replace(",", "").replace(".", ""))

def leer_good_standing_paripe(page, intentos=20, espera_segundos=2, callback_progreso=None):
    if callback_progreso:
        callback_progreso("Leyendo Usuarios good standing...")

    for intento in range(intentos):
        try:
            label = page.locator("text=Usuarios good standing").first

            candidatos = [
                label.locator("xpath=.."),
                label.locator("xpath=../.."),
                label.locator("xpath=../../.."),
                label.locator("xpath=../../../.."),
            ]

            for idx, candidato in enumerate(candidatos, start=1):
                try:
                    texto_card = candidato.inner_text()
                    print(f"Good standing - intento {intento + 1}, nivel {idx}: {repr(texto_card)}")

                    numero = limpiar_numero(texto_card)
                    if numero is not None and numero > 0:
                        return numero
                except Exception as e:
                    print(f"Good standing - intento {intento + 1}, nivel {idx}: error -> {e}")

        except Exception as e:
            print(f"Good standing - intento {intento + 1}: no se encontro la etiqueta -> {e}")

        time.sleep(espera_segundos)

    return None

def leer_pool_fotos_paripe(page, intentos=20, espera_segundos=2, callback_progreso=None):
    if callback_progreso:
        callback_progreso("Leyendo pool de fotos...")

    for intento in range(intentos):
        try:
            # Busca el primer <dd> que aparece despues de "Image bank stats"
            dd = page.locator("xpath=//*[normalize-space()='Image bank stats']/following::dd[1]").first
            texto = dd.inner_text()

            print(f"Pool de fotos - intento {intento + 1}: {repr(texto)}")

            numero = limpiar_numero(texto)
            if numero is not None and numero > 0:
                return numero

        except Exception as e:
            print(f"Pool de fotos - intento {intento + 1}: error -> {e}")

        time.sleep(espera_segundos)

    return None

def hacer_login_paripe(page, callback_progreso=None):
    if callback_progreso:
        callback_progreso("Abriendo login Paripe...")

    page.goto("https://paripe.io/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    if callback_progreso:
        callback_progreso("Seleccionando prefijo +58...")

    page.locator("#prefix").select_option("+58")
    page.wait_for_timeout(800)

    if callback_progreso:
        callback_progreso("Completando credenciales Paripe...")

    page.locator("#phone-number").fill("4148020203")
    page.wait_for_timeout(300)

    page.locator("#password").fill("compi123.")
    page.wait_for_timeout(300)

    if callback_progreso:
        callback_progreso("Iniciando sesion en Paripe...")

    page.get_by_role("button", name="Ingresar").click()
    page.wait_for_timeout(4000)

def obtener_metricas_paripe(callback_progreso=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        hacer_login_paripe(page, callback_progreso=callback_progreso)

        if callback_progreso:
            callback_progreso("Entrando al admin de Paripe...")

        page.goto("https://paripe.io/admin", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        good_standing = leer_good_standing_paripe(
            page,
            intentos=20,
            espera_segundos=2,
            callback_progreso=callback_progreso
        )

        pool_fotos = leer_pool_fotos_paripe(
            page,
            intentos=20,
            espera_segundos=2,
            callback_progreso=callback_progreso
        )

        browser.close()

        return {
            "good_standing_users": good_standing,
            "photo_pool": pool_fotos
        }

if __name__ == "__main__":
    resultado = obtener_metricas_paripe(print)
    print("Resultado final:", resultado)