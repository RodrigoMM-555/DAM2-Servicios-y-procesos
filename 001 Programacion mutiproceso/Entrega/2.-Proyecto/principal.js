"use strict"

// principal.js  (MAESTRO)
// - Carga la imagen y la trocea en teselas (buckets).
// - Crea un pool de Web Workers y les va repartiendo teselas
//   desde una cola: cuando uno termina, recibe la siguiente
//   (planificación dinámica).
// - Recoge los resultados, los pinta y mide los tiempos.
// - Puede ejecutar lo mismo en el hilo principal para comparar.

const $ = (selector) => document.querySelector(selector)

const lienzo = $("#lienzo")
const contexto = lienzo.getContext("2d", { willReadFrequently: true })
const capa = $("#superposicion")
const contextoCapa = capa.getContext("2d")

const NUCLEOS = navigator.hardwareConcurrency || 4
const LADO_MAXIMO = 2048

let original = null        // ImageData de la imagen cargada (nunca se modifica)
let pool = []              // Workers vivos
let infoWorkers = []       // Estado y estadísticas de cada worker
let contadorTrabajos = 0   // Identificador de cada ejecución
let ocupado = false
let cancelarTrabajo = null // Función para abortar la ejecución en curso
const historial = []


// INTERFAZ: valores iniciales

$("#nucleos").textContent = NUCLEOS + " núcleos lógicos detectados"

const selectorFiltro = $("#filtro")
for(const clave in NOMBRES_FILTROS){
  selectorFiltro.add(new Option(NOMBRES_FILTROS[clave], clave))
}

$("#nWorkers").max = NUCLEOS * 2
$("#nWorkers").value = NUCLEOS
$("#vWorkers").textContent = NUCLEOS

$("#nWorkers").oninput = function(){
  $("#vWorkers").textContent = this.value
  if(!ocupado) asegurarPool(Number(this.value))
}
$("#intensidad").oninput = function(){
  $("#vIntensidad").textContent = this.value
}
$("#modo").onchange = function(){
  $("#filaWorkers").classList.toggle("apagado", this.value == "principal")
}
$("#verTeselas").onchange = function(){
  capa.style.visibility = this.checked ? "visible" : "hidden"
}


// CARGA DE IMAGEN

function cargarImagen(url){

  const imagen = new Image()

  imagen.onload = function(){

    // Reduzco imágenes enormes para no agotar la memoria
    const escala = Math.min(1, LADO_MAXIMO / Math.max(imagen.width, imagen.height))
    const ancho = Math.round(imagen.width * escala)
    const alto = Math.round(imagen.height * escala)

    lienzo.width = capa.width = ancho
    lienzo.height = capa.height = alto

    contexto.drawImage(imagen, 0, 0, ancho, alto)
    original = contexto.getImageData(0, 0, ancho, alto)

    $("#dimensiones").textContent = ancho + " × " + alto + " px · " +
      (ancho * alto / 1e6).toFixed(2) + " Mpx"
    limpiarCapa()
  }

  imagen.onerror = function(){
    mostrarEstado("No se ha podido cargar la imagen", true)
  }

  imagen.src = url
}

$("#archivo").onchange = function(){
  if(this.files.length) cargarImagen(URL.createObjectURL(this.files[0]))
}

$("#restaurar").onclick = function(){
  if(!original || ocupado) return
  contexto.putImageData(original, 0, 0)
  limpiarCapa()
}

$("#descargar").onclick = function(){
  lienzo.toBlob(function(blob){
    const enlace = document.createElement("a")
    enlace.href = URL.createObjectURL(blob)
    enlace.download = "prisma.png"
    enlace.click()
  })
}


// POOL DE WORKERS

function colorWorker(i, total){
  return "hsl(" + Math.round(i * 360 / total) + " 85% 58%)"
}

function asegurarPool(n){

  if(pool.length == n) return

  destruirPool()

  for(let i = 0; i < n; i++){
    const trabajador = new Worker("trabajador.js")
    trabajador.postMessage({ tipo: "inicio", id: i })
    pool.push(trabajador)
    infoWorkers.push({ id: i, estado: "libre", teselas: 0, ms: 0, color: colorWorker(i, n) })
  }

  pintarWorkers()
}

