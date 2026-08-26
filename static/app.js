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
      button.textContent = theme === "dark" ? "Modo claro" : "Modo oscuro";
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

  function applySidebarState(collapsed) {
    const shell = document.querySelector("[data-sidebar-shell]");
    const sidebar = document.getElementById("app-sidebar");
    if (!shell || !sidebar) return;

    shell.classList.toggle("is-sidebar-collapsed", collapsed);
    document.documentElement.classList.toggle("has-sidebar-collapsed", collapsed);
    sidebar.setAttribute("aria-hidden", collapsed ? "true" : "false");

    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      button.setAttribute("aria-expanded", collapsed ? "false" : "true");
      button.setAttribute("aria-label", collapsed ? "Mostrar menu" : "Ocultar menu");
      button.setAttribute("title", collapsed ? "Mostrar menu" : "Ocultar menu");
    });
  }

  function initSidebarToggle() {
    const storedState = localStorage.getItem(SIDEBAR_KEY);
    applySidebarState(storedState === "true");

    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const shell = document.querySelector("[data-sidebar-shell]");
        const collapsed = !shell?.classList.contains("is-sidebar-collapsed");
        localStorage.setItem(SIDEBAR_KEY, String(collapsed));
        applySidebarState(collapsed);
      });
    });
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

  function disableFormControls(form, submitter) {
    window.setTimeout(() => {
      const elements = form.querySelectorAll("button, input, select, textarea");
      elements.forEach((element) => {
        if (submitter && element === submitter) return;
        element.disabled = true;
      });
    }, 0);
  }

  function initProcessingForms() {
    document.querySelectorAll("form[data-processing-message]").forEach((form) => {
      form.addEventListener("submit", (event) => {
        const submitter = event.submitter || null;
        const buttonMessage = submitter ? submitter.getAttribute("data-processing-message") : "";
        const formMessage = form.getAttribute("data-processing-message") || "";
        const message = buttonMessage || formMessage;

        if (!message) return;

        if (submitter && submitter.dataset.loadingLabel) {
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
    initCompressedUploadForms();
    initProcessingForms();
  });
})();
