// Interfaz de la bala. Todo texto del modelo o del Sheet se pone con textContent.
"use strict";

const $ = (id) => document.getElementById(id);
let datos = { nombre: "", fichas: [], lugares: [] };
let conversacion = null;
let ocupado = false;
let control = null;        // permite cancelar la respuesta en curso
let siguienteAnexo = 1;
let generacion = 0;        // cambia con cada parte nuevo
const sinMovimiento = matchMedia("(prefers-reduced-motion: reduce)").matches;

function crear(etiqueta, clase, texto) {
  const nodo = document.createElement(etiqueta);
  if (clase) nodo.className = clase;
  if (texto !== undefined) nodo.textContent = texto;
  return nodo;
}

async function pedir(ruta, opciones = {}) {
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new Error("No hay conexión con el servidor.");
  }
  if (!respuesta.ok) {
    const cuerpo = await respuesta.json().catch(() => ({}));
    throw new Error(typeof cuerpo.detail === "string" ? cuerpo.detail : `Error ${respuesta.status}.`);
  }
  return respuesta;
}

const normalizar = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// ---------- Expedientes ----------
function foto(ficha, imagen = ficha.imagenes[0]) {
  const vacia = () => crear("span", "foto sin-foto", "Sin imagen");
  if (!imagen) return vacia();
  const img = crear("img", "foto");
  img.loading = "lazy";
  img.alt = `${imagen.tipo || "Escaneo"} de ${ficha.nombre}. ${imagen.descripcion || ""}`.trim();
  img.onerror = () => img.replaceWith(vacia());
  img.src = imagen.url;
  return img;
}

function listaDeDatos(pares) {
  const lista = crear("dl");
  for (const [campo, valor] of pares) {
    const dd = crear("dd");
    // Los enlaces de las fuentes se pueden abrir
    for (const parte of valor.split(/(https?:\/\/[^\s|]+)/)) {
      if (/^https?:\/\//.test(parte)) {
        const a = crear("a", "", parte);
        a.href = parte; a.target = "_blank"; a.rel = "noopener noreferrer";
        dd.append(a);
      } else dd.append(parte);
    }
    lista.append(crear("dt", "", campo), dd);
  }
  return lista;
}

function verFicha(ficha) {
  const galeria = crear("div", "galeria");
  if (!ficha.imagenes.length) galeria.append(foto(ficha));
  for (const imagen of ficha.imagenes) {
    const figura = crear("figure");
    figura.append(foto(ficha, imagen));
    const pie = [imagen.descripcion, imagen.procedencia && `Procedencia: ${imagen.procedencia}`].filter(Boolean).join(". ");
    if (pie) figura.append(crear("figcaption", "", pie));
    galeria.append(figura);
  }
  abrirVisor(ficha.nombre, "visor-cuerpo", galeria, listaDeDatos(ficha.datos));
}

function abrirVisor(titulo, clase, ...contenido) {
  $("visor-nombre").textContent = titulo;
  $("visor-cuerpo").className = clase;
  $("visor-cuerpo").replaceChildren(...contenido);
  $("visor").showModal();
  // Al cargar la imagen cambia el alto: se vuelve al inicio
  const arriba = () => { $("visor").scrollTop = 0; };
  arriba();
  requestAnimationFrame(arriba);
  $("visor-cuerpo").querySelector("img")?.addEventListener("load", () => requestAnimationFrame(arriba), { once: true });
}

// ---------- Mapa de lugares ----------
function svg(etiqueta, atributos, texto) {
  const nodo = document.createElementNS("http://www.w3.org/2000/svg", etiqueta);
  for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, v);
  if (texto) nodo.textContent = texto;
  return nodo;
}

