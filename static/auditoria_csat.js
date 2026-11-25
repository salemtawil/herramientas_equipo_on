// Auditoría CSAT: «Auditar pendientes con IA» revisa todos los negativos en tandas, con avance.
// Sin JavaScript el botón sigue funcionando: audita una tanda por clic.
(function () {
  "use strict";

  const MAX_FALLOS_SEGUIDOS = 3;
  const ESPERA_TRAS_FALLO = 15;

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

  function iniciar() {
    const boton = document.querySelector("[data-csat-ia]");
    const estado = document.querySelector("[data-csat-ia-estado]");
    if (!boton || !estado || !boton.form) return;
    const formulario = boton.form;

    async function paso() {
      const datos = new FormData(formulario);
      datos.set("accion", "auditar_con_ia");
      const respuesta = await fetch(formulario.getAttribute("action") || window.location.pathname, {
        method: "POST",
        body: datos,
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
      return respuesta.json();
    }

    async function auditarTodo(evento) {
      evento.preventDefault();
      boton.disabled = true;
      estado.hidden = false;
      estado.textContent = "La IA está revisando los negativos…";
      let fallos = 0;
      let revisados = 0;
      let ultimo = null;

      for (;;) {
        let datos;
        try {
          datos = await paso();
          fallos = 0;
        } catch (error) {
          fallos += 1;
          if (fallos >= MAX_FALLOS_SEGUIDOS) {
            estado.textContent = "No se pudo continuar (" + error.message + "). Vuelve a pulsar el botón.";
            break;
          }
          await esperar(ESPERA_TRAS_FALLO, (s) => {
            estado.textContent = "El servidor no respondió (" + error.message + "). Reintento en " + Math.max(s, 0) + " s.";
          });
          continue;
        }

        ultimo = datos;
        revisados += datos.auditadas || 0;
        const avance =
          "Revisados " + revisados + " · quedan " + datos.pendientes + " de " + datos.total_negativos + " negativos.";
        if (datos.fin) {
          const cierre = revisados > 0 ? " Actualizando la tabla…" : "";
          estado.textContent = (datos.advertencia ? datos.advertencia + " " : "") + avance + cierre;
          break;
        }
        if (datos.esperar_segundos > 0) {
          const motivo = datos.advertencia || "El proveedor de IA pidió esperar.";
          await esperar(datos.esperar_segundos, (s) => {
            estado.textContent = avance + " " + motivo + " Reintento en " + Math.max(s, 0) + " s.";
          });
        } else {
          estado.textContent = avance + " Siguiente tanda…";
        }
      }

      // Si hubo avance se recarga para ver las propuestas; si no, se deja el aviso a la vista.
      if (revisados > 0 && ultimo && ultimo.url) {
        window.location.assign(ultimo.url);
      } else {
        boton.disabled = false;
      }
    }

    boton.addEventListener("click", auditarTodo);
  }

  document.addEventListener("DOMContentLoaded", iniciar);
})();
