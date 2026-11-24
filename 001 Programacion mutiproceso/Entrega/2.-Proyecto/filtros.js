"use strict"

// filtros.js
// Algoritmos de procesado de imagen.
// Este archivo se carga en DOS sitios:
//   - en el hilo principal  -> <script src="filtros.js">
//   - en cada Web Worker     -> importScripts("filtros.js")
// Así el modo secuencial y el modo paralelo ejecutan
// exactamente el mismo código y la comparación es justa.


// Lista de filtros que se muestran en el desplegable
const NOMBRES_FILTROS = {
  gaussiano:  "Desenfoque gaussiano (pesado)",
  bordes:     "Detección de bordes (Sobel)",
  enfoque:    "Enfoque",
  grises:     "Escala de grises",
  sepia:      "Sepia",
  negativo:   "Negativo",
  brillo:     "Brillo",
  contraste:  "Contraste",
  posterizar: "Posterizar",
  pixelar:    "Pixelar"
}


function limitar(valor, minimo, maximo){
  return valor < minimo ? minimo : valor > maximo ? maximo : valor
}

function radioGauss(intensidad){
  return Math.max(1, Math.round(intensidad / 100 * 20))
}


// MARGEN (HALO)
// Los filtros de convolución necesitan los píxeles vecinos.
// Si una tesela se procesa sin conocer a sus vecinas, aparece
// una "costura" visible en el borde. Por eso el maestro envía
// cada tesela con un margen extra de píxeles alrededor.

function margenFiltro(filtro, intensidad){
  if(filtro == "gaussiano") return radioGauss(intensidad)
  if(filtro == "bordes" || filtro == "enfoque") return 1
  return 0
}


// PUNTO DE ENTRADA
// entrada : tesela con margen -> (ancho+2m) x (alto+2m) RGBA
// devuelve: tesela limpia     ->  ancho x alto RGBA

function aplicarFiltro(filtro, entrada, ancho, alto, margen, intensidad){

  const salida = new Uint8ClampedArray(ancho * alto * 4)
  const f = intensidad / 100

  switch(filtro){
    case "negativo":   negativo(entrada, salida, ancho, alto, margen, f); break
    case "grises":     grises(entrada, salida, ancho, alto, margen, f); break
    case "sepia":      sepia(entrada, salida, ancho, alto, margen, f); break
    case "brillo":     brillo(entrada, salida, ancho, alto, margen, f); break
    case "contraste":  contraste(entrada, salida, ancho, alto, margen, f); break
    case "posterizar": posterizar(entrada, salida, ancho, alto, margen, f); break
    case "pixelar":    pixelar(entrada, salida, ancho, alto, margen, f); break
    case "gaussiano":  gaussiano(entrada, salida, ancho, alto, margen, intensidad); break
    case "bordes":     bordes(entrada, salida, ancho, alto, margen, f); break
    case "enfoque":    enfoque(entrada, salida, ancho, alto, margen, f); break
    default:
      throw new Error("Filtro desconocido: " + filtro)
  }

  return salida
}


// Recorre los píxeles útiles (sin margen) y llama a fn con la
// posición en la entrada (e) y en la salida (s).
function porPixel(entrada, salida, ancho, alto, margen, fn){

  const anchoEntrada = ancho + 2 * margen

  for(let y = 0; y < alto; y++){

    let e = ((y + margen) * anchoEntrada + margen) * 4
    let s = y * ancho * 4

    for(let x = 0; x < ancho; x++, e += 4, s += 4){
      fn(e, s)
    }
  }
}

// Mezcla el valor original con el filtrado según la intensidad
function mezcla(original, filtrado, f){
  return original + (filtrado - original) * f
}


// FILTROS PÍXEL A PÍXEL (no necesitan vecinos)

function negativo(entrada, salida, ancho, alto, margen, f){
  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    for(let c = 0; c < 3; c++){
      salida[s+c] = mezcla(entrada[e+c], 255 - entrada[e+c], f)
    }
    salida[s+3] = entrada[e+3]
  })
}

function grises(entrada, salida, ancho, alto, margen, f){
  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    const gris = entrada[e]*0.299 + entrada[e+1]*0.587 + entrada[e+2]*0.114
    for(let c = 0; c < 3; c++){
      salida[s+c] = mezcla(entrada[e+c], gris, f)
    }
    salida[s+3] = entrada[e+3]
  })
}

function sepia(entrada, salida, ancho, alto, margen, f){
  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    const r = entrada[e], g = entrada[e+1], b = entrada[e+2]
    salida[s]   = mezcla(r, r*0.393 + g*0.769 + b*0.189, f)
    salida[s+1] = mezcla(g, r*0.349 + g*0.686 + b*0.168, f)
    salida[s+2] = mezcla(b, r*0.272 + g*0.534 + b*0.131, f)
    salida[s+3] = entrada[e+3]
  })
}

function brillo(entrada, salida, ancho, alto, margen, f){
  const cantidad = f * 120
  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    salida[s]   = entrada[e]   + cantidad
    salida[s+1] = entrada[e+1] + cantidad
    salida[s+2] = entrada[e+2] + cantidad
    salida[s+3] = entrada[e+3]
  })
}

