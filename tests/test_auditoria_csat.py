import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tools.auditoria_csat as csat
from tools.auditoria_csat import (
    aceptar_propuestas_ia,
    actualizar_estado_desde_formulario,
    aplicar_resultado_ia,
    auditar_estado_con_ia,
    cargar_analisis,
    guardar_analisis,
)
from utils.estado_temporal import limpiar_estados_temporales_expirados


class AuditoriaCsatStateTests(unittest.TestCase):
    def tearDown(self):
        limpiar_estados_temporales_expirados("auditoria_csat", ttl_hours=0)

    def test_guardar_analisis_asigna_analysis_id_y_persiste_estado(self):
        estado = {
            "analysis_id": "",
            "source_filename": "csat.csv",
            "rows": [],
            "warnings": [],
            "original_columns": [],
        }

        analysis_id = guardar_analisis(estado)
        cargado = cargar_analisis(analysis_id)

        self.assertTrue(analysis_id)
        self.assertEqual(analysis_id, estado["analysis_id"])
        self.assertEqual("csat.csv", cargado["source_filename"])
        self.assertEqual(analysis_id, cargado["analysis_id"])


def fila_negativa(**extra):
    fila = {
        "row_id": "0",
        "tipo_rating": "Negativo",
        "justificable": "",
        "comentario_auditor": "",
        "motivo_inconformidad": "",
        "estado_auditoria": "pendiente",
        "csat_flag": "contabiliza",
        "ia_justificable": "",
        "ia_motivo": "",
        "origen_decision": "",
    }
    fila.update(extra)
    return fila


def fila_con_propuesta(valor):
    return fila_negativa(ia_justificable=valor, ia_motivo="CAPTCHA", ia_estado="sugerida")


class AuditoriaCsatPropuestaIaTests(unittest.TestCase):
    def test_ia_no_cambia_decision_ni_csat(self):
        fila = fila_negativa()
        aplicar_resultado_ia(
            fila,
            {"justificable": "SI", "motivo_inconformidad": "CAPTCHA", "confianza": 0.9, "explicacion": "x", "evidencia": "y"},
            "m",
        )
        self.assertEqual("SÍ", fila["ia_justificable"])
        self.assertEqual("CAPTCHA", fila["ia_motivo"])
        self.assertEqual("", fila["justificable"])
        self.assertEqual("", fila["comentario_auditor"])
        self.assertEqual("pendiente", fila["estado_auditoria"])
        self.assertEqual("contabiliza", fila["csat_flag"])

    def test_ia_fuente_chatwoot_si_hay_survey_id_y_transcripcion(self):
        fila = fila_negativa(survey_id="9", transcripcion_conversacion="hola")
        aplicar_resultado_ia(fila, {"justificable": "NO"}, "m")
        self.assertEqual("transcripcion_chatwoot", fila["ia_fuente"])

    def test_aceptar_propuestas_marca_origen(self):
        estado = {"rows": [fila_con_propuesta("SÍ")]}
        self.assertEqual(1, aceptar_propuestas_ia(estado))
        fila = estado["rows"][0]
        self.assertEqual("SÍ", fila["justificable"])
        self.assertEqual("CAPTCHA", fila["motivo_inconformidad"])
        self.assertEqual("ia_aceptada", fila["origen_decision"])
        self.assertEqual("excluida_por_justificable_si", fila["csat_flag"])

    def test_guardar_form_sin_cambios_no_vuelve_humana(self):
        estado = {"rows": [fila_con_propuesta("SÍ")]}
        actualizar_estado_desde_formulario(
            estado, {"justificable__0": "", "motivo_inconformidad__0": "", "comentario_auditor__0": ""}
        )
        self.assertEqual("", estado["rows"][0]["origen_decision"])
        self.assertEqual("", estado["rows"][0]["justificable"])

    def test_cambio_en_form_es_humana_y_la_ia_no_la_toca(self):
        estado = {"rows": [fila_negativa()]}
        actualizar_estado_desde_formulario(
            estado, {"justificable__0": "NO", "motivo_inconformidad__0": "OTRO", "comentario_auditor__0": "nota"}
        )
        self.assertEqual("humana", estado["rows"][0]["origen_decision"])

        llamadas = []

        def falso(filas, config):
            llamadas.append(filas)
            return []

        with mock.patch.object(csat, "auditar_lote_con_proveedor", falso), mock.patch.object(
            csat, "obtener_ia_config",
            return_value={"activa": True, "api_key": "k", "model": "m", "max_cases": 10},
        ):
            auditadas, _ = auditar_estado_con_ia(estado)
        self.assertEqual(0, auditadas)
        self.assertEqual([], llamadas)


