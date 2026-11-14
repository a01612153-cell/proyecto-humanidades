# Chatbot que personifica a un personaje histórico
#Paso 1: preparar el entorno y las credenciales
#Paso 2: Leer los datos del personaje desde Google Sheets
#Paso 3: Construir el system prompt del personaje
#Paso 4:Conectar con Gemini y mantener la conversación
#Paso 5:Bucle de interacción con  el usuario

#%%
#Paso 1: preparar el entorno y las credenciales
import os
import re
import time
import unicodedata

import gspread
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv(override=True)


#%%
#Paso 1.1: Configuración de variables de entorno
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
NOMBRE_HOJA = os.getenv("NOMBRE_HOJA")
RUTA_CREDENCIALES = os.getenv("RUTA_CREDENCIALES", "credenciales.json")
PESTANA_FICHAS = os.getenv("PESTANA_FICHAS", "Fichas")  # pestaña con las fichas de personas
CARPETA_ESCANEOS = os.getenv("CARPETA_ESCANEOS", "")     # carpeta de Drive con los escaneos
MODELO = os.getenv("MODELO", "gemini-3.5-flash")


def validar_configuracion():
    """Revisa que las variables necesarias existan antes de empezar."""
    faltantes = []
    if not GEMINI_API_KEY:
        faltantes.append("GEMINI_API_KEY")
    if not NOMBRE_HOJA:
        faltantes.append("NOMBRE_HOJA")
    if faltantes:
        raise SystemExit(f"Faltan variables en el archivo .env: {', '.join(faltantes)}")
    if not os.path.exists(RUTA_CREDENCIALES):
        raise SystemExit(f"No se encontró el archivo de credenciales: {RUTA_CREDENCIALES}")
    print("Todas las variables de entorno necesarias están presentes.")


# Solo corre al ejecutar este archivo (no cuando app.py lo importa)
if __name__ == "__main__":
    validar_configuracion()





# %%
#Paso 2: Leer los datos del personaje desde Google Sheets
#se realiza la conecexión  con Google Sheets y se obtiene la información del personaje historico
def cargar_personajes(nombre_hoja):
    """
    Lee la primera pestaña del Sheet. Cada fila es un personaje y cada columna un dato:

        | nombre                    | epoca                 | personalidad | forma_de_hablar | datos_clave |
        |---------------------------|-----------------------|--------------|-----------------|-------------|
        | Sor Juana Inés de la Cruz | Nueva España, s. XVII | ...          | ...             | ...         |
        | Benito Juárez             | México, s. XIX        | ...          | ...             | ...         |

    Devuelve una lista de diccionarios, uno por personaje.
    """
    gc = gspread.service_account(filename=RUTA_CREDENCIALES)
    hoja = gc.open(nombre_hoja).sheet1
    personajes = limpiar_filas(hoja.get_all_records())

    if not personajes:
        raise SystemExit("El Sheet no tiene personajes. Revisa que exista la columna 'nombre' en la fila 1.")

    return personajes


def limpiar_filas(filas):
    """Limpia espacios, pasa los encabezados a minúsculas, ignora celdas vacías
    y descarta las filas que no tienen 'nombre'."""
    limpias = []
    for fila in filas:
        registro = {
            str(columna).strip().lower(): str(valor).strip()
            for columna, valor in fila.items()
            if str(valor).strip()
        }
        if registro.get("nombre"):
            limpias.append(registro)
    return limpias


def cargar_fichas(nombre_hoja, pestana=PESTANA_FICHAS):
    """
    Lee la pestaña de fichas (por defecto "Fichas"). Cada fila es una persona
    implicada en los hechos; la única columna obligatoria es 'nombre':

        | nombre | rol        | que_paso_el_2_de_octubre | destino | fuentes |
        |--------|------------|--------------------------|---------|---------|
        | ...    | estudiante | ...                      | ...     | ...     |

    Si la pestaña no existe, regresa una lista vacía (el personaje funciona sin fichas).
    """
    gc = gspread.service_account(filename=RUTA_CREDENCIALES)
    try:
        hoja = gc.open(nombre_hoja).worksheet(pestana)
    except gspread.exceptions.WorksheetNotFound:
        return []
    return limpiar_filas(hoja.get_all_records())