function destruirPool(){
  // terminate() mata el hilo inmediatamente, esté haciendo lo que esté haciendo
  for(const trabajador of pool) trabajador.terminate()
  pool = []
  infoWorkers = []
}

function pintarWorkers(){

  $("#listaWorkers").innerHTML = infoWorkers.map(function(w){
    return '<li class="' + w.estado + '">' +
      '<span class="muestra" style="background:' + w.color + '"></span>' +
      '<b>Worker ' + w.id + '</b>' +
      '<span class="estado">' + w.estado + '</span>' +
      '<small>' + w.teselas + ' teselas · ' + Math.round(w.ms) + ' ms de cálculo</small>' +
      '</li>'
  }).join("")
}

function marcarEstado(i, estado){
  if(infoWorkers[i]) infoWorkers[i].estado = estado
}


// TESELAS Y MARGEN

// Divide la imagen en una cola de teselas (buckets)
function generarTeselas(ancho, alto, tamano){

  const cola = []

  for(let y = 0; y < alto; y += tamano){
    for(let x = 0; x < ancho; x += tamano){
      cola.push({
        x: x,
        y: y,
        ancho: Math.min(tamano, ancho - x),
        alto: Math.min(tamano, alto - y)
      })
    }
  }

  return cola
}

// Crea una copia de la imagen con un borde de "margen" píxeles
// que repite los píxeles del borde. Así todas las teselas,
// también las de las esquinas, tienen vecinos que leer.
function crearRelleno(fuente, margen){

  const ancho = fuente.width
  const alto = fuente.height
  const origen = fuente.data

  if(margen == 0) return { datos: origen, ancho: ancho }

  const anchoR = ancho + 2 * margen
  const altoR = alto + 2 * margen
  const datos = new Uint8ClampedArray(anchoR * altoR * 4)

  for(let py = 0; py < altoR; py++){

    const fy = limitar(py - margen, 0, alto - 1)
    const filaOrigen = fy * ancho * 4
    const filaDestino = py * anchoR * 4

    datos.set(origen.subarray(filaOrigen, filaOrigen + ancho * 4), filaDestino + margen * 4)

    for(let i = 0; i < margen; i++){
      // Izquierda: copio el primer píxel real
      datos.copyWithin(filaDestino + i * 4, filaDestino + margen * 4, filaDestino + margen * 4 + 4)
      // Derecha: copio el último píxel real
      datos.copyWithin(
        filaDestino + (margen + ancho + i) * 4,
        filaDestino + (margen + ancho - 1) * 4,
        filaDestino + (margen + ancho) * 4
      )
    }
  }

  return { datos: datos, ancho: anchoR }
}

// Recorta una tesela (con su margen) del buffer con relleno
function extraerTesela(relleno, tesela, margen){

  const anchoT = tesela.ancho + 2 * margen
  const altoT = tesela.alto + 2 * margen
  const salida = new Uint8ClampedArray(anchoT * altoT * 4)

  for(let fila = 0; fila < altoT; fila++){
    const inicio = ((tesela.y + fila) * relleno.ancho + tesela.x) * 4
    salida.set(relleno.datos.subarray(inicio, inicio + anchoT * 4), fila * anchoT * 4)
  }

  return salida
}


// MODO 1: PARALELO CON WEB WORKERS