function dibujarMapa(lugares) {
  const origen = lugares.find((l) => l.datos.some(([c, v]) => c === "tipo" && normalizar(v) === "lugar de los hechos")) || lugares[0];
  const km = ([lat, lon]) => [lon * 111.32 * Math.cos(origen.coordenadas[0] * Math.PI / 180), -lat * 110.57];
  const puntos = lugares.map((l) => ({ l, p: km(l.coordenadas) }));
  const xs = puntos.map((q) => q.p[0]), ys = puntos.map((q) => q.p[1]);
  const minX = Math.min(...xs), minY = Math.min(...ys);
  const ancho = 760, margen = 60;
  const escala = Math.min((ancho - 2 * margen) / Math.max(Math.max(...xs) - minX, .5), 500 / Math.max(Math.max(...ys) - minY, .5));
  const alto = Math.max((Math.max(...ys) - minY) * escala + 2 * margen + 50, 260);
  const lienzo = svg("svg", { viewBox: `0 0 ${ancho} ${alto}`, role: "img", class: "mapa", "aria-label": `Esquema de ubicación: ${lugares.map((l) => l.nombre).join(", ")}` });
  const pos = (p) => [margen + (p[0] - minX) * escala, margen + (p[1] - minY) * escala];
  const [ox, oy] = pos(km(origen.coordenadas));
  for (const { l, p } of puntos) {
    if (l === origen) continue;
    const [x, y] = pos(p);
    lienzo.append(svg("line", { x1: ox, y1: oy, x2: x, y2: y, class: "mapa-linea" }));
  }
  puntos.forEach(({ l, p }, i) => {
    const [x, y] = pos(p);
    lienzo.append(svg("circle", { cx: x, cy: y, r: 19, class: l === origen ? "mapa-origen" : "mapa-punto" }));
    lienzo.append(svg("text", { x, y: y + 8, "text-anchor": "middle", class: "mapa-numero" }, String(i + 1)));
  });
  const y = alto - 22;
  lienzo.append(svg("line", { x1: margen, y1: y, x2: margen + escala, y2: y, class: "mapa-escala" }));
  lienzo.append(svg("text", { x: margen + escala + 12, y: y + 7, class: "mapa-texto" }, "1 km"));
  return lienzo;
}

function verMapa() {
  const enMapa = datos.lugares.filter((l) => l.coordenadas);
  const contenido = [];
  if (enMapa.length > 1) {
    const leyenda = crear("ol", "leyenda");
    leyenda.append(...enMapa.map((l) => crear("li", "", l.nombre)));
    contenido.push(dibujarMapa(enMapa), leyenda, crear("p", "nota",
      "Esquema con ubicaciones aproximadas. Las líneas son rectas: no muestran la ruta que se siguió en 1968."));
  }
  for (const lugar of [...enMapa, ...datos.lugares.filter((l) => !l.coordenadas)]) {
    const numero = enMapa.length > 1 && lugar.coordenadas ? `${enMapa.indexOf(lugar) + 1}. ` : "";
    const bloque = crear("section", "lugar");
    bloque.append(crear("h3", "", numero + lugar.nombre), listaDeDatos(lugar.datos));
    contenido.push(bloque);
  }
  abrirVisor("Lugares", "lugares", ...contenido);
}

function pintarLista() {
  const busca = normalizar($("buscar").value.trim());
  const visibles = datos.fichas.filter((f) =>
    normalizar([f.nombre, ...f.datos.map((d) => d[1])].join(" ")).includes(busca));
  $("total").textContent = datos.fichas.length;
  $("lista").replaceChildren(...visibles.map((ficha) => {
    const boton = crear("button", "fila");
    boton.type = "button";
    boton.append(foto(ficha), crear("span", "", ficha.nombre));
    boton.onclick = () => verFicha(ficha);
    const li = crear("li");
    li.append(boton);
    return li;
  }));
  if (!visibles.length) {
    $("lista").append(crear("li", "sin-resultados",
      datos.fichas.length ? "Ningún expediente coincide." : "Todavía no hay expedientes en la hoja."));
  }
}

function panel(abierto) {
  $("panel").classList.toggle("abierto", abierto);
  $("abrir-panel").setAttribute("aria-expanded", abierto);
  (abierto ? $("buscar") : $("abrir-panel")).focus();
}

