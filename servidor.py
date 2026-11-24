"""
Servidor web del chatbot. Reutiliza las funciones de Humanidades.py (Pasos 1 a 4)
y entrega la interfaz que está en la carpeta web/.

Para abrirlo:  python servidor.py   (y entrar a http://127.0.0.1:8510)
"""

import json
import logging
import os
import queue
import random
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)  # para que siempre encuentre .env y credenciales.json

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from starlette.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

import Humanidades as h  # noqa: E402

registro = logging.getLogger("uvicorn.error")

RELEER_CADA = 12 * 60 * 60   # segundos: el Sheet y Drive se vuelven a leer cada 12 horas
MAX_CONVERSACIONES = 200     # al pasar el límite se olvida la menos usada
MAX_IMAGENES = 100           # imágenes guardadas en memoria

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def cabeceras_seguras(peticion, siguiente):
    respuesta = await siguiente(peticion)
    respuesta.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:"
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    if not peticion.url.path.endswith(".woff2"):
        respuesta.headers.setdefault("Cache-Control", "no-cache")
    return respuesta


# ------------------------------------------------------------
# Datos del Sheet y de Drive (en caché)
# ------------------------------------------------------------
class Archivo:
    """Foto de los datos en un momento. Al actualizar se crea otra completa."""

    def __init__(self):
        h.validar_configuracion()
        self.personaje = h.cargar_personajes(h.NOMBRE_HOJA)[0]  # primera fila del Sheet
        self.fichas = h.cargar_fichas(h.NOMBRE_HOJA)
        self.lugares = h.cargar_lugares(h.NOMBRE_HOJA)
        imagenes = h.cargar_imagenes(h.NOMBRE_HOJA)
        try:
            self.escaneos = h.listar_escaneos()
        except Exception as e:  # sin acceso a la carpeta: funciona igual, sin imágenes
            registro.warning("No se pudo leer la carpeta de escaneos: %s", type(e).__name__)
            self.escaneos = {}
        self.cliente = h.crear_cliente_gemini(h.GEMINI_API_KEY)
        self.imagenes = [h.buscar_imagenes(f, imagenes, self.escaneos) for f in self.fichas]
        self.prompt = h.construir_prompt(self.personaje, self.fichas, self.lugares)
        self.numero_por_nombre = {h.normalizar(f["nombre"]): n for n, f in enumerate(self.fichas)}
        self.version = uuid.uuid4().hex[:8]
        self.leido = time.monotonic()

    def ficha_publica(self, n):
        ficha = self.fichas[n]
        return {
            "n": n,
            "nombre": ficha["nombre"],
            "imagenes": [
                {**{c: v for c, v in imagen.items() if c != "id"},
                 "url": f"/api/fichas/{n}/imagenes/{k}?v={self.version}"}
                for k, imagen in enumerate(self.imagenes[n])
            ],
            "datos": datos_visibles(ficha),
        }


def datos_visibles(registro):
    return [[campo.replace("_", " "), valor] for campo, valor in registro.items()
            if campo not in ("nombre", "imagen", "coordenadas")]


def coordenadas(lugar):
    """Convierte "19.4514, -99.1371" en [latitud, longitud], o None si no se entiende."""
    try:
        latitud, longitud = (float(x) for x in lugar.get("coordenadas", "").split(","))
    except ValueError:
        return None
    return [latitud, longitud] if abs(latitud) < 90 and abs(longitud) <= 180 else None


_archivo = None
_candado_archivo = threading.Lock()
_imagenes = OrderedDict()
_candado_imagenes = threading.Lock()


def obtener_archivo(releer=False):
    global _archivo
    with _candado_archivo:
        if releer or _archivo is None or time.monotonic() - _archivo.leido > RELEER_CADA:
            try:
                _archivo = Archivo()
            except SystemExit as e:  # errores de configuración de Humanidades.py
                raise HTTPException(503, str(e))
            except Exception:
                registro.exception("No se pudieron leer los datos")
                raise HTTPException(503, "No se pudo leer la hoja de Google. Revisa la conexión y los permisos.")
            with _candado_imagenes:
                _imagenes.clear()
        return _archivo


def datos_del_parte(archivo):
    return {
        "nombre": archivo.personaje["nombre"],
        "fichas": [archivo.ficha_publica(n) for n in range(len(archivo.fichas))],
        "lugares": [{"nombre": lugar["nombre"], "coordenadas": coordenadas(lugar),
                     "datos": datos_visibles(lugar)} for lugar in archivo.lugares],
    }


def tipo_de_imagen(contenido):
    if contenido.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contenido.startswith(b"\x89PNG"):
        return "image/png"
    if contenido.startswith(b"GIF8"):
        return "image/gif"
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":
        return "image/webp"
    return None


@app.get("/api/parte")
def parte():
    return datos_del_parte(obtener_archivo())


@app.post("/api/actualizar")
def actualizar():
    return datos_del_parte(obtener_archivo(releer=True))


