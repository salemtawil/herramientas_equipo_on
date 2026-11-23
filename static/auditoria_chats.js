// Auditoría de chats: alcance del formulario y procesamiento del lote paso a paso.
(function () {
  "use strict";

  function normalizar(texto) {
    return String(texto || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase()
      .trim();
  }

  function iniciarSelector() {
    const selector = document.querySelector("[data-ac-selector]");
    if (!selector) return;
    const buscador = selector.querySelector("[data-ac-buscar]");
    const resumen = selector.querySelector("[data-ac-resumen]");
    const campoChats = document.querySelector("[data-ac-chats]");
    const cupo = parseInt(selector.getAttribute("data-ac-cupo"), 10) || 0;
    const grupos = Array.from(selector.querySelectorAll("[data-ac-grupo]"));
    const casillas = () => Array.from(selector.querySelectorAll('input[name="agentes"]'));

    function actualizarGrupos() {
      grupos.forEach((grupo) => {
        const todos = grupo.querySelector("[data-ac-grupo-todos]");
        const agentes = Array.from(grupo.querySelectorAll('input[name="agentes"]'));
        if (!todos || !agentes.length) return;
        const marcados = agentes.filter((c) => c.checked).length;
        todos.checked = marcados === agentes.length;
        todos.indeterminate = marcados > 0 && marcados < agentes.length;
      });
    }

    function actualizarResumen() {
      const marcados = casillas().filter((c) => c.checked).length;
      const porAgente = Math.max(1, parseInt(campoChats && campoChats.value, 10) || 1);
      const total = marcados * porAgente;
      let texto;
      if (!marcados) {
        texto = "Marca los agentes o turnos completos que quieres auditar.";
      } else {
        texto = marcados + (marcados === 1 ? " agente" : " agentes") + " · " + total + " chats";
        if (cupo > 0 && total > cupo) {
          const dias = Math.ceil(total / cupo);
          texto += " · ⚠ supera el cupo diario de la IA (~" + cupo + "/día): el lote tardará unos " + dias + " días";
        } else if (cupo > 0) {
          texto += " · cabe en el cupo diario de la IA (~" + cupo + "/día)";
        }
      }
      resumen.textContent = texto;
      resumen.classList.toggle("is-warning", cupo > 0 && total > cupo);
    }

    function refrescar() {
      actualizarGrupos();
      actualizarResumen();
    }

    selector.addEventListener("change", (evento) => {
      const objetivo = evento.target;
      if (objetivo.hasAttribute("data-ac-grupo-todos")) {
        const grupo = objetivo.closest("[data-ac-grupo]");
        grupo.querySelectorAll('input[name="agentes"]').forEach((c) => {
          if (!c.closest("[data-ac-agente]").hidden) c.checked = objetivo.checked;
        });
      }
      refrescar();
    });

    selector.querySelectorAll("[data-ac-marcar]").forEach((boton) => {
      boton.addEventListener("click", () => {
        const marcar = boton.getAttribute("data-ac-marcar") === "todos";
        casillas().forEach((c) => {
          if (!c.closest("[data-ac-agente]").hidden) c.checked = marcar;
        });
        refrescar();
      });
    });

    if (buscador) {
      buscador.addEventListener("input", () => {
        const consulta = normalizar(buscador.value);
        grupos.forEach((grupo) => {
          let visibles = 0;
          grupo.querySelectorAll("[data-ac-agente]").forEach((etiqueta) => {
            const coincide = !consulta || normalizar(etiqueta.getAttribute("data-ac-agente")).includes(consulta);
            etiqueta.hidden = !coincide;
            if (coincide) visibles += 1;
          });
          grupo.hidden = Boolean(consulta) && visibles === 0;
        });
      });
    }

    if (campoChats) campoChats.addEventListener("input", actualizarResumen);
    refrescar();
  }

  function esperar(segundos, alTick) {
    return new Promise((resolver) => {
      let restante = segundos;
      alTick(restante);
      const intervalo = setInterval(() => {
        restante -= 1;
        alTick(restante);
        if (restante <= 0) {
          clearInterval(intervalo);
          resolver();
        }
      }, 1000);
    });
  }

  function iniciarProcesamiento() {
    const botonProcesar = document.querySelector("[data-ac-procesar]");
    if (!botonProcesar) return;
    const botonPausar = document.querySelector("[data-ac-pausar]");
    const formularioPaso = document.querySelector("[data-ac-paso-form]");
    const barra = document.querySelector("[data-ac-progreso] progress");
    const textoProgreso = document.querySelector("[data-ac-progreso-texto]");
    const textoMensaje = document.querySelector("[data-ac-mensaje]");
    const estado = document.querySelector("[data-ac-estado]");
    const url = botonProcesar.getAttribute("data-url");
    let pausado = false;
    let enCurso = false;

    function mostrarProgreso(datos) {
      const p = datos.progreso;
      if (p) {
        barra.max = p.total || 1;
        barra.value = p.auditados;
        textoProgreso.textContent =
          p.auditados + " / " + p.total + " auditados · " + p.pendientes + " pendientes · " + p.errores + " errores";
      }
      if (datos.mensaje) textoMensaje.textContent = datos.mensaje;
    }

    function terminar(recargar) {
      enCurso = false;
      botonProcesar.disabled = false;
      botonPausar.hidden = true;
      if (formularioPaso) formularioPaso.hidden = false;
      if (recargar) window.location.reload();
    }

    async function procesar() {
      if (enCurso) return;
      enCurso = true;
      pausado = false;
      botonProcesar.disabled = true;
      botonPausar.hidden = false;
      if (formularioPaso) formularioPaso.hidden = true;
      if (estado) estado.textContent = "Procesando…";

      while (!pausado) {
        let datos;
        try {
          const respuesta = await fetch(url, {
            method: "POST",
            headers: { Accept: "application/json" },
            credentials: "same-origin",
          });
          if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
          datos = await respuesta.json();
          if (!datos || typeof datos !== "object") throw new Error("respuesta vacía");
        } catch (error) {
          textoMensaje.textContent = "No se pudo avanzar el lote (" + error.message + "). Vuelve a intentarlo.";
          terminar(false);
          return;
        }

        mostrarProgreso(datos);
        if (datos.accion === "fin" || datos.estado === "limite_diario") {
          terminar(true);
          return;
        }
        if (datos.accion === "error" || datos.accion === "configuracion") {
          terminar(false);
          return;
        }
        if (datos.esperar_segundos > 0) {
          const base = datos.mensaje || "Esperando al proveedor de IA";
          await esperar(datos.esperar_segundos, (s) => {
            textoMensaje.textContent = base + " Reintento en " + Math.max(s, 0) + " s.";
          });
        }
      }
      textoMensaje.textContent = "En pausa. Puedes retomarlo cuando quieras.";
      if (estado) estado.textContent = "En pausa";
      terminar(false);
    }

    botonProcesar.addEventListener("click", procesar);
    botonPausar.addEventListener("click", () => {
      pausado = true;
      botonPausar.disabled = true;
      textoMensaje.textContent = "Pausando al terminar el paso actual…";
      setTimeout(() => {
        botonPausar.disabled = false;
      }, 500);
    });
  }

  function iniciarRevisor() {
    const campo = document.querySelector("[data-ac-revisor]");
    if (!campo) return;
    const clave = "auditoria-chats-revisor";
    try {
      if (!campo.value) campo.value = window.localStorage.getItem(clave) || "";
    } catch (error) {
      /* almacenamiento no disponible */
    }
    campo.form.addEventListener("submit", () => {
      try {
        window.localStorage.setItem(clave, campo.value.trim());
      } catch (error) {
        /* almacenamiento no disponible */
      }
    });
  }

  // Informe del lote: el botón abre la impresión del navegador («Guardar como PDF»).
  function iniciarImpresion() {
    document.querySelectorAll("[data-ac-imprimir]").forEach((boton) => {
      boton.addEventListener("click", () => window.print());
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    iniciarSelector();
    iniciarProcesamiento();
    iniciarRevisor();
    iniciarImpresion();
  });
})();
