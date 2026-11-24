"use strict"

// trabajador.js  (ESCLAVO)
// Cada instancia se ejecuta en su propio hilo del navegador.
// No tiene acceso al DOM ni al canvas: solo recibe datos por
// mensajes, calcula y devuelve el resultado por mensajes.

importScripts("filtros.js")

let miId = null


onmessage = function(evento){

  const datos = evento.data

  // Primer mensaje: el maestro me dice quién soy
  if(datos.tipo == "inicio"){
    miId = datos.id
    return
  }

  if(datos.tipo != "tesela") return

  try{

    const inicio = performance.now()

    const pixeles = aplicarFiltro(
      datos.filtro,
      datos.pixeles,
      datos.ancho,
      datos.alto,
      datos.margen,
      datos.intensidad
    )

    const ms = performance.now() - inicio

    // Devuelvo el resultado. El segundo parámetro TRANSFIERE
    // el buffer en lugar de copiarlo (cero copias).
    postMessage({
      tipo: "tesela",
      trabajo: datos.trabajo,
      worker: miId,
      x: datos.x,
      y: datos.y,
      ancho: datos.ancho,
      alto: datos.alto,
      pixeles: pixeles,
      ms: ms
    }, [pixeles.buffer])

  }catch(error){

    postMessage({
      tipo: "error",
      trabajo: datos.trabajo,
      worker: miId,
      mensaje: error.message
    })

  }
}
