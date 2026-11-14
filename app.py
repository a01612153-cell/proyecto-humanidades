"""
Interfaz web del chatbot: la conversación aparece como un parte militar
escrito a máquina. Reutiliza las funciones de Humanidades.py (Pasos 1 a 4).

Para abrirla:  streamlit run app.py
"""

import html
import json
import os
import random
import time
from datetime import datetime

import streamlit as st


def cargar_secretos_de_la_nube():
    """En Streamlit Cloud no existen .env ni credenciales.json (no se suben a GitHub).
    Ahí las claves van en los "Secrets" de la app; esto las pasa a variables de entorno
    y escribe el archivo de credenciales ANTES de importar Humanidades.py."""
    try:
        secretos = dict(st.secrets)
    except Exception:
        return  # en tu computadora no hay secrets: se usa el .env como siempre
    for clave, valor in secretos.items():
        if isinstance(valor, str):
            os.environ.setdefault(clave, valor)
    if "gcp_service_account" in secretos:
        ruta = os.environ.setdefault("RUTA_CREDENCIALES", "credenciales.json")
        if not os.path.exists(ruta):
            with open(ruta, "w", encoding="utf-8") as archivo:
                json.dump(dict(secretos["gcp_service_account"]), archivo)


cargar_secretos_de_la_nube()

from Humanidades import (  # noqa: E402  (va después de cargar los secretos)
    GEMINI_API_KEY,
    NOMBRE_HOJA,
    REINICIAR,
    buscar_escaneo,
    cargar_fichas,
    cargar_personajes,
    construir_prompt,
    crear_cliente_gemini,
    descargar_de_drive,
    listar_escaneos,
    normalizar,
    responder,
    separar_anexos,
    texto_visible,
    validar_configuracion,
)

st.set_page_config(page_title="Parte de novedades", page_icon="📄", layout="centered")

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
         "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]


# ------------------------------------------------------------
# Estilo: hoja de papel y letra de máquina de escribir
# ------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Special+Elite&family=Caveat:wght@500&display=swap');

:root {
  --escritorio: #2a2823;
  --papel: #f1e9d2;
  --papel-borde: #d9cdab;
  --tinta: #22201b;
  --tinta-tenue: #5b554a;
  --sello: #a8261f;
  --pluma: #1f3f8a;      /* tinta azul de la pluma del civil */
  --nota-papel: #fbf7e8; /* papel de la nota del civil */
}

/* Fondo de escritorio y letra de máquina en toda la página */
.stApp, [data-testid="stBottom"], [data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
  background: var(--escritorio) !important;
}
.stApp, .stApp * {
  font-family: 'Special Elite', 'Courier New', Courier, monospace !important;
  color: var(--tinta);
}

/* Ocultar los menús de Streamlit */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stSidebar"],
[data-testid="collapsedControl"], #MainMenu, footer { display: none !important; }

/* La hoja de papel */
.block-container {
  max-width: 820px !important;
  margin: 2.5rem auto 7rem auto;
  padding: 3rem 3.5rem 3.5rem 3.5rem !important;
  background:
    radial-gradient(circle at 15% 10%, rgba(120, 90, 30, 0.08), transparent 40%),
    radial-gradient(circle at 85% 90%, rgba(120, 90, 30, 0.10), transparent 45%),
    var(--papel);
  border: 1px solid var(--papel-borde);
  box-shadow: 0 18px 40px rgba(0, 0, 0, 0.55);
}

/* Tinta ligeramente corrida, como en una máquina de escribir */
.block-container p, .block-container li, .block-container div {
  text-shadow: 0 0 0.6px rgba(34, 32, 27, 0.65);
  line-height: 1.65;
}

/* Encabezado del parte */
.membrete { text-align: center; letter-spacing: 0.18em; margin-bottom: 0.4rem; }
.membrete .titulo { font-size: 1.35rem; }
.membrete .sub { font-size: 0.85rem; color: var(--tinta-tenue); }
.datos-parte { font-size: 0.9rem; margin: 1.2rem 0 0.4rem 0; }
.datos-parte td { padding: 0.12rem 0.8rem 0.12rem 0; vertical-align: top; border: none; }
.datos-parte td:first-child { white-space: nowrap; }
.datos-parte table, .datos-parte tr { border: none; background: transparent; }
.sello {
  float: right; margin: -0.6rem -0.4rem 0 1rem; padding: 0.25rem 0.7rem;
  border: 3px double var(--sello); color: var(--sello) !important;
  transform: rotate(-9deg); letter-spacing: 0.15em; opacity: 0.8; font-size: 1.05rem;
}
.raya { border: none; border-top: 2px dashed var(--tinta-tenue); margin: 1rem 0 1.4rem 0; opacity: 0.6; }

