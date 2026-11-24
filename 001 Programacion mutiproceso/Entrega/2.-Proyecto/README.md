# Prisma · procesado de imagen en paralelo

## Requisitos

- Python 3
- Un navegador moderno (Chrome, Firefox o Edge)

## Puesta en marcha

1. Abre una terminal en esta carpeta.
2. Arranca el servidor:

   ```bash
   python3 servidor.py
   ```

   Para usar otro puerto: `python3 servidor.py 8080`.

3. Abre <http://localhost:8000> en el navegador.
4. Elige un filtro y el número de workers, y pulsa **Procesar**.

Para parar el servidor, pulsa `Ctrl+C` en la terminal.

> No abras `index.html` con doble clic: los Web Workers no funcionan desde `file://`, por eso hace falta el servidor.

Las mediciones de cada ejecución se guardan en `resultados.csv`, que se crea solo la primera vez.
