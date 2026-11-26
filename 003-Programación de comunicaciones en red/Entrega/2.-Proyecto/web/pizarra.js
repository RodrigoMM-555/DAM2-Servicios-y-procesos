"use strict"

// pizarra.js  (CLIENTE WEB)
// - Abre un WebSocket con el servidor y mantiene la conexión abierta:
//   comunicación continua y en los dos sentidos.
// - Cada segmento que dibujas se pinta en local y se envía al servidor,
//   que lo reenvía al resto de navegadores.
// - También envía la posición del ratón (cursores en directo), mensajes
//   de chat y pings para medir la latencia.
// - Si se cae la conexión, reintenta con espera creciente.

const $ = (selector) => document.querySelector(selector)

const lienzo = $("#lienzo")
const ctx = lienzo.getContext("2d")
const ANCHO = lienzo.width     // resolución lógica fija: 1600 x 1000
const ALTO = lienzo.height
const FONDO = "#ffffff"
const PALETA = ["#1f2937", "#e11d48", "#f59e0b", "#16a34a", "#2563eb", "#9333ea", "#0891b2"]

let ws = null
let miNombre = null
let usuarios = []
let reintentos = 0
let enviados = 0
let recibidos = 0

const pincel = { color: PALETA[0], grosor: 4, goma: false }


// ------------------------------------------------------------ utilidades

function colorDe(nombre){
  // mismo nombre -> mismo color en todos los navegadores
  let h = 0
  for(const c of nombre) h = (h * 31 + c.codePointAt(0)) >>> 0
  return `hsl(${h % 360} 70% 55%)`
}

function enviar(mensaje){
  if(!ws || ws.readyState !== WebSocket.OPEN) return false
  ws.send(JSON.stringify(mensaje))
  enviados++
  return true
}

function actualizarContadores(){
  $("#contadores").textContent = `↑${enviados} ↓${recibidos}`
}
setInterval(actualizarContadores, 250)


// ------------------------------------------------------------ dibujo

ctx.lineCap = "round"
ctx.lineJoin = "round"

function limpiarLienzo(){
  ctx.fillStyle = FONDO
  ctx.fillRect(0, 0, ANCHO, ALTO)
}

function dibujarTrazo(t){
  ctx.strokeStyle = t.color
  ctx.lineWidth = t.grosor
  ctx.beginPath()
  ctx.moveTo(t.x0 * ANCHO, t.y0 * ALTO)
  ctx.lineTo(t.x1 * ANCHO, t.y1 * ALTO)
  ctx.stroke()
}

// Ajusta el tamaño en pantalla del canvas al hueco disponible (16:10).
// La resolución interna no cambia, así que el dibujo no se pierde.
function ajustarTamano(){
  const zona = $("#zona")
  const escala = Math.min(zona.clientWidth / ANCHO, zona.clientHeight / ALTO)
  lienzo.style.width = Math.floor(ANCHO * escala) + "px"
  lienzo.style.height = Math.floor(ALTO * escala) + "px"
}
new ResizeObserver(ajustarTamano).observe($("#zona"))

// Posición del puntero normalizada a 0..1
function posicion(evento){
  const r = lienzo.getBoundingClientRect()
  return {
    x: Math.min(1, Math.max(0, (evento.clientX - r.left) / r.width)),
    y: Math.min(1, Math.max(0, (evento.clientY - r.top) / r.height)),
  }
}

let anterior = null      // último punto mientras se arrastra
let ultimoCursor = 0

lienzo.addEventListener("pointerdown", (e) => {
  if(!ws || ws.readyState !== WebSocket.OPEN) return
  lienzo.setPointerCapture(e.pointerId)
  anterior = posicion(e)
  trazar(anterior, anterior)          // un clic deja un punto
})

lienzo.addEventListener("pointermove", (e) => {
  const p = posicion(e)

  // cursor en directo, como mucho cada 40 ms para no saturar la red
  const ahora = performance.now()
  if(ahora - ultimoCursor > 40){
    ultimoCursor = ahora
    enviar({ tipo: "cursor", x: p.x, y: p.y })
  }

  if(!anterior) return
  trazar(anterior, p)
  anterior = p
})

