(function () {
  const THEME_KEY = "theme";

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
        header.addEventListener("click", () => {
          const asc = !header.classList.contains("asc");
          headers.forEach((th) => th.classList.remove("asc", "desc"));
          header.classList.add(asc ? "asc" : "desc");
          sortTableByColumn(table, index, asc);
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

        showProcessingOverlay(message);
        disableFormControls(form, submitter);
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initThemeToggle();
    initBackButtons();
    initSortableTables();
    initProcessingForms();
  });
})();