#%%
#Paso 2.1: Escaneos de las fichas en Google Drive
# Cada ficha puede tener un escaneo. Se busca así:
#   1) si la ficha tiene la columna 'imagen' con un enlace de Drive, se usa ese archivo;
#   2) si no, se busca en la carpeta CARPETA_ESCANEOS un archivo que se llame
#      igual que la persona (por ejemplo "Marta Ejemplo Díaz.jpg").
def normalizar(texto):
    """Minúsculas, sin acentos y sin lo que va entre paréntesis, para comparar nombres
    sin importar cómo se escribieron ("Marta Díaz (PRUEBA)" = "marta diaz")."""
    sin_parentesis = re.sub(r"\(.*?\)", " ", texto)
    sin_acentos = unicodedata.normalize("NFKD", sin_parentesis).encode("ascii", "ignore").decode()
    return " ".join(sin_acentos.lower().split())


def id_de_drive(enlace):
    """Saca el ID de un enlace de Drive (…/d/ID/…, …/folders/ID, ?id=ID o el ID solo)."""
    for patron in (r"/d/([\w-]{20,})", r"/folders/([\w-]{20,})",
                   r"[?&]id=([\w-]{20,})", r"^([\w-]{20,})$"):
        encontrado = re.search(patron, enlace.strip())
        if encontrado:
            return encontrado.group(1)
    return None


def sesion_drive():
    """Sesión autenticada con la service account (la misma que usa gspread)."""
    return gspread.service_account(filename=RUTA_CREDENCIALES).http_client.session


