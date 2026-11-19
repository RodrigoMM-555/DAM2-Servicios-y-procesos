# MiniDrop

Un mini-Dropbox hecho en Python. Tienes carpetas en distintos ordenadores y MiniDrop las mantiene iguales: si creas, cambias o borras un archivo en una, el cambio aparece en las demás.

- Solo usa la biblioteca estándar de Python 3 (no hay que instalar nada).
- Es un proyecto de portfolio para practicar **computación distribuida en red**: comunicación por sockets TCP, un protocolo propio, concurrencia y resolución de conflictos.

---

## 1. Cómo funciona (en 30 segundos)

```
  Carpeta A ── Cliente A ──┐
                           ├── red (TCP) ── SERVIDOR ── guarda la copia oficial
  Carpeta B ── Cliente B ──┘
```

- El **servidor** guarda la copia oficial de todos los archivos.
- Cada **cliente** vigila una carpeta de su ordenador. Cada pocos segundos le pregunta al servidor "¿ha cambiado algo?", sube lo que tú has cambiado y baja lo que han cambiado los demás.
- Los clientes nunca hablan entre ellos: todo pasa por el servidor.

---

## 2. Requisitos

- Python 3.8 o superior (`python3 --version` para comprobarlo).
- Nada más.

---

## 3. Probarlo paso a paso

Necesitas **4 terminales abiertas a la vez**. Copia solo los comandos.

Pon el proyecto en una carpeta de tu usuario, por ejemplo `~/proyectos/minidrop`, y entra en la carpeta que contiene la subcarpeta `minidrop/` (la del código). Todos los comandos se ejecutan desde ahí.

**Terminal 1: el servidor**
```bash
cd ~/proyectos/minidrop
export MINIDROP_TOKEN=un-secreto
python3 -m minidrop server --root ~/minidrop_datos --port 8765
```
Se queda ejecutándose y mostrando mensajes. Déjala abierta.

**Terminal 2: cliente A**
```bash
cd ~/proyectos/minidrop
export MINIDROP_TOKEN=un-secreto
python3 -m minidrop client --folder ~/A --id portatil
```

**Terminal 3: cliente B**
```bash
cd ~/proyectos/minidrop
export MINIDROP_TOKEN=un-secreto
python3 -m minidrop client --folder ~/B --id sobremesa
```

**Terminal 4: comprobar que funciona**
```bash
echo "hola desde A" > ~/A/nota.txt
sleep 3
cat ~/B/nota.txt
```
Debería salir `hola desde A`. Prueba también a modificar el archivo en `~/B`, a borrarlo, o a crear subcarpetas, y mira cómo se refleja en la otra carpeta.

> Para usar **dos ordenadores distintos**, arranca el servidor en uno, y en el otro añade `--host IP_DEL_SERVIDOR` al comando del cliente (el puerto 8765 debe estar accesible).

### ¿Y si dos personas editan el mismo archivo a la vez?

Gana la primera que sincroniza. La otra versión **no se pierde**: se guarda al lado como `nota (conflicto de sobremesa).txt`, para que decidas qué hacer con ella.

---

## 4. Opciones de la línea de comandos

**Servidor** (`python3 -m minidrop server ...`)

| Opción | Qué hace | Por defecto |
|---|---|---|
| `--root` | Carpeta donde guarda los archivos y el índice | `./minidrop_data` |
| `--port` | Puerto en el que escucha | `8765` |
| `--host` | Dirección en la que escucha | `0.0.0.0` (todas) |
| `--token` | Contraseña compartida | variable `MINIDROP_TOKEN` |

**Cliente** (`python3 -m minidrop client ...`)

| Opción | Qué hace | Por defecto |
|---|---|---|
| `--folder` | Carpeta a sincronizar (obligatoria) | |
| `--host` | Dirección del servidor | `127.0.0.1` |
| `--port` | Puerto del servidor | `8765` |
| `--id` | Nombre de este cliente (sale en las copias de conflicto) | nombre del equipo |
| `--interval` | Segundos entre sincronizaciones | `2` |
| `--token` | Contraseña compartida | variable `MINIDROP_TOKEN` |

