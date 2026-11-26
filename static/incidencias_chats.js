// Incidencias de chats: horas por turno, avance de la revisión paso a paso y decisiones sin recargar.
// Todo funciona también sin JS (formularios normales).
(function () {
  "use strict";

  function sumarDia(fechaIso) {
    const partes = String(fechaIso || "").split("-").map((n) => parseInt(n, 10));
    if (partes.length !== 3 || partes.some(isNaN)) return fechaIso;
    const fecha = new Date(Date.UTC(partes[0], partes[1] - 1, partes[2] + 1));
    return fecha.toISOString().slice(0, 10);
  }

  function iniciarTurnos() {
    const selector = document.querySelector("[data-ic-turno]");
    if (!selector) return;
    const desdeFecha = document.querySelector("[data-ic-desde-fecha]");
    const desdeHora = document.querySelector("[data-ic-desde-hora]");
    const hastaFecha = document.querySelector("[data-ic-hasta-fecha]");
    const hastaHora = document.querySelector("[data-ic-hasta-hora]");
    selector.addEventListener("change", () => {
      const opcion = selector.options[selector.selectedIndex];
      const desde = opcion && opcion.getAttribute("data-desde");
      const hasta = opcion && opcion.getAttribute("data-hasta");
      if (!desde || !hasta) return;
      desdeHora.value = desde;
      hastaHora.value = hasta;
      // Un turno que cruza la medianoche termina al día siguiente.
      hastaFecha.value = hasta <= desde ? sumarDia(desdeFecha.value) : desdeFecha.value;
    });
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

  function iniciarProgreso() {
    const contenedor = document.querySelector("[data-ic-paso-url]");
    if (!contenedor) return;
    const url = contenedor.getAttribute("data-ic-paso-url");
    const barra = contenedor.querySelector("progress");
    const textoProgreso = contenedor.querySelector("[data-ic-progreso-texto]");
    const textoMensaje = contenedor.querySelector("[data-ic-mensaje]");
    const estado = document.querySelector("[data-ic-estado-revision]");
    const botonPausar = document.querySelector("[data-ic-pausar]");
    let pausado = false;
    let enCurso = false;

    function mostrar(datos) {
      const p = datos.progreso;
      if (p) {
        const hechos = (p.evaluados || 0) + (p.descartados || 0) + (p.errores || 0);
        barra.max = p.total || 1;
        barra.value = hechos;
        textoProgreso.textContent = hechos + " / " + p.total + " chats revisados";
        Object.keys(p).forEach((clave) => {
          const celda = document.querySelector('[data-ic-contador="' + clave + '"]');
          if (celda) celda.textContent = p[clave];
        });
      }
      if (datos.mensaje) textoMensaje.textContent = datos.mensaje;
    }

    async function avanzar() {
      if (enCurso) return;
      enCurso = true;
      pausado = false;
      if (botonPausar) {
        botonPausar.hidden = false;
        botonPausar.textContent = "Pausar";
      }
      if (estado) estado.textContent = "Procesando…";

      const MAX_FALLOS_SEGUIDOS = 6;
      let fallosSeguidos = 0;
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
          datos = { accion: "error", mensaje: "El servidor no respondió (" + error.message + ").", esperar_segundos: 15 };
        }

        mostrar(datos);
        if (datos.accion === "fin") {
          window.location.reload();
          return;
        }
        if (datos.accion === "configuracion") break;
        if (datos.accion === "error") {
          fallosSeguidos += 1;
          if (fallosSeguidos >= MAX_FALLOS_SEGUIDOS) {
            textoMensaje.textContent = (datos.mensaje || "") + " Se detuvo tras varios fallos seguidos; recarga para retomarla.";
            break;
          }
        } else {
          fallosSeguidos = 0;
        }
        const segundos = parseInt(datos.esperar_segundos, 10) || (datos.accion === "error" ? 5 : 0);
        if (segundos > 0) {
          const base = datos.mensaje || "Esperando";
          await esperar(segundos, (s) => {
            textoMensaje.textContent = base + " Sigue en " + Math.max(s, 0) + " s.";
          });
        }
      }
      enCurso = false;
      if (estado) estado.textContent = pausado ? "En pausa" : "Detenida";
      if (botonPausar) botonPausar.textContent = "Reanudar";
    }

    if (botonPausar) {
      botonPausar.addEventListener("click", () => {
        if (enCurso) {
          pausado = true;
          textoMensaje.textContent = "Pausando al terminar el paso actual…";
        } else {
          avanzar();
        }
      });
    }
    avanzar();
  }

  function iniciarDecisiones() {
    document.querySelectorAll("form[data-ic-decision]").forEach((formulario) => {
      formulario.addEventListener("submit", async (evento) => {
        evento.preventDefault();
        const mensaje = formulario.querySelector("[data-ic-decision-mensaje]");
        const datos = new FormData(formulario);
        if (evento.submitter && evento.submitter.name) datos.set(evento.submitter.name, evento.submitter.value);
        const botones = formulario.querySelectorAll("button");
        botones.forEach((b) => (b.disabled = true));
        try {
          const respuesta = await fetch(formulario.action, {
            method: "POST",
            headers: { Accept: "application/json" },
            credentials: "same-origin",
            body: datos,
          });
          const resultado = await respuesta.json();
          mensaje.textContent = resultado.mensaje || "";
          if (resultado.ok) actualizarEstado(formulario, datos);
        } catch (error) {
          mensaje.textContent = "No se pudo guardar la decisión (" + error.message + ").";
        } finally {
          botones.forEach((b) => (b.disabled = false));
        }
      });
    });
  }

  function actualizarEstado(formulario, datos) {
    const decision = datos.get("decision");
    const por = String(datos.get("por") || "").trim();
    const nota = String(datos.get("nota") || "").trim();
    const textos = { atendida: "Atendida", falso_positivo: "Falso positivo" };
    const id = formulario.action.match(/conversacion\/(\d+)\//);
    if (!id) return;
    // La decisión es por conversación: se actualizan todas sus filas.
    document.querySelectorAll('[data-ic-estado="' + id[1] + '"]').forEach((celda) => {
      celda.replaceChildren();
      const etiqueta = document.createElement("span");
      etiqueta.className = "ic-etiqueta ic-etiqueta--" + decision;
      etiqueta.textContent = textos[decision] || decision;
      const detalle = document.createElement("div");
      detalle.className = "small";
      detalle.textContent = "por " + por + (nota ? " · " + nota : "");
      celda.append(etiqueta, detalle);
    });
    document.querySelectorAll("[data-ic-por]").forEach((campo) => {
      if (!campo.value) campo.value = por;
    });
    const desplegable = formulario.closest("details");
    if (desplegable) desplegable.open = false;
  }

  document.addEventListener("DOMContentLoaded", () => {
    iniciarTurnos();
    iniciarProgreso();
    iniciarDecisiones();
  });
})();