def listar_escaneos(carpeta=CARPETA_ESCANEOS):
    """Regresa {nombre normalizado sin extensión: id del archivo} de las imágenes de la carpeta."""
    if not carpeta:
        return {}
    respuesta = sesion_drive().get(
        "https://www.googleapis.com/drive/v3/files",
        params={
            "q": f"'{id_de_drive(carpeta)}' in parents and mimeType contains 'image/' and trashed = false",
            "fields": "files(id, name)",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
    )
    respuesta.raise_for_status()
    return {
        normalizar(os.path.splitext(archivo["name"])[0]): archivo["id"]
        for archivo in respuesta.json().get("files", [])
    }


def buscar_escaneo(ficha, escaneos):
    """Regresa el id de Drive del escaneo de una ficha, o None si no tiene."""
    if ficha.get("imagen"):
        return id_de_drive(ficha["imagen"])
    return escaneos.get(normalizar(ficha["nombre"]))


def descargar_de_drive(id_archivo):
    """Descarga el contenido (bytes) de un archivo de Drive."""
    respuesta = sesion_drive().get(
        f"https://www.googleapis.com/drive/v3/files/{id_archivo}",
        params={"alt": "media", "supportsAllDrives": "true"},
    )
    respuesta.raise_for_status()
    return respuesta.content


def elegir_personaje(personajes):
    """Muestra un menú con los nombres y regresa el personaje elegido."""
    print("\nPersonajes disponibles:")
    for i, p in enumerate(personajes, start=1):
        print(f"  {i}. {p['nombre']}")

    while True:
        opcion = input("\nElige un número: ").strip()
        if opcion.isdigit() and 1 <= int(opcion) <= len(personajes):
            return personajes[int(opcion) - 1]
        print(f"Opción no válida. Escribe un número del 1 al {len(personajes)}.")


if __name__ == "__main__":
    personajes = cargar_personajes(NOMBRE_HOJA)
    personaje = elegir_personaje(personajes)
    print(personaje)

    fichas = cargar_fichas(NOMBRE_HOJA)
    print(f"Fichas cargadas de la pestaña '{PESTANA_FICHAS}': {len(fichas)}")

# %%
#Paso 3: Construir el system prompt del personaje
def formatear_datos(registro, excluir=()):
    """Convierte un diccionario en una lista de viñetas: '- Campo: valor'."""
    return "\n".join(
        f"- {campo.replace('_', ' ').capitalize()}: {valor}"
        for campo, valor in registro.items()
        if campo not in excluir
    )


def construir_prompt(personaje, fichas=None):
    """Crea el prompt del personaje a partir de sus datos y, si hay, de las fichas."""
    nombre = personaje["nombre"]

    # Columnas extra del Sheet (obras, frases_celebres, etc.) se agregan solas
    campos_base = {"nombre", "epoca", "personalidad", "forma_de_hablar", "datos_clave", "conocimiento_hasta"}
    extras = formatear_datos(personaje, excluir=campos_base)

    # Columna opcional: hasta cuándo sabe cosas el personaje (por defecto, hasta su muerte)
    if personaje.get("conocimiento_hasta"):
        regla_tiempo = (f"- Solo conoces lo que pasó hasta {personaje['conocimiento_hasta']}. "
                        "Si te preguntan por algo posterior, reacciona con extrañeza o di que no lo sabes.")
    else:
        regla_tiempo = ("- Solo conoces lo que pasó hasta tu muerte. Si te preguntan por algo posterior, "
                        "reacciona con curiosidad o extrañeza desde tu época.")

    prompt = f"""
Eres {nombre}, {personaje.get('epoca', 'un personaje histórico').rstrip('.')}.

## Identidad
- Personalidad: {personaje.get('personalidad', 'acorde a tu historia')}
- Forma de hablar: {personaje.get('forma_de_hablar', 'acorde a tu época')}
- Datos clave: {personaje.get('datos_clave', 'los que se conocen de tu historia')}
{extras}

## Reglas
- Habla siempre en primera persona como {nombre}. No rompas el personaje ni digas que eres una IA.
{regla_tiempo}
- Si no sabes algo con certeza histórica, admítelo con tu propia personalidad. No inventes datos.
- Si hablas de víctimas de violencia, hazlo con respeto: no te burles de ellas ni glorifiques la violencia.
- Responde en español, en 1 a 3 párrafos.
"""

    if fichas:
        expedientes = "\n\n".join(
            f"### Expediente {i}: {ficha['nombre']}\n{formatear_datos(ficha, excluir={'nombre', 'imagen'})}"
            for i, ficha in enumerate(fichas, start=1)
        )
        prompt += f"""
## Expedientes
Tienes acceso a {len(fichas)} expedientes sobre personas relacionadas con los hechos.
Son tu ÚNICA fuente de información sobre personas específicas.

{expedientes}

## Reglas sobre los expedientes
- Cuando hables de una persona concreta, usa solo lo que dice su expediente.
- Si te preguntan por alguien que no tiene expediente, o por un dato que no aparece en él, dilo claramente (por ejemplo: "ese dato no consta en mis expedientes"). Nunca lo inventes ni lo adivines.
- No atribuyas a personas reales actos, culpas o frases que no estén en su expediente.
- Si un expediente indica que algo es incierto o está en disputa, preséntalo así.
- Si el expediente incluye fuentes, puedes citarlas cuando te pregunten de dónde sale la información.
- Cada vez que tu respuesta use información del expediente de una persona, agrega al final, en una línea aparte, la marca [[ANEXO: nombre]] con el nombre exacto como aparece en el título del expediente (una línea por persona). Nunca pongas esa marca para personas sin expediente.
"""

    return prompt.strip()


def separar_anexos(texto):
    """
    Separa la respuesta del personaje de sus marcas [[ANEXO: nombre]].
    Regresa (texto sin marcas, lista de nombres sin repetir).
    """
    nombres = re.findall(r"\[\[\s*ANEXO\s*:\s*(.+?)\s*\]\]", texto, flags=re.IGNORECASE)
    limpio = re.sub(r"\[\[\s*ANEXO\s*:.*?\]\]", "", texto, flags=re.IGNORECASE)
    return limpio.strip(), list(dict.fromkeys(nombres))


def texto_visible(texto):
    """Lo que se muestra mientras se escribe la respuesta: oculta las marcas
    de anexo, incluso cuando todavía van a la mitad (por ejemplo '[[ANE')."""
    return re.sub(r"\[\[.*$", "", texto, flags=re.DOTALL).rstrip()


if __name__ == "__main__":
    prompt = construir_prompt(personaje, fichas)
    print(prompt)


# %%
#Paso 4:Conectar con Gemini y su API
def crear_cliente_gemini(api_key):
    """Crea un cliente de Gemini con la API Key proporcionada."""
    if not api_key:
        raise SystemExit("No se proporcionó la API Key de Gemini.")
    # attempts=1: la librería no reintenta sola el mismo modelo;
    # de eso se encarga responder() probando otros modelos (Paso 4.2)
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
    )


if __name__ == "__main__":
    cliente = crear_cliente_gemini(GEMINI_API_KEY)


#%%
#Paso 4.1:mantener la conversación con Gemini
def iniciar_chat(cliente, prompt):
    """Crea una sesión de chat con el personaje. La sesión guarda el historial,
    así el personaje recuerda lo que se ha dicho en la conversación."""
    return cliente.chats.create(
        model=MODELO,
        config=types.GenerateContentConfig(
            system_instruction=prompt,
            temperature=0.8,  # más alto = más creativo/expresivo
        ),
    )