function contraste(entrada, salida, ancho, alto, margen, f){
  const valor = f * 200
  const factor = (259 * (valor + 255)) / (255 * (259 - valor))
  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    salida[s]   = factor * (entrada[e]   - 128) + 128
    salida[s+1] = factor * (entrada[e+1] - 128) + 128
    salida[s+2] = factor * (entrada[e+2] - 128) + 128
    salida[s+3] = entrada[e+3]
  })
}

function posterizar(entrada, salida, ancho, alto, margen, f){
  const niveles = 2 + Math.round((1 - f) * 6)
  const salto = 255 / (niveles - 1)
  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    salida[s]   = Math.round(entrada[e]   / salto) * salto
    salida[s+1] = Math.round(entrada[e+1] / salto) * salto
    salida[s+2] = Math.round(entrada[e+2] / salto) * salto
    salida[s+3] = entrada[e+3]
  })
}

// Los bloques (2..32 px) siempre caben un número entero de veces
// en las teselas (64..512 px), así que no hay cortes entre teselas.
function pixelar(entrada, salida, ancho, alto, margen, f){

  const bloque = 2 ** (1 + Math.round(f * 4))
  const anchoEntrada = ancho + 2 * margen

  for(let by = 0; by < alto; by += bloque){
    for(let bx = 0; bx < ancho; bx += bloque){

      const muestra = ((by + margen) * anchoEntrada + bx + margen) * 4

      for(let y = by; y < Math.min(by + bloque, alto); y++){
        for(let x = bx; x < Math.min(bx + bloque, ancho); x++){
          const s = (y * ancho + x) * 4
          salida[s]   = entrada[muestra]
          salida[s+1] = entrada[muestra+1]
          salida[s+2] = entrada[muestra+2]
          salida[s+3] = entrada[muestra+3]
        }
      }
    }
  }
}


// FILTROS DE CONVOLUCIÓN (necesitan el margen)

// Desenfoque gaussiano 2D. Es deliberadamente costoso
// (hasta 41x41 = 1681 vecinos por píxel) para que se note
// la diferencia entre 1 y N procesos.
function gaussiano(entrada, salida, ancho, alto, margen, intensidad){

  const radio = radioGauss(intensidad)
  const lado = 2 * radio + 1
  const sigma = radio / 2
  const anchoEntrada = ancho + 2 * margen

  // Precalculo los pesos del núcleo una sola vez
  const pesos = new Float32Array(lado * lado)
  let suma = 0
  for(let dy = -radio; dy <= radio; dy++){
    for(let dx = -radio; dx <= radio; dx++){
      const peso = Math.exp(-(dx*dx + dy*dy) / (2 * sigma * sigma))
      pesos[(dy + radio) * lado + (dx + radio)] = peso
      suma += peso
    }
  }
  for(let i = 0; i < pesos.length; i++) pesos[i] /= suma

  for(let y = 0; y < alto; y++){
    for(let x = 0; x < ancho; x++){

      let r = 0, g = 0, b = 0, k = 0

      // La ventana empieza en (x, y) de la entrada porque margen == radio
      for(let ky = 0; ky < lado; ky++){
        let e = ((y + ky) * anchoEntrada + x) * 4
        for(let kx = 0; kx < lado; kx++, e += 4, k++){
          const peso = pesos[k]
          r += entrada[e]   * peso
          g += entrada[e+1] * peso
          b += entrada[e+2] * peso
        }
      }

      const s = (y * ancho + x) * 4
      salida[s]   = r
      salida[s+1] = g
      salida[s+2] = b
      salida[s+3] = entrada[((y + margen) * anchoEntrada + x + margen) * 4 + 3]
    }
  }
}

// Operador de Sobel sobre la luminancia
function bordes(entrada, salida, ancho, alto, margen, f){

  const anchoEntrada = ancho + 2 * margen
  const gx = [-1, 0, 1, -2, 0, 2, -1, 0, 1]
  const gy = [-1, -2, -1, 0, 0, 0, 1, 2, 1]
  const ganancia = 0.5 + f * 1.5

  for(let y = 0; y < alto; y++){
    for(let x = 0; x < ancho; x++){

      let sumaX = 0, sumaY = 0, k = 0

      for(let dy = 0; dy < 3; dy++){
        for(let dx = 0; dx < 3; dx++, k++){
          const e = ((y + dy) * anchoEntrada + x + dx) * 4
          const gris = entrada[e]*0.299 + entrada[e+1]*0.587 + entrada[e+2]*0.114
          sumaX += gris * gx[k]
          sumaY += gris * gy[k]
        }
      }

      const intensidad = Math.sqrt(sumaX*sumaX + sumaY*sumaY) * ganancia
      const s = (y * ancho + x) * 4
      salida[s] = salida[s+1] = salida[s+2] = intensidad
      salida[s+3] = 255
    }
  }
}

// Máscara de enfoque: centro reforzado menos los 4 vecinos
function enfoque(entrada, salida, ancho, alto, margen, f){

  const anchoEntrada = ancho + 2 * margen
  const k = f * 2
  const fila = anchoEntrada * 4

  porPixel(entrada, salida, ancho, alto, margen, function(e, s){
    for(let c = 0; c < 3; c++){
      const centro = entrada[e+c]
      const vecinos = entrada[e+c-4] + entrada[e+c+4] + entrada[e+c-fila] + entrada[e+c+fila]
      salida[s+c] = centro * (1 + 4*k) - k * vecinos
    }
    salida[s+3] = entrada[e+3]
  })
}