// ---------- Conversación ----------
function agregarMensaje(rol, texto) {
  const ahora = new Date();
  const hora = ahora.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit", hour12: false });
  const nodo = crear("article", `mensaje ${rol}`);
  const etiqueta = crear("p", "mensaje-etiqueta");
  etiqueta.append(
    crear("strong", "", rol === "civil" ? "Pregunta del civil" : "Declaración de la unidad"),
    crear("time", "", `${hora} horas`));
  const cuerpo = crear("div", "mensaje-texto", texto);
  nodo.append(etiqueta, cuerpo);
  $("mensajes").append(nodo);
  return { nodo, cuerpo };
}

function mostrarAnexos(nodo, fichas) {
  if (!fichas.length) return;
  const caja = crear("div", "anexos");
  for (const ficha of fichas) {
    const boton = crear("button", "anexo");
    boton.type = "button";
    const pie = crear("span", "anexo-pie");
    pie.append(crear("b", "", `Anexo ${siguienteAnexo++}`), ficha.nombre);
    boton.append(foto(ficha), pie);
    boton.onclick = () => verFicha(ficha);
    caja.append(boton);
  }
  nodo.append(caja);
}

const cercaDelFinal = () =>
  innerHeight + scrollY > document.documentElement.scrollHeight - 420;

function ponerOcupado(valor) {
  ocupado = valor;
  $("enviar").disabled = valor;
  $("mensajes").setAttribute("aria-busy", valor);
}

// Escribe poco a poco, como máquina; si se atrasa, acelera.
function mecanografo(cuerpo) {
  let pendiente = "";
  let activo = true;
  const terminado = [];
  function paso() {
    if (!activo) return;
    if (pendiente) {
      const seguir = cercaDelFinal();
      const cuantos = sinMovimiento || document.hidden ? pendiente.length : Math.max(3, Math.ceil(pendiente.length / 40));
      cuerpo.textContent += pendiente.slice(0, cuantos);
      pendiente = pendiente.slice(cuantos);
      if (seguir) cuerpo.scrollIntoView({ block: "end" });
    }
    if (!pendiente) terminado.splice(0).forEach((f) => f());
    setTimeout(paso, 16);
  }
  paso();
  return {
    agregar(t) { pendiente += t; },
    reiniciar() { pendiente = ""; cuerpo.textContent = ""; },
    vaciar() { return pendiente ? new Promise((f) => terminado.push(f)) : Promise.resolve(); },
    parar() { activo = false; pendiente = ""; terminado.splice(0).forEach((f) => f()); },
  };
}

async function preguntar(texto) {
  const mia = generacion;
  ponerOcupado(true);
  $("vacio").hidden = true;
  agregarMensaje("civil", texto);
  const { nodo, cuerpo } = agregarMensaje("bala", "");
  nodo.classList.add("escribiendo");
  const nota = crear("p", "nota", "Procesando declaración…");
  cuerpo.before(nota);
  nodo.scrollIntoView({ block: "end" });
  $("estado").textContent = "Procesando declaración";

  const maquina = mecanografo(cuerpo);
  control = new AbortController();
  let completa = false;
  try {
    const respuesta = await pedir("/api/mensaje", {
      method: "POST", signal: control.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversacion, texto }),
    });
    const lector = respuesta.body.pipeThrough(new TextDecoderStream()).getReader();
    let resto = "";
    let anexos = [];
    for (;;) {
      const { value, done } = await lector.read();
      if (done) break;
      const lineas = (resto + value).split("\n");
      resto = lineas.pop();
      for (const linea of lineas) {
        const evento = JSON.parse(linea);
        if (evento.tipo === "texto") { nota.hidden = true; maquina.agregar(evento.texto); }
        else if (evento.tipo === "reiniciar") maquina.reiniciar();
        else if (evento.tipo === "aviso") { nota.hidden = false; nota.textContent = `Nota del archivo: ${evento.texto}`; }
        else if (evento.tipo === "anexos") anexos = evento.fichas;
        else if (evento.tipo === "error") throw new Error(evento.texto);
        else if (evento.tipo === "fin") {
          await maquina.vaciar();
          if (mia !== generacion) return;
          completa = true;
          cuerpo.textContent = evento.texto || "Sin declaración.";
          const seguir = cercaDelFinal();
          mostrarAnexos(nodo, anexos);
          if (seguir && anexos.length) nodo.scrollIntoView({ block: "end" });
          $("estado").textContent = `Declaración: ${evento.texto}`;
        }
      }
    }
    if (!completa) throw new Error("La respuesta se interrumpió. Intente de nuevo.");
  } catch (e) {
    if (mia !== generacion) return;
    maquina.reiniciar();
    nodo.append(crear("p", "error", e.message));
    $("estado").textContent = e.message;
    if (!$("pregunta").value) $("pregunta").value = texto; // para reintentar sin volver a escribir
  } finally {
    maquina.parar();
    if (mia === generacion) {
      nota.remove();
      nodo.classList.remove("escribiendo");
      ponerOcupado(false);
      $("pregunta").focus();
    }
  }
}