@app.get("/api/fichas/{n}/imagenes/{k}")
def imagen(n: int, k: int, v: str):
    archivo = obtener_archivo()
    if v != archivo.version:  # los números pudieron cambiar al releer el Sheet
        raise HTTPException(410, "Los expedientes se actualizaron.")
    if not 0 <= n < len(archivo.fichas) or not 0 <= k < len(archivo.imagenes[n]):
        raise HTTPException(404, "Esa imagen no existe.")
    id_archivo = archivo.imagenes[n][k]["id"]
    with _candado_imagenes:
        contenido = _imagenes.get(id_archivo)
    if contenido is None:
        try:
            contenido = h.descargar_de_drive(id_archivo)
        except Exception:
            raise HTTPException(502, "No se pudo descargar la imagen.")
        with _candado_imagenes:
            _imagenes[id_archivo] = contenido
            while len(_imagenes) > MAX_IMAGENES:
                _imagenes.popitem(last=False)
    tipo = tipo_de_imagen(contenido)
    if not tipo:
        raise HTTPException(415, "El formato de la imagen no se puede mostrar.")
    return Response(contenido, media_type=tipo, headers={"Cache-Control": "private, max-age=43200"})


# ------------------------------------------------------------
# Conversaciones
# ------------------------------------------------------------
class Conversacion:
    def __init__(self, archivo):
        self.archivo = archivo      # conserva los datos con los que empezó
        self.historial = []         # lo que Gemini recuerda
        self.ocupada = threading.Lock()


_conversaciones = OrderedDict()
_candado_conversaciones = threading.Lock()


@app.post("/api/conversacion")
def nueva_conversacion():
    conversacion = Conversacion(obtener_archivo())
    clave = uuid.uuid4().hex
    with _candado_conversaciones:
        _conversaciones[clave] = conversacion
        while len(_conversaciones) > MAX_CONVERSACIONES:
            _conversaciones.popitem(last=False)
    return {"id": clave, "folio": f"68-{random.randint(1000, 9999)}"}


class Mensaje(BaseModel):
    conversacion: str
    texto: str = Field(min_length=1, max_length=4000)


class Cancelado(Exception):
    """La persona cerró la página o empezó otro parte."""


def visible(crudo):
    """Texto que ya se puede enseñar: sin marcas [[ANEXO: ...]], ni completas ni a medias."""
    return h.texto_visible(h.separar_anexos(crudo)[0]).rstrip("[").rstrip()


def generar(conversacion, texto, cola, cancelar):
    """Corre en un hilo: pone los eventos en la cola y termina con None."""
    archivo = conversacion.archivo

    def avisar(aviso):
        if cancelar.is_set():
            raise Cancelado
        cola.put({"tipo": "aviso", "texto": aviso})

    crudo = enviado = ""
    try:
        for pedazo in h.responder(archivo.cliente, archivo.prompt,
                                  conversacion.historial, texto, avisar=avisar):
            if cancelar.is_set():
                raise Cancelado
            if pedazo is h.REINICIAR:
                crudo = enviado = ""
                cola.put({"tipo": "reiniciar"})
                continue
            crudo += pedazo
            ahora = visible(crudo)
            if not ahora.startswith(enviado):
                cola.put({"tipo": "reiniciar"})
                enviado = ""
            if len(ahora) > len(enviado):
                cola.put({"tipo": "texto", "texto": ahora[len(enviado):]})
                enviado = ahora
        limpio, nombres = h.separar_anexos(crudo)
        numeros = [archivo.numero_por_nombre.get(h.normalizar(nombre)) for nombre in nombres]
        anexos = [archivo.ficha_publica(n) for n in dict.fromkeys(numeros) if n is not None]
        cola.put({"tipo": "anexos", "fichas": anexos})
        cola.put({"tipo": "fin", "texto": limpio})
    except Cancelado:
        pass
    except RuntimeError as e:  # responder() agotó los reintentos
        cola.put({"tipo": "error", "texto": str(e)})
    except Exception as e:
        registro.exception("Error al contactar a Gemini")
        codigo = getattr(e, "code", None)
        cola.put({"tipo": "error",
                  "texto": "No se pudo contactar a Gemini" + (f" (código {codigo})." if codigo else ".")})
    finally:
        conversacion.ocupada.release()
        cola.put(None)


@app.post("/api/mensaje")
def mensaje(datos: Mensaje):
    texto = datos.texto.strip()
    if not texto:
        raise HTTPException(422, "Escribe una pregunta.")
    with _candado_conversaciones:
        conversacion = _conversaciones.get(datos.conversacion)
        if conversacion:
            _conversaciones.move_to_end(datos.conversacion)
    if not conversacion:
        raise HTTPException(404, "Este parte ya no existe. Abre uno nuevo.")
    if not conversacion.ocupada.acquire(blocking=False):
        raise HTTPException(409, "La unidad todavía está declarando.")

    cola = queue.Queue()
    cancelar = threading.Event()
    threading.Thread(target=generar, args=(conversacion, texto, cola, cancelar), daemon=True).start()

    def eventos():
        try:
            while (evento := cola.get()) is not None:
                yield json.dumps(evento, ensure_ascii=False) + "\n"  # un evento por línea
        finally:
            cancelar.set()

    return StreamingResponse(eventos(), media_type="application/x-ndjson")


# ------------------------------------------------------------
# Página
# ------------------------------------------------------------
@app.get("/")
def pagina():
    return FileResponse(BASE / "web" / "index.html")


app.mount("/web", StaticFiles(directory=BASE / "web"), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8510")))
