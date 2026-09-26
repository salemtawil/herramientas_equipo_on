(function () {
  const THEME_KEY = "theme";
  const SIDEBAR_KEY = "sidebarCollapsed";

  function getInitialTheme() {
    const storedTheme = localStorage.getItem(THEME_KEY);
    if (storedTheme === "dark" || storedTheme === "light") {
      return storedTheme;
    }

    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      const label = theme === "dark" ? "Modo claro" : "Modo oscuro";
      const text = button.querySelector(".theme-toggle__label");
      if (text) {
        text.textContent = label;
      } else {
        button.textContent = label;
      }
      button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    });
  }

  function initThemeToggle() {
    applyTheme(getInitialTheme());

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const nextTheme =
          document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        localStorage.setItem(THEME_KEY, nextTheme);
        applyTheme(nextTheme);
      });
    });
  }

  function initBackButtons() {
    document.querySelectorAll("[data-back-button]").forEach((button) => {
      button.addEventListener("click", () => {
        const fallback = button.getAttribute("data-fallback") || "/";
        if (window.history.length > 1) {
          window.history.back();
          return;
        }
        window.location.href = fallback;
      });
    });
  }

  const MOBILE_NAV_QUERY = window.matchMedia ? window.matchMedia("(max-width: 900px)") : null;

  function isMobileNav() {
    return Boolean(MOBILE_NAV_QUERY && MOBILE_NAV_QUERY.matches);
  }

  function setToggleLabels(expanded, openLabel, closeLabel, shortOpen, shortClose) {
    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      const label = expanded ? closeLabel : openLabel;
      button.setAttribute("aria-expanded", expanded ? "true" : "false");
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      const text = button.querySelector(".sidebar-icon-toggle__label");
      if (text) text.textContent = expanded ? shortClose : shortOpen;
    });
  }

  function applySidebarState(collapsed) {
    const shell = document.querySelector("[data-sidebar-shell]");
    if (!shell) return;

    shell.classList.toggle("is-sidebar-collapsed", collapsed);
    document.documentElement.classList.toggle("has-sidebar-collapsed", collapsed);

    if (!isMobileNav()) {
      setToggleLabels(!collapsed, "Expandir menú", "Contraer menú", "Menú", "Menú");
    }
  }

  function setMobileNav(open, options) {
    const shell = document.querySelector("[data-sidebar-shell]");
    if (!shell) return;
    shell.classList.toggle("is-nav-open", open);
    setToggleLabels(open, "Abrir menú", "Cerrar menú", "Menú", "Cerrar");

    if (options && options.focusFirstLink && open) {
      const firstLink = shell.querySelector(".app-sidebar__nav a");
      if (firstLink) firstLink.focus();
    }
    if (options && options.focusToggle && !open) {
      const toggle = shell.querySelector("[data-sidebar-toggle]");
      if (toggle) toggle.focus();
    }
  }

  function initSidebarToggle() {
    const storedState = localStorage.getItem(SIDEBAR_KEY);
    applySidebarState(storedState === "true");
    if (isMobileNav()) setMobileNav(false);

    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const shell = document.querySelector("[data-sidebar-shell]");
        if (isMobileNav()) {
          setMobileNav(!shell?.classList.contains("is-nav-open"), { focusFirstLink: true });
          return;
        }
        const collapsed = !shell?.classList.contains("is-sidebar-collapsed");
        localStorage.setItem(SIDEBAR_KEY, String(collapsed));
        applySidebarState(collapsed);
      });
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || !isMobileNav()) return;
      const shell = document.querySelector("[data-sidebar-shell]");
      if (shell && shell.classList.contains("is-nav-open")) {
        setMobileNav(false, { focusToggle: true });
      }
    });

    if (MOBILE_NAV_QUERY) {
      const onChange = () => {
        if (isMobileNav()) {
          setMobileNav(false);
        } else {
          document.querySelector("[data-sidebar-shell]")?.classList.remove("is-nav-open");
          applySidebarState(localStorage.getItem(SIDEBAR_KEY) === "true");
        }
      };
      if (MOBILE_NAV_QUERY.addEventListener) {
        MOBILE_NAV_QUERY.addEventListener("change", onChange);
      } else if (MOBILE_NAV_QUERY.addListener) {
        MOBILE_NAV_QUERY.addListener(onChange);
      }
    }
  }

  function sortTableByColumn(table, index, asc) {
    const tbody = table.querySelector("tbody");
    if (!tbody) return;

    const rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort((a, b) => {
      const aText = (a.children[index]?.innerText || "").trim().replace("%", "");
      const bText = (b.children[index]?.innerText || "").trim().replace("%", "");

      const aNum = parseFloat(aText.replace(",", "."));
      const bNum = parseFloat(bText.replace(",", "."));
      const numeric = !Number.isNaN(aNum) && !Number.isNaN(bNum);

      if (numeric) {
        return asc ? aNum - bNum : bNum - aNum;
      }

      return asc
        ? aText.localeCompare(bText, "es", { numeric: true })
        : bText.localeCompare(aText, "es", { numeric: true });
    });

    rows.forEach((row) => tbody.appendChild(row));
  }

  function initSortableTables() {
    document.querySelectorAll(".tabla-ordenable").forEach((table) => {
      if (table.dataset.sortableBound === "true") return;
      table.dataset.sortableBound = "true";

      const headers = table.querySelectorAll("th");
      headers.forEach((header, index) => {
        header.style.cursor = "pointer";
        header.setAttribute("role", "button");
        header.setAttribute("tabindex", "0");
        header.setAttribute("aria-sort", "none");

        function toggleSort() {
          const asc = !header.classList.contains("asc");
          headers.forEach((th) => {
            th.classList.remove("asc", "desc");
            th.setAttribute("aria-sort", "none");
          });
          header.classList.add(asc ? "asc" : "desc");
          header.setAttribute("aria-sort", asc ? "ascending" : "descending");
          sortTableByColumn(table, index, asc);
        }

        header.addEventListener("click", () => {
          toggleSort();
        });
        header.addEventListener("keydown", (event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          toggleSort();
        });
      });
    });
  }

  function showProcessingOverlay(message) {
    const overlay = document.getElementById("global-processing-overlay");
    const overlayText = document.getElementById("global-processing-text");
    if (!overlay) return;

    if (overlayText && message) {
      overlayText.textContent = message;
    }

    overlay.classList.add("is-visible");
    overlay.setAttribute("aria-hidden", "false");
  }

  function hideProcessingOverlay() {
    const overlay = document.getElementById("global-processing-overlay");
    if (!overlay) return;

    overlay.classList.remove("is-visible");
    overlay.setAttribute("aria-hidden", "true");
  }

  // Los controles se deshabilitan en el siguiente tick: el navegador ya construyó
  // los datos del envío (incluido name/value del botón pulsado), así que no se pierden.
  function disableFormControls(form, submitter) {
    window.setTimeout(() => {
      const elements = form.querySelectorAll("button, input, select, textarea");
      elements.forEach((element) => {
        if (submitter && element === submitter) return;
        if (!element.disabled) {
          element.disabled = true;
          element.dataset.guardDisabled = "true";
        }
      });
    }, 0);
  }

  function isDownloadSubmit(form, submitter) {
    if (form.hasAttribute("data-download")) return true;
    if (!submitter) return false;
    if (submitter.hasAttribute("data-download")) return true;
    return String(submitter.value || "").startsWith("descargar");
  }

  function releaseForm(form) {
    delete form.dataset.submitting;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("[data-guard-disabled]").forEach((element) => {
      element.disabled = false;
      delete element.dataset.guardDisabled;
    });
    form.querySelectorAll("[data-original-label]").forEach((element) => {
      element.textContent = element.dataset.originalLabel;
      delete element.dataset.originalLabel;
    });
  }

  // Evita envíos dobles en formularios POST. Las descargas no navegan, así que el
  // formulario se libera a los pocos segundos para permitir otra descarga.
  function initDoubleSubmitGuard() {
    document.addEventListener("submit", (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
      if ((form.getAttribute("method") || "get").toLowerCase() !== "post") return;
      if (form.hasAttribute("data-allow-resubmit")) return;

      if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }

      const submitter = event.submitter || null;
      form.dataset.submitting = "true";
      form.setAttribute("aria-busy", "true");
      window.setTimeout(() => {
        if (submitter && !submitter.disabled) {
          submitter.disabled = true;
          submitter.dataset.guardDisabled = "true";
        }
      }, 0);

      if (isDownloadSubmit(form, submitter)) {
        window.setTimeout(() => releaseForm(form), 2500);
      }
    });

    // Al volver con el botón «Atrás» el navegador puede restaurar la página congelada.
    window.addEventListener("pageshow", (event) => {
      if (!event.persisted) return;
      document.querySelectorAll("form[data-submitting]").forEach(releaseForm);
      hideProcessingOverlay();
    });
  }

  // Confirmación explícita para acciones irreversibles (data-confirm en el formulario
  // o en el botón). Sin JavaScript el formulario se envía sin este paso.
  function initConfirmations() {
    const dialog = document.getElementById("confirm-dialog");
    let pending = null;

    function ask(form, submitter, message, acceptLabel) {
      if (!dialog || typeof dialog.showModal !== "function") {
        return window.confirm(message);
      }
      pending = { form, submitter, opener: submitter || document.activeElement };
      dialog.querySelector("#confirm-dialog-text").textContent = message;
      const accept = dialog.querySelector("[data-confirm-accept]");
      accept.textContent = acceptLabel || "Confirmar";
      dialog.returnValue = "";
      dialog.showModal();
      dialog.querySelector("[data-confirm-cancel]").focus();
      return null;
    }

    if (dialog) {
      dialog.addEventListener("close", () => {
        const current = pending;
        pending = null;
        if (!current) return;
        if (dialog.returnValue === "confirmar") {
          current.form.dataset.confirmed = "true";
          if (typeof current.form.requestSubmit === "function") {
            current.form.requestSubmit(current.submitter || undefined);
          } else {
            current.form.submit();
          }
        } else if (current.opener && typeof current.opener.focus === "function") {
          current.opener.focus();
        }
      });
    }

    document.addEventListener(
      "submit",
      (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        const submitter = event.submitter || null;
        const source = submitter && submitter.hasAttribute("data-confirm") ? submitter : form;
        const message = source.getAttribute("data-confirm");
        if (!message) return;

        if (form.dataset.confirmed === "true") {
          delete form.dataset.confirmed;
          return;
        }

        const answer = ask(form, submitter, message, source.getAttribute("data-confirm-accept"));
        if (answer === true) return;
        event.preventDefault();
        event.stopImmediatePropagation();
      },
      true
    );
  }

  function initProcessingForms() {
    document.querySelectorAll("form[data-processing-message]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (event.defaultPrevented) return;
        const submitter = event.submitter || null;
        if (isDownloadSubmit(form, submitter)) return;
        const buttonMessage = submitter ? submitter.getAttribute("data-processing-message") : "";
        const formMessage = form.getAttribute("data-processing-message") || "";
        const message = buttonMessage || formMessage;

        if (!message) return;

        if (submitter && submitter.dataset.loadingLabel) {
          submitter.dataset.originalLabel = submitter.textContent;
          submitter.textContent = submitter.dataset.loadingLabel;
        }

        showProcessingOverlay(message);
        disableFormControls(form, submitter);
      });
    });
  }

  async function comprimirArchivoGzip(file) {
    const gzipStream = file.stream().pipeThrough(new CompressionStream("gzip"));
    const compressedBlob = await new Response(gzipStream).blob();
    return new File([compressedBlob], `${file.name}.gz`, {
      type: "application/gzip",
      lastModified: file.lastModified,
    });
  }

  function initCompressedUploadForms() {
    document.querySelectorAll("form[data-compress-upload='gzip']").forEach((form) => {
      form.addEventListener("submit", async (event) => {
        if (form.dataset.compressedSubmitting === "true") {
          delete form.dataset.compressedSubmitting;
          return;
        }

        const input = form.querySelector("input[type='file']");
        const file = input?.files?.[0];
        if (!file || file.name.toLowerCase().endsWith(".gz")) return;

        const threshold = Number.parseInt(form.dataset.compressMinBytes || "4194304", 10);
        if (file.size < threshold) return;

        event.preventDefault();
        event.stopImmediatePropagation();

        if (!("CompressionStream" in window) || !("DataTransfer" in window)) {
          window.alert(
            "Este archivo es grande. Comprímelo como .csv.gz o intenta desde un navegador actualizado."
          );
          return;
        }

        const submitter = event.submitter || null;
        showProcessingOverlay("Comprimiendo el CSV para poder subirlo a Vercel...");

        try {
          const compressedFile = await comprimirArchivoGzip(file);
          const dataTransfer = new DataTransfer();
          dataTransfer.items.add(compressedFile);
          input.files = dataTransfer.files;
          form.dataset.compressedSubmitting = "true";

          if (typeof form.requestSubmit === "function") {
            form.requestSubmit(submitter);
          } else {
            form.submit();
          }
        } catch (error) {
          hideProcessingOverlay();
          window.alert("No se pudo comprimir el CSV. Intenta comprimirlo manualmente como .csv.gz.");
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initThemeToggle();
    initSidebarToggle();
    initBackButtons();
    initSortableTables();
    initConfirmations();
    initCompressedUploadForms();
    initProcessingForms();
    initDoubleSubmitGuard();
  });
})();