function procesarConWorkers(fuente, opciones){

  return new Promise(function(resolver, rechazar){

    asegurarPool(opciones.workers)

    const trabajo = ++contadorTrabajos
    const margen = margenFiltro(opciones.filtro, opciones.intensidad)
    const inicio = performance.now()
    const relleno = crearRelleno(fuente, margen)
    const cola = generarTeselas(fuente.width, fuente.height, opciones.tesela)
    const total = cola.length
    let completadas = 0

    for(const w of infoWorkers){ w.teselas = 0; w.ms = 0; w.estado = "libre" }

    // Asigna la siguiente tesela de la cola al worker i
    function enviarSiguiente(i){

      if(cola.length == 0){
        marcarEstado(i, "terminado")
        pintarWorkers()
        return
      }

      const tesela = cola.shift()
      const pixeles = extraerTesela(relleno, tesela, margen)

      marcarEstado(i, "ocupado")
      dibujarAsignacion(tesela, infoWorkers[i].color)

      // Transfiero el buffer: el maestro deja de tenerlo y el worker
      // lo recibe sin copiarlo.
      pool[i].postMessage({
        tipo: "tesela",
        trabajo: trabajo,
        x: tesela.x,
        y: tesela.y,
        ancho: tesela.ancho,
        alto: tesela.alto,
        margen: margen,
        filtro: opciones.filtro,
        intensidad: opciones.intensidad,
        pixeles: pixeles
      }, [pixeles.buffer])
    }

    pool.forEach(function(trabajador, i){

      trabajador.onmessage = function(evento){

        const r = evento.data

        // Ignoro mensajes de una ejecución anterior
        if(r.trabajo != trabajo) return

        if(r.tipo == "error"){
          abortar()
          rechazar(new Error("Worker " + r.worker + ": " + r.mensaje))
          return
        }

        contexto.putImageData(new ImageData(r.pixeles, r.ancho, r.alto), r.x, r.y)

        infoWorkers[i].teselas++
        infoWorkers[i].ms += r.ms
        dibujarCompletada(r, infoWorkers[i].color, String(i))

        // SINCRONIZACIÓN: solo cuando han vuelto TODAS las teselas
        // doy el trabajo por terminado (barrera).
        completadas++
        actualizarProgreso(completadas, total)

        if(completadas == total){
          for(const w of infoWorkers) w.estado = "libre"
          pintarWorkers()
          resolver({ ms: performance.now() - inicio, teselas: total })
        }else{
          enviarSiguiente(i)
          pintarWorkers()
        }
      }

      trabajador.onerror = function(evento){
        evento.preventDefault()
        abortar()
        rechazar(new Error("Worker " + i + ": " + evento.message))
      }
    })

    function abortar(){
      const n = pool.length
      destruirPool()
      asegurarPool(n)
    }

    cancelarTrabajo = function(){
      abortar()
      rechazar(new Error("cancelado"))
    }

    // Arranque: una tesela para cada worker
    for(let i = 0; i < pool.length; i++) enviarSiguiente(i)
    pintarWorkers()
  })
}


// MODO 2: SECUENCIAL EN EL HILO PRINCIPAL
// Mismo algoritmo, pero sin workers. Mientras dura, la página
// se queda congelada (mira los bichitos del monitor).

function procesarEnPrincipal(fuente, opciones){

  const margen = margenFiltro(opciones.filtro, opciones.intensidad)
  const inicio = performance.now()
  const relleno = crearRelleno(fuente, margen)
  const cola = generarTeselas(fuente.width, fuente.height, opciones.tesela)

  for(const tesela of cola){
    const entrada = extraerTesela(relleno, tesela, margen)
    const salida = aplicarFiltro(opciones.filtro, entrada, tesela.ancho, tesela.alto, margen, opciones.intensidad)
    contexto.putImageData(new ImageData(salida, tesela.ancho, tesela.alto), tesela.x, tesela.y)
    dibujarCompletada(tesela, "hsl(0 0% 80%)", "P")
  }

  return { ms: performance.now() - inicio, teselas: cola.length }
}

// Deja que el navegador pinte antes de bloquear el hilo
function esperarPintado(){
  return new Promise(function(resolver){
    requestAnimationFrame(function(){ setTimeout(resolver, 0) })
  })
}


// EJECUCIÓN

function leerOpciones(){
  return {
    filtro: $("#filtro").value,
    intensidad: Number($("#intensidad").value),
    modo: $("#modo").value,
    workers: Number($("#nWorkers").value),
    tesela: Number($("#tamTesela").value)
  }
}

async function ejecutar(opciones, fuente){

  limpiarCapa()
  actualizarProgreso(0, 1)

  let resultado

  if(opciones.modo == "principal"){
    mostrarEstado("Bloqueando el hilo principal…")
    await esperarPintado()
    resultado = procesarEnPrincipal(fuente, opciones)
    actualizarProgreso(1, 1)
  }else{
    resultado = await procesarConWorkers(fuente, opciones)
  }

  const fila = registrar(opciones, resultado)
  mostrarEstado(
    NOMBRES_FILTROS[opciones.filtro] + " · " +
    (opciones.modo == "principal" ? "hilo principal" : opciones.workers + " workers") +
    " · " + resultado.teselas + " teselas · " + Math.round(resultado.ms) + " ms"
  )
  return fila
}