/* Entradas de la conversación */
.etiqueta { letter-spacing: 0.08em; font-size: 0.9rem; margin-top: 1.6rem; }
.etiqueta .hora { color: var(--tinta-tenue); }

/* LA BALA: mecanografiada en tinta negra, etiqueta en la tinta roja de la cinta */
.etiqueta-bala { color: var(--sello) !important; }
.etiqueta-bala .hora { color: var(--sello) !important; opacity: 0.75; }
[class*="st-key-texto-bala"] {
  border-left: 3px solid var(--tinta);
  padding-left: 1rem;
  margin-left: 0.3rem;
}

/* EL CIVIL: escrito a mano con pluma azul, en una nota de papel rayado */
.etiqueta-civil { margin-left: 2.2rem; }
.stApp .etiqueta-civil, .stApp .etiqueta-civil * {
  font-family: 'Caveat', cursive !important;
  font-size: 1.15rem; letter-spacing: 0; color: var(--pluma) !important;
}
.etiqueta-civil .hora { color: var(--pluma) !important; opacity: 0.7; }
.stApp [class*="st-key-texto-civil"] {
  margin-left: 2.2rem; max-width: 82%;
  padding: 0.35rem 1rem 0.2rem 1rem;
  background:
    repeating-linear-gradient(transparent 0 1.85rem, rgba(31, 63, 138, 0.18) 1.85rem 1.9rem),
    var(--nota-papel);
  border: 1px solid #e3dcc4;
  box-shadow: 2px 3px 6px rgba(0, 0, 0, 0.12);
  transform: rotate(-0.6deg);
}
.stApp [class*="st-key-texto-civil"] * {
  font-family: 'Caveat', cursive !important;
  color: var(--pluma) !important;
  font-size: 1.4rem; line-height: 1.9rem; text-shadow: none;
}
.nota { color: var(--tinta-tenue); font-size: 0.85rem; }
.vacio { text-align: center; color: var(--tinta-tenue); letter-spacing: 0.08em; margin: 2rem 0; }
.firma { margin-top: 2.5rem; font-size: 0.9rem; }

/* Botones como texto mecanografiado entre corchetes */
.stButton button {
  background: transparent !important; border: 1px dashed var(--tinta-tenue) !important;
  border-radius: 0 !important; letter-spacing: 0.06em;
}
.stButton button:hover { border-style: solid !important; background: rgba(0,0,0,0.04) !important; }

/* Caja de texto: una tira de papel debajo de la hoja */
[data-testid="stChatInput"] {
  max-width: 820px; margin: 0 auto;
}
[data-testid="stChatInput"] > div {
  background: var(--papel) !important; border: 1px solid var(--papel-borde) !important;
  border-radius: 0 !important;
}
/* El civil escribe a mano (igual que sus notas); el texto de ayuda sigue mecanografiado */
.stApp [data-testid="stChatInput"] textarea {
  font-family: 'Caveat', cursive !important;
  color: var(--pluma) !important; font-size: 1.35rem !important;
}
.stApp [data-testid="stChatInput"] textarea::placeholder {
  font-family: 'Special Elite', 'Courier New', monospace !important;
  color: var(--tinta-tenue) !important; font-size: 0.9rem;
}

/* ANEXOS: escaneos de las fichas, como fotos engrapadas con un clip */
[class*="st-key-anexo-"] {
  position: relative;
  background: #fbf8ef; padding: 10px 10px 4px 10px;
  box-shadow: 2px 5px 12px rgba(0, 0, 0, 0.35);
  margin: 1.4rem 0 0.6rem 0;
  transform: rotate(-1.2deg);
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}
[class*="st-key-anexo-b"] { transform: rotate(1.3deg); }
/* Al pasar el mouse, la foto se endereza y se levanta del papel */
[class*="st-key-anexo-"]:hover {
  transform: rotate(0deg) scale(1.03);
  box-shadow: 4px 10px 22px rgba(0, 0, 0, 0.45);
  z-index: 3;
}
/* Los escaneos se ven envejecidos, como fotos de archivo */
[class*="st-key-anexo-"] img {
  filter: sepia(0.35) contrast(1.05);
  border: 1px solid #d6cfbd;
}
[class*="st-key-anexo-"] .stButton button {
  font-size: 0.72rem !important; padding: 0.1rem 0.4rem !important; min-height: 0 !important;
}

