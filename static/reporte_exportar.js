/* Descarga del reporte de agentes en Word (.docx), PDF o texto (.txt).
   Todo se genera en el navegador con los datos que ya trajo la página:
   no vuelve a consultar Chatwoot ni usa librerías externas. */
(function () {
  "use strict";

  const fuente = document.getElementById("reporte-datos-exportacion");
  const botones = document.querySelectorAll("[data-exportar-reporte]");
  if (!fuente || !botones.length) return;

  let datos;
  try {
    datos = JSON.parse(fuente.textContent);
  } catch (error) {
    return;
  }

  const estado = document.getElementById("reporte-descarga-estado");
  const TITULO = "Reporte de agentes";

  function avisar(texto) {
    if (estado) estado.textContent = texto;
  }

  function generadoEl() {
    return new Date().toLocaleString("es", { dateStyle: "short", timeStyle: "short" });
  }

  function lineasCabecera() {
    const lineas = [];
    if (datos.periodo) lineas.push("Periodo: " + datos.periodo);
    if (datos.fuente) lineas.push("Fuente: " + datos.fuente);
    lineas.push("Generado: " + generadoEl());
    return lineas;
  }

  // Secciones en el orden del reporte: resumen general, resumen por turno y cada turno.
  function secciones() {
    const lista = [
      {
        titulo: "Resumen general",
        columnas: ["Métrica", "Valor"],
        filas: datos.resumen || [],
        total: [],
      },
      {
        titulo: "Resumen por turno",
        columnas: datos.resumen_turnos.columnas,
        filas: datos.resumen_turnos.filas,
        total: datos.resumen_turnos.total,
      },
    ];
    (datos.turnos || []).forEach((turno) => {
      lista.push({
        titulo: turno.nombre + " (" + turno.filas.length + (turno.filas.length === 1 ? " agente)" : " agentes)"),
        columnas: turno.columnas,
        filas: turno.filas,
        total: turno.total,
      });
    });
    return lista;
  }

  function texto(valor) {
    return valor === null || valor === undefined ? "" : String(valor);
  }

  function esNumero(valor) {
    return typeof valor === "number";
  }

  function nombreArchivo(extension) {
    const fecha = (datos.fecha_archivo || new Date().toISOString().slice(0, 10)).replace(/[^0-9-]/g, "");
    return "reporte-agentes_" + fecha + "." + extension;
  }

  function descargar(contenido, tipo, nombre) {
    const blob = contenido instanceof Blob ? contenido : new Blob([contenido], { type: tipo });
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = nombre;
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  /* ---------- Texto (.txt) ---------- */

  function tablaTexto(seccion) {
    const filas = seccion.filas.map((fila) => fila.map(texto));
    const total = seccion.total && seccion.total.length ? seccion.total.map(texto) : null;
    const todas = [seccion.columnas].concat(filas, total ? [total] : []);
    const anchos = seccion.columnas.map((_, i) => Math.max(...todas.map((fila) => texto(fila[i]).length)));
    const numericas = seccion.columnas.map((_, i) => i > 0 && seccion.filas.every((fila) => esNumero(fila[i]) || fila[i] === ""));

    const formatear = (fila) =>
      fila
        .map((valor, i) => (numericas[i] ? texto(valor).padStart(anchos[i]) : texto(valor).padEnd(anchos[i])))
        .join("   ")
        .replace(/\s+$/, "");
    const separador = anchos.map((ancho) => "-".repeat(ancho)).join("   ");

    const lineas = [formatear(seccion.columnas), separador];
    filas.forEach((fila) => lineas.push(formatear(fila)));
    if (total) {
      lineas.push(separador);
      lineas.push(formatear(total));
    }
    return lineas;
  }

  function generarTxt() {
    const lineas = [TITULO.toUpperCase(), "=".repeat(TITULO.length)].concat(lineasCabecera(), [""]);
    secciones().forEach((seccion) => {
      lineas.push(seccion.titulo.toUpperCase());
      lineas.push("");
      lineas.push(...tablaTexto(seccion));
      lineas.push("", "");
    });
    // BOM + CRLF para que el Bloc de notas muestre bien acentos y saltos de línea.
    return "﻿" + lineas.join("\r\n");
  }

  /* ---------- Word (.docx) ---------- */

  function xml(valor) {
    return texto(valor)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function parrafo(contenido, opciones) {
    const o = opciones || {};
    const pPr = [
      o.estilo ? '<w:pStyle w:val="' + o.estilo + '"/>' : "",
      o.antes || o.despues ? '<w:spacing w:before="' + (o.antes || 0) + '" w:after="' + (o.despues || 0) + '"/>' : "",
      o.alinear ? '<w:jc w:val="' + o.alinear + '"/>' : "",
    ].join("");
    const rPr = [o.negrita ? "<w:b/>" : "", o.color ? '<w:color w:val="' + o.color + '"/>' : "", o.tamano ? '<w:sz w:val="' + o.tamano + '"/>' : ""].join("");
    return (
      "<w:p>" + (pPr ? "<w:pPr>" + pPr + "</w:pPr>" : "") +
      "<w:r>" + (rPr ? "<w:rPr>" + rPr + "</w:rPr>" : "") +
      '<w:t xml:space="preserve">' + xml(contenido) + "</w:t></w:r></w:p>"
    );
  }

  const ANCHO_PAGINA = 10080; // 7 pulgadas útiles (carta con márgenes de 0,75")

  function celda(valor, ancho, opciones) {
    const o = opciones || {};
    return (
      "<w:tc><w:tcPr>" +
      '<w:tcW w:w="' + ancho + '" w:type="dxa"/>' +
      (o.fondo ? '<w:shd w:val="clear" w:color="auto" w:fill="' + o.fondo + '"/>' : "") +
      "</w:tcPr>" +
      parrafo(valor, { negrita: o.negrita, alinear: o.derecha ? "right" : "", color: o.color }) +
      "</w:tc>"
    );
  }

  function tablaWord(seccion) {
    const n = seccion.columnas.length;
    const primera = n === 2 ? 4200 : Math.round(ANCHO_PAGINA * 0.3);
    const resto = Math.floor((ANCHO_PAGINA - primera) / Math.max(n - 1, 1));
    const anchos = seccion.columnas.map((_, i) => (i === 0 ? primera : resto));
    const derecha = (i, fila) => i > 0 && esNumero(fila[i]);
    const borde = '<w:{b} w:val="single" w:sz="4" w:space="0" w:color="C2CCD5"/>';
    const bordes = ["top", "left", "bottom", "right", "insideH", "insideV"].map((b) => borde.replace("{b}", b)).join("");

    let salida =
      "<w:tbl><w:tblPr>" +
      '<w:tblW w:w="' + ANCHO_PAGINA + '" w:type="dxa"/>' +
      "<w:tblBorders>" + bordes + "</w:tblBorders>" +
      '<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar>' +
      "</w:tblPr><w:tblGrid>" + anchos.map((a) => '<w:gridCol w:w="' + a + '"/>').join("") + "</w:tblGrid>";

    salida +=
      "<w:tr><w:trPr><w:tblHeader/></w:trPr>" +
      seccion.columnas.map((col, i) => celda(col, anchos[i], { negrita: true, fondo: "DCE9E6", color: "07111F", derecha: i > 0 && n > 2 })).join("") +
      "</w:tr>";
    seccion.filas.forEach((fila) => {
      salida += "<w:tr><w:trPr><w:cantSplit/></w:trPr>" + fila.map((valor, i) => celda(valor, anchos[i], { derecha: derecha(i, fila) })).join("") + "</w:tr>";
    });
    if (seccion.total && seccion.total.length) {
      salida += "<w:tr>" + seccion.total.map((valor, i) => celda(valor, anchos[i], { negrita: true, fondo: "F1F4F7", derecha: derecha(i, seccion.total) })).join("") + "</w:tr>";
    }
    return salida + "</w:tbl>";
  }

  function documentoWord() {
    let cuerpo = parrafo(TITULO, { estilo: "Title" });
    lineasCabecera().forEach((linea) => {
      cuerpo += parrafo(linea, { color: "4F5E6E" });
    });
    secciones().forEach((seccion) => {
      cuerpo += parrafo(seccion.titulo, { estilo: "Heading1" });
      cuerpo += tablaWord(seccion);
    });
    return (
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' +
      cuerpo +
      '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>' +
      '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="708" w:footer="708" w:gutter="0"/>' +
      "</w:sectPr></w:body></w:document>"
    );
  }

  const ESTILOS_WORD =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
    "<w:docDefaults><w:rPrDefault><w:rPr>" +
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>' +
    '<w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="es-ES"/>' +
    "</w:rPr></w:rPrDefault>" +
    '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="252" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>' +
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>' +
    '<w:pPr><w:spacing w:after="80"/></w:pPr><w:rPr><w:b/><w:color w:val="07111F"/><w:sz w:val="40"/></w:rPr></w:style>' +
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>' +
    '<w:pPr><w:keepNext/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>' +
    '<w:rPr><w:b/><w:color w:val="0A6D5F"/><w:sz w:val="26"/></w:rPr></w:style>' +
    "</w:styles>";

  const TIPOS_WORD =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
    '<Default Extension="xml" ContentType="application/xml"/>' +
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
    "</Types>";

  const RELACIONES_PAQUETE =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
    "</Relationships>";

  const RELACIONES_DOCUMENTO =
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
    "</Relationships>";

  // ZIP sin compresión (método "stored"): suficiente para un .docx y sin dependencias.
  const TABLA_CRC = (() => {
    const tabla = new Uint32Array(256);
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      tabla[n] = c >>> 0;
    }
    return tabla;
  })();

  function crc32(bytes) {
    let crc = 0xffffffff;
    for (let i = 0; i < bytes.length; i += 1) crc = TABLA_CRC[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    return (crc ^ 0xffffffff) >>> 0;
  }

  function zip(archivos) {
    const codificador = new TextEncoder();
    const ahora = new Date();
    const hora = (ahora.getHours() << 11) | (ahora.getMinutes() << 5) | Math.floor(ahora.getSeconds() / 2);
    const fecha = ((ahora.getFullYear() - 1980) << 9) | ((ahora.getMonth() + 1) << 5) | ahora.getDate();
    const partes = [];
    const central = [];
    let desplazamiento = 0;

    archivos.forEach(([nombre, contenido]) => {
      const nombreBytes = codificador.encode(nombre);
      const datosBytes = codificador.encode(contenido);
      const crc = crc32(datosBytes);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);
      local.setUint16(8, 0, true);
      local.setUint16(10, hora, true);
      local.setUint16(12, fecha, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, datosBytes.length, true);
      local.setUint32(22, datosBytes.length, true);
      local.setUint16(26, nombreBytes.length, true);
      local.setUint16(28, 0, true);
      partes.push(new Uint8Array(local.buffer), nombreBytes, datosBytes);

      const entrada = new DataView(new ArrayBuffer(46));
      entrada.setUint32(0, 0x02014b50, true);
      entrada.setUint16(4, 20, true);
      entrada.setUint16(6, 20, true);
      entrada.setUint16(8, 0x0800, true);
      entrada.setUint16(10, 0, true);
      entrada.setUint16(12, hora, true);
      entrada.setUint16(14, fecha, true);
      entrada.setUint32(16, crc, true);
      entrada.setUint32(20, datosBytes.length, true);
      entrada.setUint32(24, datosBytes.length, true);
      entrada.setUint16(28, nombreBytes.length, true);
      entrada.setUint32(42, desplazamiento, true);
      central.push(new Uint8Array(entrada.buffer), nombreBytes);

      desplazamiento += 30 + nombreBytes.length + datosBytes.length;
    });

    const tamanoCentral = central.reduce((suma, parte) => suma + parte.length, 0);
    const fin = new DataView(new ArrayBuffer(22));
    fin.setUint32(0, 0x06054b50, true);
    fin.setUint16(8, archivos.length, true);
    fin.setUint16(10, archivos.length, true);
    fin.setUint32(12, tamanoCentral, true);
    fin.setUint32(16, desplazamiento, true);

    return new Blob(partes.concat(central, [new Uint8Array(fin.buffer)]), {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
  }

  function generarDocx() {
    return zip([
      ["[Content_Types].xml", TIPOS_WORD],
      ["_rels/.rels", RELACIONES_PAQUETE],
      ["word/document.xml", documentoWord()],
      ["word/_rels/document.xml.rels", RELACIONES_DOCUMENTO],
      ["word/styles.xml", ESTILOS_WORD],
    ]);
  }

  /* ---------- PDF (diálogo de impresión → «Guardar como PDF») ---------- */

  function html(valor) {
    return texto(valor).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function documentoImpresion(hojaEstilos) {
    let cuerpo = "<h1>" + TITULO + "</h1>";
    cuerpo += '<p class="meta">' + lineasCabecera().map(html).join("<br>") + "</p>";
    secciones().forEach((seccion) => {
      cuerpo += "<section><h2>" + html(seccion.titulo) + "</h2><table><thead><tr>";
      cuerpo += seccion.columnas.map((col, i) => "<th" + (i > 0 && seccion.columnas.length > 2 ? ' class="num"' : "") + ">" + html(col) + "</th>").join("");
      cuerpo += "</tr></thead><tbody>";
      seccion.filas.forEach((fila) => {
        cuerpo += "<tr>" + fila.map((v, i) => "<td" + (i > 0 && esNumero(v) ? ' class="num"' : "") + ">" + html(v) + "</td>").join("") + "</tr>";
      });
      cuerpo += "</tbody>";
      if (seccion.total && seccion.total.length) {
        cuerpo += "<tfoot><tr>" + seccion.total.map((v, i) => "<td" + (i > 0 && esNumero(v) ? ' class="num"' : "") + ">" + html(v) + "</td>").join("") + "</tr></tfoot>";
      }
      cuerpo += "</table></section>";
    });
    return (
      '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>' + html(nombreArchivo("pdf").replace(/\.pdf$/, "")) + "</title>" +
      '<link rel="stylesheet" href="' + hojaEstilos + '"></head><body>' + cuerpo + "</body></html>"
    );
  }

  function imprimirPdf() {
    const hojaEstilos = fuente.getAttribute("data-estilos-impresion");
    const marco = document.createElement("iframe");
    marco.setAttribute("aria-hidden", "true");
    marco.tabIndex = -1;
    // Fuera de la vista: solo se usa para imprimir su contenido.
    marco.style.position = "fixed";
    marco.style.right = "0";
    marco.style.bottom = "0";
    marco.style.width = "0";
    marco.style.height = "0";
    marco.style.border = "0";
    marco.srcdoc = documentoImpresion(hojaEstilos);
    marco.addEventListener("load", () => {
      const ventana = marco.contentWindow;
      const enlace = marco.contentDocument && marco.contentDocument.querySelector("link[rel=stylesheet]");
      const imprimir = () => {
        ventana.focus();
        ventana.print();
        setTimeout(() => marco.remove(), 60000);
      };
      if (enlace && !enlace.sheet) enlace.addEventListener("load", imprimir, { once: true });
      else imprimir();
    });
    document.body.appendChild(marco);
  }

  /* ---------- Botones ---------- */

  botones.forEach((boton) => {
    boton.addEventListener("click", () => {
      const formato = boton.getAttribute("data-exportar-reporte");
      try {
        if (formato === "txt") {
          descargar(generarTxt(), "text/plain;charset=utf-8", nombreArchivo("txt"));
          avisar("Descargado " + nombreArchivo("txt") + ".");
        } else if (formato === "docx") {
          descargar(generarDocx(), "", nombreArchivo("docx"));
          avisar("Descargado " + nombreArchivo("docx") + ".");
        } else if (formato === "pdf") {
          imprimirPdf();
          avisar("En la ventana de impresión elige «Guardar como PDF».");
        }
      } catch (error) {
        avisar("No se pudo generar el archivo. Recarga la página e inténtalo de nuevo.");
      }
    });
  });
})();