class ParsearFechaIsoTests(unittest.TestCase):
    def test_iso_con_zona_horaria_sin_advertencias(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            fecha = csat.parsear_fecha("2023-11-14T18:13:20-04:00")
        self.assertEqual((2023, 11, 14, 18, 13), (fecha.year, fecha.month, fecha.day, fecha.hour, fecha.minute))
        self.assertEqual(-4 * 3600, fecha.utcoffset().total_seconds())

    def test_fecha_csv_sigue_dia_primero(self):
        fecha = csat.parsear_fecha("05/11/2023 10:00")
        self.assertEqual((2023, 11, 5), (fecha.year, fecha.month, fecha.day))

    def test_candidatos_para_ia_excluye_negativos_con_decision_humana_previa(self):
        filas = [
            {"row_id": "1", "tipo_rating": "Negativo", "justificable": "NO", "origen_decision": ""},
            {"row_id": "2", "tipo_rating": "Negativo", "justificable": "", "origen_decision": ""},
        ]
        self.assertEqual(["2"], [f["row_id"] for f in csat.candidatos_para_ia(filas, 10)])


if __name__ == "__main__":
    unittest.main()


class IaCompartidaTests(unittest.TestCase):
    """La Auditoría CSAT usa la misma IA que la Auditoría de chats (AUDITORIA_CHATS_AI_*)."""

    def test_config_usa_la_ia_de_auditoria_de_chats(self):
        with mock.patch.dict(os.environ, {"AUDITORIA_CHATS_AI_API_KEY": "k", "AUDITORIA_CHATS_AI_MODEL": "modelo-x", "CSAT_AI_MAX_CASES": "4"}):
            config = csat.obtener_ia_config()
        self.assertTrue(csat.ia_disponible(config))
        self.assertEqual("modelo-x", config["model"])
        self.assertEqual(4, config["max_cases"])

    def test_sin_clave_avisa_y_no_llama(self):
        estado = {"rows": [fila_negativa()]}
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(csat, "completar_json") as llamada:
            os.environ.pop("AUDITORIA_CHATS_AI_API_KEY", None)
            auditadas, avisos = auditar_estado_con_ia(estado)
        self.assertEqual(0, auditadas)
        self.assertIn("AUDITORIA_CHATS_AI_API_KEY", avisos[0])
        llamada.assert_not_called()

    def test_lote_usa_conector_compartido_y_aplica_propuesta(self):
        estado = {"rows": [fila_negativa()]}
        config = {"activa": True, "api_key": "k", "model": "principal", "model_respaldo": "", "max_cases": 10, "base_url": "http://ia.local"}
        respuesta = {"resultados": [{"row_id": "0", "justificable": "SI", "motivo_inconformidad": "CAPTCHA", "confianza": 0.7, "explicacion": "e", "evidencia": "v"}]}
        with mock.patch.object(csat, "obtener_ia_config", return_value=config), mock.patch.object(
            csat, "completar_json", return_value=respuesta
        ) as llamada:
            auditadas, avisos = auditar_estado_con_ia(estado)
        self.assertEqual((1, []), (auditadas, avisos))
        mensajes = llamada.call_args.args[0]
        self.assertEqual(["system", "user"], [m["role"] for m in mensajes])
        fila = estado["rows"][0]
        self.assertEqual(("SÍ", "CAPTCHA", "principal"), (fila["ia_justificable"], fila["ia_motivo"], fila["ia_modelo"]))
        self.assertEqual("", fila["justificable"])

    def test_usa_modelo_de_respaldo_si_el_principal_no_tiene_cupo(self):
        from utils.ia_chat import IARateLimitError

        estado = {"rows": [fila_negativa()]}
        config = {"activa": True, "api_key": "k", "model": "principal", "model_respaldo": "respaldo", "max_cases": 10, "base_url": "http://ia.local"}
        respuesta = {"resultados": [{"row_id": "0", "justificable": "NO", "motivo_inconformidad": "OTRO", "confianza": 0.5}]}
        modelos = []

        def falso(mensajes, cfg, timeout=60):
            modelos.append((cfg["model"], timeout))
            if cfg["model"] == "principal":
                raise IARateLimitError("Límite diario de la IA alcanzado; retoma mañana.", diario=True)
            return respuesta

        with mock.patch.object(csat, "obtener_ia_config", return_value=config), mock.patch.object(csat, "completar_json", falso):
            auditadas, _ = auditar_estado_con_ia(estado)
        # Ambos modelos se reparten el presupuesto para no pasar el límite de 60 s de Vercel.
        self.assertEqual([("principal", 24), ("respaldo", 24)], modelos)
        self.assertEqual(1, auditadas)
        self.assertEqual("respaldo", estado["rows"][0]["ia_modelo"])

    def test_limite_sin_respaldo_da_aviso_en_espanol(self):
        from utils.ia_chat import IARateLimitError

        estado = {"rows": [fila_negativa()]}
        config = {"activa": True, "api_key": "k", "model": "principal", "model_respaldo": "", "max_cases": 10, "base_url": "http://ia.local"}
        with mock.patch.object(csat, "obtener_ia_config", return_value=config), mock.patch.object(
            csat, "completar_json", side_effect=IARateLimitError("Límite diario de la IA alcanzado; retoma mañana.", diario=True)
        ):
            auditadas, avisos = auditar_estado_con_ia(estado)
        self.assertEqual(0, auditadas)
        self.assertIn("Límite diario", avisos[0])
        self.assertIn("compartido con la Auditoría de chats", avisos[0])


class AvisoModelosTests(unittest.TestCase):
    """Cuando la IA no responde, el aviso dice qué modelos se probaron y si falta el respaldo."""

    def _config(self, respaldo):
        return {"activa": True, "api_key": "k", "model": "gemini-principal", "model_respaldo": respaldo, "max_cases": 5, "base_url": "http://ia.local"}

    def test_sin_respaldo_sugiere_configurarlo(self):
        from utils.ia_chat import IATemporalError

        with mock.patch.object(csat, "obtener_ia_config", return_value=self._config("")), mock.patch.object(
            csat, "completar_json", side_effect=IATemporalError("El proveedor de IA está saturado o con fallos (503); se reintentará en 30 s.")
        ):
            _, avisos = auditar_estado_con_ia({"rows": [fila_negativa()]})
        self.assertIn("gemini-principal: saturado", avisos[0])
        self.assertIn("AUDITORIA_CHATS_AI_MODEL_RESPALDO", avisos[0])

    def test_con_respaldo_nombra_ambos_modelos(self):
        from utils.ia_chat import IATemporalError

        errores = [
            IATemporalError("El proveedor de IA está saturado o con fallos (503); se reintentará en 30 s."),
            IATemporalError("El proveedor de IA no respondió a tiempo (ReadTimeout); se reintentará en 30 s."),
        ]
        with mock.patch.object(csat, "obtener_ia_config", return_value=self._config("gemini-respaldo")), mock.patch.object(
            csat, "completar_json", side_effect=errores
        ):
            _, avisos = auditar_estado_con_ia({"rows": [fila_negativa()]})
        self.assertIn("gemini-principal: saturado", avisos[0])
        self.assertIn("gemini-respaldo: tardó demasiado", avisos[0])
        self.assertNotIn("AUDITORIA_CHATS_AI_MODEL_RESPALDO", avisos[0])