function bloquearControles(si){
  ocupado = si
  document.querySelectorAll("#controles button, #controles select, #controles input")
    .forEach(function(control){ control.disabled = si })
  $("#cancelar").disabled = !si
}

$("#procesar").onclick = async function(){

  if(!original || ocupado) return

  const opciones = leerOpciones()
  const fuente = $("#acumular").checked
    ? contexto.getImageData(0, 0, lienzo.width, lienzo.height)
    : original

  bloquearControles(true)

  try{
    await ejecutar(opciones, fuente)
  }catch(error){
    mostrarEstado(error.message == "cancelado" ? "Cancelado" : error.message, error.message != "cancelado")
  }

  bloquearControles(false)
}

$("#cancelar").onclick = function(){
  if(cancelarTrabajo) cancelarTrabajo()
}


// HISTORIAL DE EJECUCIONES Y SPEEDUP

function registrar(opciones, resultado){

  // La referencia es la última ejecución secuencial comparable:
  // hilo principal o 1 worker, mismo filtro, intensidad y tesela.
  const referencia = historial.slice().reverse().find(function(h){
    return h.filtro == opciones.filtro &&
      h.intensidad == opciones.intensidad &&
      h.tesela == opciones.tesela &&
      (h.modo == "principal" || h.workers == 1)
  })

  const workers = opciones.modo == "principal" ? 1 : opciones.workers
  const esReferencia = opciones.modo == "principal" || workers == 1
  const msReferencia = esReferencia ? resultado.ms : referencia ? referencia.ms : null
  const speedup = msReferencia ? msReferencia / resultado.ms : null

  const fila = {
    numero: historial.length + 1,
    fecha: new Date().toISOString(),
    filtro: opciones.filtro,
    intensidad: opciones.intensidad,
    modo: opciones.modo,
    workers: workers,
    tesela: opciones.tesela,
    teselas: resultado.teselas,
    ancho: lienzo.width,
    alto: lienzo.height,
    ms: Math.round(resultado.ms),
    speedup: speedup ? Number(speedup.toFixed(2)) : "",
    eficiencia: speedup ? Number((speedup / workers).toFixed(2)) : "",
    nucleos: NUCLEOS
  }

  historial.push(fila)
  pintarTabla()
  enviarAlServidor(fila)
  return fila
}

function pintarTabla(){

  $("#tablaResultados tbody").innerHTML = historial.slice().reverse().map(function(h){
    return "<tr>" +
      "<td>" + h.numero + "</td>" +
      "<td>" + NOMBRES_FILTROS[h.filtro] + " (" + h.intensidad + ")</td>" +
      "<td>" + (h.modo == "principal" ? "Hilo principal" : "Workers") + "</td>" +
      "<td>" + h.workers + "</td>" +
      "<td>" + h.tesela + " px · " + h.teselas + "</td>" +
      "<td class='num'>" + h.ms + "</td>" +
      "<td class='num'>" + (h.speedup ? h.speedup.toFixed(2) + "×" : "—") + "</td>" +
      "<td class='num'>" + (h.eficiencia ? Math.round(h.eficiencia * 100) + " %" : "—") + "</td>" +
      "</tr>"
  }).join("")
}


// CAPA DE VISUALIZACIÓN: qué worker procesa cada tesela

function limpiarCapa(){
  contextoCapa.clearRect(0, 0, capa.width, capa.height)
}

function dibujarAsignacion(t, color){
  contextoCapa.strokeStyle = color
  contextoCapa.lineWidth = Math.max(3, capa.width / 250)
  contextoCapa.strokeRect(t.x + 2, t.y + 2, t.ancho - 4, t.alto - 4)
}