function soltar(){ anterior = null }
lienzo.addEventListener("pointerup", soltar)
lienzo.addEventListener("pointercancel", soltar)
lienzo.addEventListener("pointerleave", () => enviar({ tipo: "cursor", fuera: true }))

function trazar(a, b){
  const trazo = {
    tipo: "trazo",
    x0: a.x, y0: a.y, x1: b.x, y1: b.y,
    color: pincel.goma ? FONDO : pincel.color,
    grosor: pincel.goma ? pincel.grosor * 3 : pincel.grosor,
  }
  dibujarTrazo(trazo)                 // respuesta inmediata en local
  enviar(trazo)                       // y el resto lo ve a continuación
}


// ------------------------------------------------------------ herramientas

for(const color of PALETA){
  const boton = document.createElement("button")
  boton.style.background = color
  boton.title = color
  boton.onclick = () => elegirColor(color)
  $("#paleta").append(boton)
}

function elegirColor(color){
  pincel.color = color
  pincel.goma = false
  $("#goma").classList.remove("activo")
  $("#color").value = color
  for(const b of $("#paleta").children) b.classList.toggle("activo", b.title === color)
}
elegirColor(PALETA[0])

$("#color").oninput = (e) => elegirColor(e.target.value)

$("#grosor").oninput = (e) => {
  pincel.grosor = Number(e.target.value)
  $("#vGrosor").textContent = e.target.value
}

$("#goma").onclick = () => {
  pincel.goma = !pincel.goma
  $("#goma").classList.toggle("activo", pincel.goma)
}

$("#borrar").onclick = () => {
  if(confirm("¿Borrar la pizarra para TODOS los conectados?")) enviar({ tipo: "borrar" })
}

$("#descargar").onclick = () => {
  const enlace = document.createElement("a")
  enlace.download = "garabato.png"
  enlace.href = lienzo.toDataURL("image/png")
  enlace.click()
}


// ------------------------------------------------------------ nombre

const campoNombre = $("#nombre")
campoNombre.value = localStorage.getItem("garabato.nombre") || ""

campoNombre.addEventListener("change", () => {
  const nuevo = campoNombre.value.trim()
  if(!nuevo){ campoNombre.value = miNombre || ""; return }
  localStorage.setItem("garabato.nombre", nuevo)
  enviar({ tipo: "nombre", nombre: nuevo })
})
campoNombre.addEventListener("keydown", (e) => { if(e.key === "Enter") campoNombre.blur() })


// ------------------------------------------------------------ chat y usuarios

const cajaMensajes = $("#mensajes")

function anadirMensaje(m){
  const abajo = cajaMensajes.scrollHeight - cajaMensajes.scrollTop - cajaMensajes.clientHeight < 40
  const p = document.createElement("p")
  p.className = "msg"

  // Siempre textContent, nunca innerHTML: así nadie puede inyectar HTML
  if(m.tipo === "chat"){
    const meta = document.createElement("span")
    meta.className = "meta"
    meta.textContent = `${m.hora} · ${m.origen}`
    const autor = document.createElement("span")
    autor.className = "autor"
    autor.style.setProperty("--c", colorDe(m.nombre))
    autor.textContent = m.nombre + ": "
    p.append(meta, autor, document.createTextNode(m.texto))
  } else {
    p.classList.add(m.tipo)            // sistema | error
    p.textContent = (m.hora ? m.hora + " · " : "") + m.texto
  }

  cajaMensajes.append(p)
  while(cajaMensajes.children.length > 300) cajaMensajes.firstChild.remove()
  if(abajo) cajaMensajes.scrollTop = cajaMensajes.scrollHeight
}

function pintarUsuarios(){
  const lista = $("#usuarios")
  lista.replaceChildren()
  for(const u of usuarios){
    const li = document.createElement("li")
    li.style.setProperty("--c", colorDe(u.nombre))
    li.classList.toggle("yo", u.nombre === miNombre)
    li.textContent = u.nombre + (u.nombre === miNombre ? " (tú)" : "")
    const origen = document.createElement("span")
    origen.className = "origen"
    origen.textContent = u.origen
    li.append(origen)
    lista.append(li)
  }
  $("#nUsuarios").textContent = usuarios.length

  // quitar cursores de quien ya no está
  const nombres = new Set(usuarios.map(u => u.nombre))
  for(const [nombre, el] of cursores){
    if(!nombres.has(nombre)){ el.remove(); cursores.delete(nombre) }
  }
}