El token tiene que ser el mismo en el servidor y en todos los clientes.

---

## 5. Problemas habituales

| Mensaje o síntoma | Causa y solución |
|---|---|
| `No module named minidrop` | Estás en la carpeta equivocada. Ejecuta el comando desde la carpeta que **contiene** la subcarpeta `minidrop/`. Compruébalo con `ls`: debe aparecer `minidrop`, `tests` y `README.md`. |
| `falta --token (o la variable MINIDROP_TOKEN)` | No has hecho el `export MINIDROP_TOKEN=...` **en esa terminal** (cada terminal nueva empieza sin él), o has pegado el prompt junto al comando. |
| `autenticación fallida` | El token del cliente no coincide con el del servidor. |
| `Connection refused` o "sin conexión, reintentando" | El servidor no está arrancado, o el `--host`/`--port` no coinciden. El cliente reintenta solo. |
| `Permission denied` al crear la carpeta de datos | Usa una carpeta de tu usuario (`~/minidrop_datos`); evita sitios como `/var/www/html`. |
| Los cambios tardan en aparecer | Es normal: se sincroniza cada `--interval` segundos (2 por defecto). |

---

## 6. Para entender el código

```
minidrop/
├── protocol.py   formato de los mensajes por la red
├── server.py     servidor: almacén de archivos + índice + atención a clientes
├── client.py     cliente: vigila la carpeta y sincroniza
└── __main__.py   interfaz de línea de comandos
tests/
└── test_sync.py  pruebas con un servidor real y dos clientes
```

Ejecutar las pruebas: `python3 -m unittest discover -s tests -v`

### El protocolo

Cada mensaje es: `[4 bytes con el tamaño de la cabecera][cabecera JSON][datos del archivo opcionales]`.

| Mensaje | Para qué sirve |
|---|---|
| `hello` | Identificarse con el token |
| `changes {since}` | Preguntar qué ha cambiado desde la revisión N |
| `pull {path}` | Descargar un archivo |
| `push {path, base_version, sha256}` + datos | Subir un archivo |
| `delete {path, base_version}` | Borrar un archivo |

### Ideas clave del diseño

- **Versión por archivo.** Cada archivo tiene un número de versión. Para subir un cambio, el cliente indica en qué versión se basó. Si el servidor ya tiene una más nueva, rechaza la subida y hay conflicto. Es el *control de concurrencia optimista*, el mismo principio que usan las bases de datos.
- **Revisión global.** El servidor numera cada cambio. Un cliente solo pide "lo posterior a mi última revisión", así no hay que comparar todos los archivos cada vez.
- **Borrados como cambios.** Borrar deja una marca (una *lápida*) con su versión, para que los demás clientes también borren y para detectar conflictos entre editar y borrar.
- **Integridad.** Se comprueba el hash SHA-256 al subir y al bajar, y los archivos se escriben de forma atómica (primero a un temporal y luego se renombra), así nunca queda un archivo a medias.
- **Seguridad básica.** Contraseña compartida y rechazo de rutas peligrosas como `../../etc/passwd`.

---

## 7. Limitaciones y próximos pasos

Lo que el proyecto aún **no** hace, de más a menos interesante para ampliarlo:

1. **Avisos instantáneos (push):** ahora los clientes preguntan cada pocos segundos; el servidor podría avisarles al momento.
2. **Enviar solo lo que cambió:** hoy se envían los archivos enteros. Dividirlos en bloques con hash (como rsync) permitiría archivos grandes y reanudar descargas.
3. **Cifrado (TLS) y usuarios:** ahora hay un único token compartido y los datos viajan sin cifrar.
4. **Detectar cambios al instante** con `watchdog` en vez de escanear la carpeta.
5. **Varios usuarios y permisos**, guardando los metadatos en SQLite o MySQL.
6. **Servidor replicado:** varios nodos con elección de líder, el paso hacia un sistema distribuido completo.
7. **Docker**, panel web de estado y empaquetado con `pyproject.toml`.
8. Directorios vacíos y renombrados (hoy renombrar = borrar + crear).
