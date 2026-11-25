// Auditoría CSAT: guardado al instante de cada ficha, pestañas y «Revisar con IA» en tandas.
// Sin JavaScript todo sigue funcionando con formularios normales (un clic recarga la página).
(function () {
  "use strict";

  const MAX_FALLOS_SEGUIDOS = 3;
  const ESPERA_TRAS_FALLO = 15;

  // Cada respuesta del servidor trae un analysis_id nuevo; todas las peticiones se envían
  // de una en una y con el más reciente, así que se comparte una sola cadena de envíos.
  let cadena = Promise.resolve();
  let navegando = false;
  function enSerie(tarea) {
    const resultado = cadena.then(tarea);
    cadena = resultado.catch(() => {});
    return resultado;
  }

  function guardarToken(valor) {
    if (!valor) return;
    document.querySelectorAll('input[name="analysis_id"]').forEach((campo) => {
      campo.value = valor;
    });
  }

  function ultimoToken(formulario) {
    const campo = formulario.querySelector('input[name="analysis_id"]');
    return campo ? campo.value : "";
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

  function iniciar() {
    const boton = document.querySelector("[data-csat-ia]");
    const estado = document.querySelector("[data-csat-ia-estado]");
    if (!boton || !estado || !boton.form) return;
    const formulario = boton.form;

    // Muestra la tabla con el estado final. Se envía por POST porque el estado viaja firmado
    // en la página (no cabe en una URL) y así no depende de qué servidor atienda la petición.
    // Ya no se aceptan más decisiones: la página se va a recargar con el último token.
    function bloquearDecisiones() {
      navegando = true;
      document.querySelectorAll('[data-csat-ficha] button[name="justificable"]').forEach((b) => {
        b.disabled = true;
      });
    }

    function verEstado() {
      bloquearDecisiones();
      const accion = document.createElement("input");
      accion.type = "hidden";
      accion.name = "accion";
      accion.value = "ver_estado";
      formulario.appendChild(accion);
      formulario.submit();
    }

    async function paso() {
      return enSerie(async () => {
        const datos = new FormData(formulario);
        datos.set("accion", "auditar_con_ia");
        const respuesta = await fetch(formulario.getAttribute("action") || window.location.pathname, {
          method: "POST",
          body: datos,
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!respuesta.ok) throw new Error("HTTP " + respuesta.status);
        const json = await respuesta.json();
        guardarToken(json.analysis_id);
        return json;
      });
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
        // Cada paso devuelve el estado actualizado: el siguiente paso debe partir de él.
        const avance =
          "Revisados " + revisados + " · quedan " + datos.pendientes + " de " + datos.total_negativos + " negativos.";
        if (datos.fin) {
          const cierre = revisados > 0 ? " Actualizando las fichas…" : "";
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
      if (revisados > 0 && ultimo) {
        // Va por la misma cola: espera las decisiones pendientes y parte del token más reciente.
        bloquearDecisiones();
        enSerie(() => verEstado());
      } else {
        boton.disabled = false;
      }
    }

    boton.addEventListener("click", auditarTodo);
  }

  // ---- Fichas: guardado al instante ----

  const TEXTO_KPI_EXCLUIDOS_CERO = "Ningún negativo excluido todavía";

  function porcentaje(valor) {
    // El servidor imprime los porcentajes como decimales (85.0), no como enteros.
    const n = Number(valor);
    return Number.isInteger(n) ? n.toFixed(1) : String(n);
  }

  function ponerKpis(kpis) {
    if (!kpis) return;
    const campo = (clave) => document.querySelector('[data-csat-kpi="' + clave + '"]');
    const poner = (clave, texto) => {
      const el = campo(clave);
      if (el) el.textContent = texto;
    };
    poner("csat_real", porcentaje(kpis.csat_real));
    poner("csat_ajustado", porcentaje(kpis.csat_ajustado));
    poner("negativos", String(kpis.negativos));
    poner("por_confirmar", String(kpis.por_confirmar));

    const delta = campo("delta");
    if (delta) {
      const d = Number(kpis.delta);
      delta.textContent = d > 0 ? "▲ " + porcentaje(d) : d < 0 ? "▼ " + porcentaje(Math.abs(d)) : "= 0";
      delta.classList.remove("is-up", "is-down", "is-igual");
      delta.classList.add(d > 0 ? "is-up" : d < 0 ? "is-down" : "is-igual");
    }

    const excluidos = campo("excluidos");
    const nota = excluidos ? excluidos.parentElement : null;
    if (nota) {
      const n = Number(kpis.excluidos);
      const numero = document.createElement("span");
      numero.setAttribute("data-csat-kpi", "excluidos");
      numero.textContent = String(n);
      nota.textContent = "";
      if (n === 0) {
        numero.hidden = true;
        nota.append(TEXTO_KPI_EXCLUIDOS_CERO, numero);
      } else {
        nota.append("Sin ", numero, " negativos que no fueron culpa del agente");
      }
    }
  }

  function ponerPasos(pasos) {
    (pasos || []).forEach((paso) => {
      const el = document.querySelector('[data-csat-paso="' + paso.clave + '"]');
      if (!el) return;
      el.classList.remove("is-hecho", "is-actual", "is-pendiente");
      el.classList.add("is-" + paso.estado);
      if (paso.estado === "actual") el.setAttribute("aria-current", "step");
      else el.removeAttribute("aria-current");
      const detalle = el.querySelector("[data-csat-paso-detalle]");
      if (detalle) detalle.textContent = paso.detalle;
    });
  }

  function ponerPestanas(pestanas) {
    if (!pestanas) return;
    document.querySelectorAll("[data-csat-pestana]").forEach((boton) => {
      const conteo = boton.querySelector("[data-csat-pestana-conteo]");
      const valor = pestanas[boton.getAttribute("data-csat-pestana")];
      if (conteo && valor !== undefined) conteo.textContent = String(valor);
    });
  }

  function ponerListo(kpis) {
    const listo = document.querySelector("[data-csat-listo]");
    if (listo && kpis) listo.hidden = Number(kpis.por_confirmar) !== 0;
  }

  function mostrarAviso(texto) {
    const aviso = document.querySelector("[data-csat-aviso]");
    if (!aviso) return;
    aviso.textContent = texto || "";
    aviso.hidden = !texto;
  }

  function claseDecision(valor) {
    return { "SÍ": "is-si", "NO": "is-no", "TAL VEZ": "is-dudoso" }[valor] || "";
  }

  function elemento(etiqueta, clase, texto) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function ponerResumen(formulario, ficha) {
    const resumen = formulario.querySelector("[data-csat-ficha-resumen]");
    if (!resumen) return;
    const insignia = elemento("span", "csat-insignia " + claseDecision(ficha.justificable));
    const marca = elemento("span", "", "✓");
    marca.setAttribute("aria-hidden", "true");
    insignia.append(marca, " Confirmado: ", elemento("span", "", ficha.decision_texto));
    if (ficha.origen_texto) insignia.append(" · ", elemento("span", "", ficha.origen_texto));

    const detalle = elemento("span", "csat-ficha__detalle");
    if (ficha.ia) {
      detalle.append(ficha.ia.decision === ficha.justificable ? "Coincide con la IA" : "La IA proponía: " + ficha.ia.texto, " · ");
    }
    detalle.append("Motivo: ", elemento("span", "", ficha.motivo || "sin motivo"));
    if (ficha.nota) detalle.append(" · Nota: ", elemento("span", "", ficha.nota));

    resumen.textContent = "";
    resumen.append(insignia, detalle);
  }

  function ponerFicha(formulario, ficha) {
    if (!ficha) return;
    formulario.setAttribute("data-confirmada", ficha.confirmada ? "1" : "0");
    formulario.querySelectorAll('button[name="justificable"]').forEach((boton) => {
      const actual = boton.value === ficha.justificable;
      boton.classList.toggle("is-actual", actual);
      boton.setAttribute("aria-pressed", actual ? "true" : "false");
    });
    if (ficha.confirmada) {
      ponerResumen(formulario, ficha);
      const cuerpo = formulario.querySelector("[data-csat-ficha-cuerpo]");
      if (cuerpo) cuerpo.open = false;
    }
  }

  function estadoFicha(formulario, texto, esError) {
    const el = formulario.querySelector("[data-csat-ficha-estado]");
    if (!el) return;
    el.textContent = texto || "";
    el.style.color = esError ? "var(--status-bad, #b42318)" : "";
  }

  function enviarDecision(formulario, justificable) {
    return enSerie(async () => {
      estadoFicha(formulario, "Guardando…", false);
      formulario.classList.add("is-guardando");
      try {
        const datos = new FormData(formulario);
        datos.set("accion", "decidir");
        datos.set("justificable", justificable);
        datos.set("analysis_id", ultimoToken(formulario) || datos.get("analysis_id"));
        const respuesta = await fetch(formulario.getAttribute("action") || window.location.pathname, {
          method: "POST",
          body: datos,
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        let json = null;
        try {
          json = await respuesta.json();
        } catch (error) {
          json = null;
        }
        if (json) guardarToken(json.analysis_id);
        if (!respuesta.ok && !json) throw new Error("HTTP " + respuesta.status);
        if (!json || !json.ok) {
          estadoFicha(formulario, (json && json.error) || "No se pudo guardar. Inténtalo de nuevo.", true);
          if (json) mostrarAviso(json.advertencia);
          return;
        }
        estadoFicha(formulario, "", false);
        try {
          ponerFicha(formulario, json.ficha);
          ponerKpis(json.kpis);
          ponerPasos(json.pasos);
          ponerPestanas(json.pestanas);
          ponerListo(json.kpis);
          mostrarAviso(json.advertencia);
        } catch (errorVista) {
          estadoFicha(formulario, "Guardado; recarga la página para ver el estado actualizado.", false);
        }
      } catch (error) {
        estadoFicha(formulario, "No se pudo guardar (" + error.message + "). Inténtalo de nuevo.", true);
      } finally {
        formulario.classList.remove("is-guardando");
      }
    });
  }

  function iniciarFichas() {
    if (typeof fetch !== "function" || typeof FormData !== "function") return;
    if (!document.querySelector("[data-csat-ficha]")) return;

    document.addEventListener("click", (evento) => {
      const boton = evento.target.closest ? evento.target.closest('[data-csat-ficha] button[name="justificable"]') : null;
      if (!boton) return;
      evento.preventDefault();
      if (navegando) return;
      enviarDecision(boton.form, boton.value);
    });

    // «Cambiar decisión» es el <summary> del <details>: solo reabre la ficha, no envía nada.

    const pestanas = document.querySelectorAll("[data-csat-pestana]");
    function filtrar(clave) {
      pestanas.forEach((boton) => {
        const activa = boton.getAttribute("data-csat-pestana") === clave;
        boton.classList.toggle("is-activa", activa);
        boton.setAttribute("aria-pressed", activa ? "true" : "false");
      });
      document.querySelectorAll("[data-csat-ficha]").forEach((ficha) => {
        const confirmada = ficha.getAttribute("data-confirmada") === "1";
        const visible = clave === "todos" || (clave === "confirmados" ? confirmada : !confirmada);
        ficha.style.display = visible ? "" : "none";
      });
    }
    pestanas.forEach((boton) => {
      boton.addEventListener("click", () => filtrar(boton.getAttribute("data-csat-pestana")));
    });
    const activa = document.querySelector("[data-csat-pestana].is-activa");
    if (activa) filtrar(activa.getAttribute("data-csat-pestana"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    iniciarFichas();
    iniciar();
  });
})();