if __name__ == "__main__":
    chat = iniciar_chat(cliente, prompt)

    # Prueba: un mensaje para ver si el personaje responde
    respuesta = chat.send_message("Hola, ¿quién eres?")
    print(respuesta.text)

#%%
#Paso 4.2: Respuesta con modelos de respaldo
# Si un modelo está saturado ("high demand"), se intenta con el siguiente.
# Si todos fallan, se espera y se vuelve a intentar la lista completa.
MODELOS_RESPALDO = os.getenv(
    "MODELOS_RESPALDO", "gemini-3.5-flash,gemini-flash-latest,gemini-3.1-flash-lite"
)
MODELOS = list(dict.fromkeys(  # MODELO va primero; dict.fromkeys quita repetidos
    [MODELO] + [m.strip() for m in MODELOS_RESPALDO.split(",") if m.strip()]
))
MAX_RONDAS = 10  # rondas por toda la lista; con las esperas son ~4 minutos en total

# 404 = modelo retirado, 429 = límite de uso, 5xx = servidor saturado o caído
ERRORES_TEMPORALES = {404, 429, 500, 502, 503, 504}

# Señal que responder() envía cuando un modelo falla a media respuesta:
# quien muestre la respuesta debe borrar lo que lleva y empezar de nuevo.
REINICIAR = object()


def responder(cliente, prompt, historial, mensaje, avisar=print):
    """
    Genera la respuesta del personaje pedazo a pedazo (es un generador).
    Normalmente entrega textos; si un modelo falla a media respuesta, entrega
    REINICIAR y vuelve a empezar con otro modelo.
    `historial` es una lista que guarda la conversación; al terminar se le
    agregan el mensaje del usuario y la respuesta.
    `avisar` es una función para mostrar los cambios de modelo y las esperas.
    """
    contenidos = historial + [types.Content(role="user", parts=[types.Part(text=mensaje)])]
    config = types.GenerateContentConfig(
        system_instruction=prompt,
        temperature=0.8,
        # No usamos herramientas; esto evita un aviso innecesario de la librería
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    for ronda in range(1, MAX_RONDAS + 1):
        for modelo in MODELOS:
            partes = []
            try:
                for pedazo in cliente.models.generate_content_stream(
                    model=modelo, contents=contenidos, config=config
                ):
                    if pedazo.text:
                        partes.append(pedazo.text)
                        yield pedazo.text
            except errors.APIError as e:
                if e.code not in ERRORES_TEMPORALES:
                    raise
                if partes:
                    # Falló a media respuesta: se descarta lo que llevaba
                    avisar(f"{modelo} se interrumpió ({e.code}). Repitiendo la respuesta con otro modelo...")
                    yield REINICIAR
                else:
                    avisar(f"{modelo} no está disponible ({e.code}). Probando con otro modelo...")
                continue

            if partes:
                historial.extend([
                    contenidos[-1],
                    types.Content(role="model", parts=[types.Part(text="".join(partes))]),
                ])
                return
            avisar(f"{modelo} regresó una respuesta vacía. Probando con otro modelo...")

        espera = min(5 * ronda, 30)
        avisar(f"Todos los modelos están ocupados. Reintentando en {espera} segundos "
               f"(intento {ronda} de {MAX_RONDAS})...")
        time.sleep(espera)

    raise RuntimeError("Ningún modelo respondió después de varios intentos. Intenta más tarde.")


# %%
#Paso 5:Bucle de interacción con  el usuario
def bucle_interaccion(cliente, prompt, nombre):
    """Bucle principal de interacción con el usuario. El usuario escribe algo,
    el personaje responde, y así sucesivamente."""
    historial = []
    print("\n¡Comienza la conversación! Escribe 'salir' para terminar.\n")
    while True:
        entrada_usuario = input("Tú: ").strip()
        if entrada_usuario.lower() == "salir":
            print("Fin de la conversación.")
            break
        print(f"{nombre}: ", end="", flush=True)
        for pedazo in responder(cliente, prompt, historial, entrada_usuario):
            if pedazo is REINICIAR:
                # La respuesta se cortó; empieza de nuevo en otra línea
                print(f"\n{nombre}: ", end="", flush=True)
            else:
                print(pedazo, end="", flush=True)
        print("\n")
# %%
