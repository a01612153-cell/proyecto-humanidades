# Habla la bala

Chatbot que da voz a una bala disparada en Tlatelolco el 2 de octubre de 1968.

## Cómo correrlo

1. Instala las dependencias: `python -m pip install -r requirements.txt`
2. Crea un archivo `.env` con `GEMINI_API_KEY`, `NOMBRE_HOJA`, `RUTA_CREDENCIALES` y `CARPETA_ESCANEOS`,
   y coloca el archivo de credenciales de Google. Ninguno se sube a GitHub.
3. Ejecuta `python servidor.py` y abre http://127.0.0.1:8510

## Estructura

- `Humanidades.py`: Google Sheets, Drive, prompt y Gemini.
- `servidor.py`: servidor web.
- `web/`: interfaz. Fuentes Anton y Courier Prime, con licencia SIL Open Font License.
- `fuentes/`: documentos originales (solo local).
- `pruebas/`: `python -m unittest discover pruebas`