$("#formulario").onsubmit = (e) => {
  e.preventDefault()
  const texto = $("#texto").value.trim()
  if(texto && enviar({ tipo: "chat", texto })) $("#texto").value = ""
}


// ------------------------------------------------------------ cursores ajenos

const cursores = new Map()     // nombre -> elemento

function moverCursor(m){
  let el = cursores.get(m.nombre)
  if(!el){
    el = document.createElement("div")
    el.className = "cursor"
    el.style.setProperty("--c", colorDe(m.nombre))
    const etiqueta = document.createElement("span")
    etiqueta.textContent = m.nombre
    el.append(etiqueta)
    $("#cursores").append(el)
    cursores.set(m.nombre, el)
  }
  if(m.fuera){ el.classList.add("oculto"); return }

  // de 0..1 a píxeles dentro de #zona (el canvas puede estar centrado)
  el.style.left = (lienzo.offsetLeft + m.x * lienzo.clientWidth) + "px"
  el.style.top = (lienzo.offsetTop + m.y * lienzo.clientHeight) + "px"
  el.classList.remove("oculto")
  clearTimeout(el.temporizador)
  el.temporizador = setTimeout(() => el.classList.add("oculto"), 4000)
}


// ------------------------------------------------------------ red

function ponerEstado(clase, texto){
  const e = $("#estado")
  e.className = "estado " + clase
  e.textContent = texto
}

async function conectar(){
  ponerEstado("reconectando", reintentos ? "Reconectando…" : "Conectando…")

  // El servidor HTTP nos dice en qué puerto está el WebSocket
  let puerto = 8765
  try{
    puerto = (await (await fetch("/config.json")).json()).ws
  }catch(_){ /* abierto sin servidor HTTP: se usa el puerto por defecto */ }

  const host = location.hostname || "localhost"
  ws = new WebSocket(`ws://${host}:${puerto}`)

  ws.onopen = () => {
    reintentos = 0
    ponerEstado("conectado", "Conectado")
    // primer mensaje obligatorio: presentarse
    enviar({ tipo: "hola", nombre: campoNombre.value.trim() })
  }

  ws.onmessage = (evento) => {
    recibidos++
    manejar(JSON.parse(evento.data))
  }

  ws.onclose = () => {
    ws = null
    anterior = null
    ponerEstado("desconectado", "Sin conexión")
    // espera creciente: 1 s, 2 s, 4 s… hasta 10 s
    const espera = Math.min(10000, 1000 * 2 ** reintentos++)
    setTimeout(conectar, espera)
  }
}

function manejar(m){
  switch(m.tipo){

    case "bienvenida":
      miNombre = m.nombre
      campoNombre.value = m.nombre
      localStorage.setItem("garabato.nombre", m.nombre)
      // estado completo: se repinta todo desde cero
      limpiarLienzo()
      m.trazos.forEach(dibujarTrazo)
      cajaMensajes.replaceChildren()
      m.chat.forEach(anadirMensaje)
      usuarios = m.usuarios
      pintarUsuarios()
      break

    case "trazo":     dibujarTrazo(m); break
    case "borrar":    limpiarLienzo(); break
    case "cursor":    moverCursor(m); break
    case "chat":
    case "sistema":
    case "error":     anadirMensaje(m); break

    case "usuarios":
      usuarios = m.lista
      pintarUsuarios()
      break

    case "renombrado":
      miNombre = m.nombre
      campoNombre.value = m.nombre
      localStorage.setItem("garabato.nombre", m.nombre)
      pintarUsuarios()
      break

    case "pong":
      $("#ping").textContent = (performance.now() - m.t).toFixed(1) + " ms"
      break
  }
}

// ping cada 2 s para ver la latencia en directo
setInterval(() => enviar({ tipo: "ping", t: performance.now() }), 2000)

limpiarLienzo()
conectar()