/* Visor del expediente (ventana emergente) */
[data-testid="stDialog"] [role="dialog"] {
  background: var(--papel) !important; border-radius: 0 !important;
  border: 1px solid var(--papel-borde);
}
[data-testid="stDialog"] img { filter: sepia(0.2); border: 1px solid #d6cfbd; }
.ficha-dato { font-size: 0.88rem; margin-bottom: 0.5rem; }
.ficha-dato b { letter-spacing: 0.06em; }
[class*="st-key-anexo-"]::before {  /* el clip */
  content: ""; position: absolute; z-index: 2;
  top: -16px; left: 46%; width: 16px; height: 46px;
  border: 4px solid #85858c; border-radius: 9px;
}
.pie-anexo { text-align: center; font-size: 0.78rem; letter-spacing: 0.06em; padding: 0.3rem 0 0.2rem 0; }

/* Pantallas angostas (celular) */
@media (max-width: 640px) {
  .block-container { margin: 0.8rem 0 6rem 0; padding: 1.6rem 1rem 2rem 1rem !important; }
  .sello { float: none; display: inline-block; margin: 0 0 0.8rem 0; }
  .etiqueta-civil, .stApp [class*="st-key-texto-civil"] { margin-left: 0.8rem; max-width: 100%; }
  [class*="st-key-texto-bala"] { padding-left: 0.7rem; }
}
</style>
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# Carga de datos (se guarda en caché para no leer el Sheet en cada mensaje)
# ------------------------------------------------------------
RELEER_CADA = 12 * 60 * 60  # segundos: el Sheet y Drive se vuelven a leer cada 12 horas


@st.cache_data(ttl=RELEER_CADA, show_spinner="Consultando el archivo...")
def obtener_personajes():
    return cargar_personajes(NOMBRE_HOJA)


@st.cache_data(ttl=RELEER_CADA, show_spinner="Consultando expedientes...")
def obtener_fichas():
    return cargar_fichas(NOMBRE_HOJA)


@st.cache_data(ttl=RELEER_CADA, show_spinner="Consultando escaneos...")
def obtener_escaneos():
    return listar_escaneos()


@st.cache_data(ttl=RELEER_CADA, show_spinner=False)
def obtener_imagen(id_archivo):
    return descargar_de_drive(id_archivo)


@st.cache_resource
def obtener_cliente():
    return crear_cliente_gemini(GEMINI_API_KEY)


try:
    validar_configuracion()
    personaje = obtener_personajes()[0]  # el personaje es la primera fila del Sheet
    fichas = obtener_fichas()
    cliente = obtener_cliente()
    try:
        escaneos = obtener_escaneos()
    except Exception:
        escaneos = {}  # sin acceso a la carpeta: la app funciona igual, sin imágenes
except SystemExit as e:
    # Las funciones de Humanidades.py usan SystemExit para los errores de configuración
    st.error(str(e))
    st.stop()
except Exception as e:
    st.error(f"No se pudo iniciar: {e}")
    st.stop()


def iniciar_parte():
    """Empieza una conversación nueva (un parte nuevo)."""
    st.session_state.prompt = construir_prompt(personaje, fichas)
    st.session_state.historial = []  # lo que Gemini recuerda de la conversación
    st.session_state.mensajes = []   # lo que se muestra en la hoja
    st.session_state.folio = f"68-{random.randint(1000, 9999)}"


if "mensajes" not in st.session_state:
    iniciar_parte()


def fecha_mecanografiada(fecha):
    return f"{fecha.day} DE {MESES[fecha.month - 1]} DE {fecha.year}"


def texto_seguro(texto):
    """Evita que Streamlit interprete '$' como fórmula matemática."""
    return texto.replace("$", "\\$")


def mostrar_etiqueta(rol, hora):
    if rol == "civil":
        # Anotación a mano del civil
        etiqueta = f'Pregunta del civil <span class="hora">&mdash; {hora} hrs.</span>'
    else:
        # Encabezado mecanografiado de la declaración
        etiqueta = f'&#9656; DECLARACIÓN DE LA UNIDAD <span class="hora">({hora} HRS.):</span>'
    st.markdown(f'<div class="etiqueta etiqueta-{rol}">{etiqueta}</div>', unsafe_allow_html=True)


def mecanografiar(lugar, texto_previo, nuevo):
    """Escribe `nuevo` poco a poco después de `texto_previo`, como una máquina de escribir."""
    texto = texto_previo
    for i in range(0, len(nuevo), 3):
        texto = texto_previo + nuevo[: i + 3]
        # texto_visible() oculta las marcas [[ANEXO: ...]] mientras se escriben
        lugar.markdown(texto_seguro(texto_visible(texto)) + "▌")
        time.sleep(0.012)
    return texto_previo + nuevo


FICHAS_POR_NOMBRE = {normalizar(f["nombre"]): f for f in fichas}


def imagen_de_ficha(ficha):
    """Descarga (con caché) el escaneo de una ficha, o None si no tiene."""
    id_archivo = buscar_escaneo(ficha, escaneos)
    if not id_archivo:
        return None
    try:
        return obtener_imagen(id_archivo)
    except Exception:
        return None


@st.dialog("EXPEDIENTE", width="large")
def ver_expediente(ficha, numero):
    """Ventana con el escaneo en grande y los datos de la ficha del Sheet."""
    st.markdown(f'<div class="pie-anexo">ANEXO {numero} &mdash; '
                f'{html.escape(ficha["nombre"].upper())}</div>', unsafe_allow_html=True)
    izquierda, derecha = st.columns([3, 2])
    imagen = imagen_de_ficha(ficha)
    if imagen:
        izquierda.image(imagen, width="stretch")
    else:
        izquierda.markdown('<div class="nota">[ESCANEO NO DISPONIBLE EN EL ARCHIVO]</div>',
                           unsafe_allow_html=True)
    # Todas las columnas de la ficha, menos el nombre y el enlace de la imagen
    for campo, valor in ficha.items():
        if campo in ("nombre", "imagen"):
            continue
        derecha.markdown(
            f'<div class="ficha-dato"><b>{html.escape(campo.replace("_", " ").upper())}:</b> '
            f'{html.escape(valor)}</div>',
            unsafe_allow_html=True,
        )


def mostrar_anexos(nombres, primer_numero, clave):
    """Muestra los escaneos de las fichas mencionadas, como anexos del parte.
    Regresa cuántos anexos mostró (para seguir la numeración)."""
    encontradas = [FICHAS_POR_NOMBRE[normalizar(n)] for n in nombres if normalizar(n) in FICHAS_POR_NOMBRE]
    if not encontradas:
        return 0

    if len(encontradas) == 1:
        columnas = [st.columns([1, 2.2, 1])[1]]  # una sola: centrada
    else:
        columnas = st.columns(min(len(encontradas), 3))

    for k, ficha in enumerate(encontradas):
        lado = "a" if k % 2 == 0 else "b"  # inclinación alterna
        with columnas[k % len(columnas)], st.container(key=f"anexo-{lado}-{clave}-{k}"):
            imagen = imagen_de_ficha(ficha)
            if imagen:
                st.image(imagen, width="stretch")
            else:
                st.markdown('<div class="nota">[ESCANEO NO DISPONIBLE EN EL ARCHIVO]</div>',
                            unsafe_allow_html=True)
            st.markdown(
                f'<div class="pie-anexo">ANEXO {primer_numero + k} &mdash; '
                f'EXPEDIENTE: {html.escape(ficha["nombre"].upper())}</div>',
                unsafe_allow_html=True,
            )
            if st.button("[ AMPLIAR ]", key=f"ampliar-{clave}-{k}", use_container_width=True):
                ver_expediente(ficha, primer_numero + k)
    return len(encontradas)


# ------------------------------------------------------------
# Encabezado del parte
# ------------------------------------------------------------
nombre = html.escape(personaje["nombre"].upper())
st.markdown(
    f"""
<div class="sello">CONFIDENCIAL</div>
<div class="membrete">
  <div class="titulo">PARTE DE NOVEDADES</div>
  <div class="sub">ARCHIVO DE EVIDENCIAS &middot; DECLARACIÓN DE OBJETO</div>
</div>
<div class="datos-parte">
<table>
  <tr><td>FOLIO:</td><td>{st.session_state.folio}</td></tr>
  <tr><td>DECLARANTE:</td><td>{nombre}</td></tr>
  <tr><td>LUGAR DE LOS HECHOS:</td><td>PLAZA DE LAS TRES CULTURAS, TLATELOLCO, CIUDAD DE MÉXICO</td></tr>
  <tr><td>FECHA DE LOS HECHOS:</td><td>2 DE OCTUBRE DE 1968</td></tr>
  <tr><td>FECHA DEL INTERROGATORIO:</td><td>{fecha_mecanografiada(datetime.now())}</td></tr>
  <tr><td>EXPEDIENTES ANEXOS:</td><td>{len(fichas)}</td></tr>
</table>
</div>
<hr class="raya">
""",
    unsafe_allow_html=True,
)


# ------------------------------------------------------------
# Conversación
# ------------------------------------------------------------
# La caja de texto siempre aparece abajo, aunque se declare aquí
pregunta = st.chat_input("ESCRIBA SU PREGUNTA, CIVIL...")

if not st.session_state.mensajes and not pregunta:
    st.markdown(
        '<div class="vacio">SIN NOVEDADES QUE REPORTAR.<br>EN ESPERA DE LAS PREGUNTAS DEL CIVIL.</div>',
        unsafe_allow_html=True,
    )

siguiente_anexo = 1  # numeración de los anexos a lo largo del parte
for i, mensaje in enumerate(st.session_state.mensajes):
    mostrar_etiqueta(mensaje["rol"], mensaje["hora"])
    with st.container(key=f"texto-{mensaje['rol']}-{i}"):
        st.markdown(texto_seguro(mensaje["texto"]))
    if mensaje.get("anexos"):
        siguiente_anexo += mostrar_anexos(mensaje["anexos"], siguiente_anexo, i)

if pregunta:
    hora = datetime.now().strftime("%H:%M")
    n = len(st.session_state.mensajes)
    st.session_state.mensajes.append({"rol": "civil", "texto": pregunta, "hora": hora})
    mostrar_etiqueta("civil", hora)
    with st.container(key=f"texto-civil-{n}"):
        st.markdown(texto_seguro(pregunta))

    mostrar_etiqueta("bala", hora)
    with st.container(key=f"texto-bala-{n + 1}"):
        aviso = st.empty()  # notas del archivo: "procesando", cambios de modelo
        aviso.markdown('<div class="nota">[PROCESANDO DECLARACIÓN...]</div>', unsafe_allow_html=True)
        cuerpo = st.empty()  # aquí se va escribiendo la respuesta

        def nota(texto):
            aviso.markdown(f'<div class="nota">[NOTA DEL ARCHIVO: {html.escape(texto.upper())}]</div>',
                           unsafe_allow_html=True)

        respuesta = ""
        try:
            for pedazo in responder(cliente, st.session_state.prompt,
                                    st.session_state.historial, pregunta, avisar=nota):
                if pedazo is REINICIAR:
                    # El modelo se cortó a media respuesta: se borra y empieza otra vez
                    respuesta = ""
                    cuerpo.empty()
                    continue
                aviso.empty()
                respuesta = mecanografiar(cuerpo, respuesta, pedazo)
            # Quita las marcas [[ANEXO: ...]] y guarda los nombres para mostrar sus escaneos
            respuesta, anexos = separar_anexos(respuesta)
            cuerpo.markdown(texto_seguro(respuesta))
        except Exception as e:
            aviso.empty()
            respuesta = None
            st.error(f"Error al contactar a Gemini: {e}")

    if respuesta:
        st.session_state.mensajes.append({"rol": "bala", "texto": respuesta, "hora": hora, "anexos": anexos})
        mostrar_anexos(anexos, siguiente_anexo, n + 1)


# ------------------------------------------------------------
# Pie del parte: firma y acciones
# ------------------------------------------------------------
st.markdown(
    f'<div class="firma">ASÍ MI REPORTE.<br><br>______________________________<br>{nombre}</div>',
    unsafe_allow_html=True,
)
st.markdown('<hr class="raya">', unsafe_allow_html=True)

col1, col2 = st.columns(2)
if col1.button("[ ARCHIVAR Y ABRIR NUEVA PARTE ]", use_container_width=True):
    iniciar_parte()
    st.rerun()
if col2.button("[ ACTUALIZAR EXPEDIENTES ]", use_container_width=True):
    # Relee el Sheet (personaje y fichas) y empieza un parte nuevo con los datos actualizados
    obtener_personajes.clear()
    obtener_fichas.clear()
    obtener_escaneos.clear()
    obtener_imagen.clear()
    st.session_state.clear()
    st.rerun()