function dibujarCompletada(t, color, etiqueta){
  contextoCapa.clearRect(t.x, t.y, t.ancho, t.alto)
  contextoCapa.globalAlpha = 0.22
  contextoCapa.fillStyle = color
  contextoCapa.fillRect(t.x, t.y, t.ancho, t.alto)
  contextoCapa.globalAlpha = 0.9
  contextoCapa.font = "bold " + Math.max(12, Math.min(t.ancho, t.alto) / 4) + "px system-ui, sans-serif"
  contextoCapa.textAlign = "center"
  contextoCapa.textBaseline = "middle"
  contextoCapa.fillText(etiqueta, t.x + t.ancho / 2, t.y + t.alto / 2)
  contextoCapa.globalAlpha = 1
}


// PROGRESO Y MENSAJES

function actualizarProgreso(hechas, total){
  $("#barra").style.width = (100 * hechas / total) + "%"
}

function mostrarEstado(texto, esError){
  $("#textoProgreso").textContent = texto
  $("#progreso").classList.toggle("error", !!esError)
}


// MONITOR DEL HILO PRINCIPAL (bichitos de 004)
// Se mueven con requestAnimationFrame en el hilo principal.
// Si el hilo se bloquea, los bichitos se congelan.

const latido = $("#latido")
const contextoLatido = latido.getContext("2d")
const bichitos = []

for(let i = 0; i < 16; i++){
  bichitos.push({
    x: Math.random() * latido.width,
    y: Math.random() * latido.height,
    angulo: Math.random() * Math.PI * 2,
    velocidad: 1 + Math.random() * 2,
    radio: 3 + Math.random() * 4,
    color: "hsl(" + Math.round(Math.random() * 360) + " 80% 62%)"
  })
}

let ultimoFrame = performance.now()
let framesSegundo = 0
let inicioSegundo = performance.now()

function animarLatido(ahora){

  const pausa = ahora - ultimoFrame
  ultimoFrame = ahora

  if(pausa > 250 && ocupado){
    $("#bloqueo").textContent = "Último bloqueo: " + Math.round(pausa) + " ms sin responder"
  }

  framesSegundo++
  if(ahora - inicioSegundo >= 1000){
    $("#fps").textContent = framesSegundo + " fps"
    framesSegundo = 0
    inicioSegundo = ahora
  }

  contextoLatido.clearRect(0, 0, latido.width, latido.height)

  for(const b of bichitos){
    b.x += Math.cos(b.angulo) * b.velocidad
    b.y += Math.sin(b.angulo) * b.velocidad

    if(b.x < b.radio || b.x > latido.width - b.radio){
      b.angulo = Math.PI - b.angulo
      b.x = limitar(b.x, b.radio, latido.width - b.radio)
    }
    if(b.y < b.radio || b.y > latido.height - b.radio){
      b.angulo = -b.angulo
      b.y = limitar(b.y, b.radio, latido.height - b.radio)
    }

    contextoLatido.fillStyle = b.color
    contextoLatido.beginPath()
    contextoLatido.arc(b.x, b.y, b.radio, 0, Math.PI * 2)
    contextoLatido.fill()
  }

  requestAnimationFrame(animarLatido)
}

requestAnimationFrame(animarLatido)


// COMUNICACIÓN CON EL SERVIDOR (servidor.py)

let hayServidor = false

function enviarAlServidor(fila){

  if(!hayServidor) return

  fetch("/api/resultados", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fila)
  }).then(function(respuesta){
    if(respuesta.ok) $("#servidor").textContent = "Ejecución " + fila.numero + " guardada en resultados.csv"
  }).catch(function(){
    $("#servidor").textContent = "No se pudo guardar en el servidor"
  })
}

function comprobarServidor(){

  if(location.protocol == "file:"){
    mostrarEstado("Abre la página con servidor.py (http://localhost:8000): los workers no funcionan desde file://", true)
    $("#servidor").textContent = "Sin servidor"
    return
  }

  fetch("/api/resultados").then(function(respuesta){
    if(!respuesta.ok) throw new Error()
    return respuesta.json()
  }).then(function(filas){
    hayServidor = true
    $("#servidor").textContent = "Conectado a servidor.py · " + filas.length + " ejecuciones guardadas"
  }).catch(function(){
    $("#servidor").textContent = "Servidor sin API de resultados: las ejecuciones no se guardan"
  })
}


// ARRANQUE

comprobarServidor()
if(location.protocol != "file:") asegurarPool(NUCLEOS)
cargarImagen("img.jpg")
