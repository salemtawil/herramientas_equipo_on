// Auditoría de chats: alcance del formulario y procesamiento del lote paso a paso.
(function () {
  "use strict";

  function iniciarAlcance() {
    const selector = document.querySelector("[data-ac-alcance]");
    if (!selector) return;
    const actualizar = () => {
      document.querySelectorAll("[data-ac-bloque]").forEach((bloque) => {
        bloque.hidden = bloque.getAttribute("data-ac-bloque") !== selector.value;
      });
    };
    selector.addEventListener("change", actualizar);
    actualizar();
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

  document.addEventListener("DOMContentLoaded", () => {
    iniciarAlcance();
    iniciarProcesamiento();
    iniciarRevisor();
  });
})();