// ---------- Parte nuevo ----------
async function abrirParte(ruta) {
  const nuevos = await (await pedir(ruta, ruta === "/api/actualizar" ? { method: "POST" } : {})).json();
  const sesion = await (await pedir("/api/conversacion", { method: "POST" })).json();
  generacion++;
  if (control) control.abort();
  datos = nuevos;
  conversacion = sesion.id;
  siguienteAnexo = 1;
  ponerOcupado(false);
  $("mensajes").replaceChildren();
  $("vacio").hidden = false;
  $("folio").textContent = sesion.folio;
  $("declarante").textContent = $("firma").textContent = datos.nombre;
  $("fecha").textContent = new Date().toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" });
  $("buscar").value = "";
  $("ver-mapa").hidden = !datos.lugares.length;
  pintarLista();
}

async function conBoton(boton, espera, accion) {
  const original = boton.textContent;
  boton.disabled = true;
  boton.textContent = espera;
  boton.parentNode.querySelector(":scope > .error")?.remove();
  try {
    await accion();
  } catch (e) {
    const aviso = crear("p", "error", e.message);
    aviso.setAttribute("role", "alert");
    boton.parentNode.append(aviso);
  } finally {
    boton.disabled = false;
    boton.textContent = original;
  }
}

$("comenzar").onclick = (e) => conBoton(e.currentTarget, "Consultando el archivo…", async () => {
  await abrirParte("/api/parte");
  $("portada").hidden = true;
  $("parte").hidden = false;
  scrollTo(0, 0);
  $("pregunta").focus({ preventScroll: true });
});
$("nueva").onclick = (e) => conBoton(e.currentTarget, "Archivando…", async () => {
  await abrirParte("/api/parte");
  scrollTo(0, 0);
});
$("actualizar").onclick = (e) => conBoton(e.currentTarget, "Consultando expedientes…", async () => {
  await abrirParte("/api/actualizar");
  scrollTo(0, 0);
});
$("ver-mapa").onclick = verMapa;
$("buscar").oninput = pintarLista;
$("abrir-panel").onclick = () => panel(true);
$("cerrar-panel").onclick = () => panel(false);
$("cerrar-visor").onclick = () => $("visor").close();
$("visor").onclick = (e) => { if (e.target === $("visor")) $("visor").close(); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("visor").open && $("panel").classList.contains("abierto")) panel(false);
});

const caja = $("pregunta");
function ajustar() { caja.style.height = "auto"; caja.style.height = `${caja.scrollHeight + 4}px`; }
caja.oninput = ajustar;
caja.onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("forma").requestSubmit(); }
};
$("forma").onsubmit = (e) => {
  e.preventDefault();
  const texto = caja.value.trim();
  if (!texto || ocupado || !conversacion) return;
  caja.value = "";
  ajustar();
  preguntar(texto);
};
