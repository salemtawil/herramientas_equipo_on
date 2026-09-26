import re
import unittest

from app import app


class AccesibilidadBaseTests(unittest.TestCase):
    def test_enlace_saltar_al_contenido_apunta_al_main(self):
        html = app.test_client().get("/").get_data(as_text=True)
        self.assertIn('<a class="skip-link" href="#contenido-principal">Saltar al contenido</a>', html)
        self.assertRegex(html, r'<main[^>]*id="contenido-principal"')

    def test_solo_el_enlace_activo_tiene_aria_current(self):
        html = app.test_client().get("/comparar-csv").get_data(as_text=True)
        activos = re.findall(r'<a class="sidebar-link[^"]*"[^>]*aria-current="page"[^>]*>', html)
        self.assertEqual(1, len(activos))
        self.assertIn('href="/comparar-csv"', activos[0])
        self.assertIn("is-active", activos[0])

    def test_campos_de_archivo_tienen_etiqueta(self):
        html = app.test_client().get("/comparar-csv").get_data(as_text=True)
        self.assertIn('for="comparar-archivo-base"', html)
        self.assertIn('id="comparar-archivo-base"', html)


if __name__ == "__main__":
    unittest.main()
