import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import servidor as s  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class Pruebas(unittest.TestCase):
    def setUp(self):
        s._archivo = None
        s._conversaciones.clear()
        reemplazos = {
            "validar_configuracion": lambda: None,
            "cargar_personajes": lambda _: [{"nombre": "La bala", "epoca": "SECRETO"}],
            "cargar_fichas": lambda _: [{"nombre": "Ana Díaz", "rol": "x"}, {"nombre": "Luis"}],
            "listar_escaneos": lambda: {"ana diaz": "idsecreto", "ana diaz - retrato 1": "idsecreto2", "mapa": "idsecreto3"},
            "cargar_lugares": lambda _: [{"nombre": "Plaza", "coordenadas": "19.4, -99.1", "dudas": "una"},
                                         {"nombre": "Otro", "coordenadas": "x"}],
            "cargar_imagenes": lambda _: [
                {"archivo": "Ana Díaz.png", "persona": "Ana Díaz", "tipo": "ficha"},
                {"archivo": "Ana Díaz - retrato 1.png", "persona": "Ana Diaz", "tipo": "retrato"},
                {"archivo": "Mapa.png", "persona": "Ana Díaz", "tipo": "mapa"},
                {"archivo": "No existe.png", "persona": "Luis"}],
            "crear_cliente_gemini": lambda _: None,
            "descargar_de_drive": lambda _: b"\xff\xd8\xff123",
        }
        for nombre, f in reemplazos.items():
            p = patch.object(s.h, nombre, f)
            p.start()
            self.addCleanup(p.stop)
        self.c = TestClient(s.app)

    def preguntar(self, responder):
        clave = self.c.post("/api/conversacion").json()["id"]
        with patch.object(s.h, "responder", responder):
            r = self.c.post("/api/mensaje", json={"conversacion": clave, "texto": "hola"})
        return clave, [json.loads(x) for x in r.text.splitlines()]

    def test_marca_partida_y_aviso(self):
        def falso(*a, avisar):
            avisar("espera")
            yield from ["Reporto [", "[ANE", "XO: ana diaz]", "]\nfin [", "[ANEXO: Nadie]]"]
        _, ev = self.preguntar(falso)
        self.assertEqual(ev[0], {"tipo": "aviso", "texto": "espera"})
        texto = "".join(e["texto"] for e in ev if e["tipo"] == "texto")
        self.assertNotIn("[", texto)
        self.assertEqual(ev[-1]["tipo"], "fin")
        self.assertIn("fin", ev[-1]["texto"])
        self.assertEqual([f["nombre"] for f in ev[-2]["fichas"]], ["Ana Díaz"])

    def test_reinicio(self):
        def falso(*a, avisar):
            yield "malo"
            yield s.h.REINICIAR
            yield "bueno"
        _, ev = self.preguntar(falso)
        self.assertEqual([e["tipo"] for e in ev], ["texto", "reiniciar", "texto", "anexos", "fin"])
        self.assertEqual(ev[-1]["texto"], "bueno")

    def test_error_libera_y_no_filtra(self):
        def falso(*a, avisar):
            raise ValueError("clave-privada")
            yield
        clave, ev = self.preguntar(falso)
        self.assertEqual(ev[-1]["tipo"], "error")
        self.assertNotIn("clave-privada", str(ev))
        self.assertFalse(s._conversaciones[clave].ocupada.locked())

    def test_memoria_separada(self):
        def falso(cliente, prompt, historial, mensaje, avisar):
            historial.append(mensaje)
            yield "ok"
        a, _ = self.preguntar(falso)
        b = self.c.post("/api/conversacion").json()["id"]
        self.assertEqual(s._conversaciones[a].historial, ["hola"])
        self.assertEqual(s._conversaciones[b].historial, [])

    def test_ocupada_inexistente_y_limites(self):
        clave = self.c.post("/api/conversacion").json()["id"]
        s._conversaciones[clave].ocupada.acquire()
        enviar = lambda i, t: self.c.post("/api/mensaje", json={"conversacion": i, "texto": t}).status_code
        self.assertEqual(enviar(clave, "x"), 409)
        self.assertEqual(enviar("no", "x"), 404)
        self.assertEqual(enviar(clave, "  "), 422)
        self.assertEqual(enviar(clave, "x" * 4001), 422)

    def test_imagenes_y_privacidad(self):
        r = self.c.get("/api/parte")
        self.assertNotIn("SECRETO", r.text)
        self.assertNotIn("idsecreto", r.text)
        imagenes = r.json()["fichas"][0]["imagenes"]
        self.assertEqual([i["tipo"] for i in imagenes], ["ficha", "retrato"])
        self.assertEqual(r.json()["fichas"][1]["imagenes"], [])
        self.assertEqual([x["coordenadas"] for x in r.json()["lugares"]], [[19.4, -99.1], None])
        ruta = imagenes[1]["url"]
        self.assertEqual(self.c.get(ruta).headers["content-type"], "image/jpeg")
        v = ruta.split("=")[1]
        self.assertEqual(self.c.get(f"/api/fichas/1/imagenes/0?v={v}").status_code, 404)
        self.assertEqual(self.c.get(f"/api/fichas/0/imagenes/-1?v={v}").status_code, 404)
        self.assertEqual(self.c.get("/api/fichas/0/imagenes/0?v=vieja").status_code, 410)
        for ruta in ("/.env", "/web/../.env", "/web/%2e%2e/.env", "/credenciales.json"):
            self.assertEqual(self.c.get(ruta).status_code, 404)

    def test_configuracion_y_fallo_al_actualizar(self):
        self.c.get("/api/parte")
        def falla():
            raise SystemExit("Faltan variables")
        with patch.object(s.h, "validar_configuracion", falla):
            r = self.c.post("/api/actualizar")
        self.assertEqual((r.status_code, r.json()["detail"]), (503, "Faltan variables"))
        self.assertEqual(self.c.get("/api/parte").status_code, 200)

    def test_prompt(self):
        prompt = s.obtener_archivo().prompt
        self.assertIn("### Lugar: Plaza", prompt)
        self.assertNotIn("19.4", prompt)
        self.assertIn("no consta qué bala fue", prompt)

    def test_modelo_colgado_pasa_al_siguiente(self):
        usados, avisos = [], []

        class Modelos:
            def generate_content_stream(self, model, **_):
                usados.append(model)
                if len(usados) == 1:
                    raise s.h.httpx.ReadTimeout("lento")
                return iter([SimpleNamespace(text="hola")])
        cliente = SimpleNamespace(models=Modelos())
        self.assertEqual(list(s.h.responder(cliente, "p", [], "x", avisar=avisos.append)), ["hola"])
        self.assertEqual(len(usados), 2)
        self.assertIn("sin respuesta", avisos[0])

    def test_cancelar(self):
        conv = s.Conversacion(s.obtener_archivo())
        conv.ocupada.acquire()
        cola, cancelar = s.queue.Queue(), threading.Event()
        cancelar.set()
        def falso(*a, avisar):
            avisar("x")
            yield "nunca"
        with patch.object(s.h, "responder", falso):
            s.generar(conv, "x", cola, cancelar)
        self.assertIsNone(cola.get())
        self.assertFalse(conv.ocupada.locked())


if __name__ == "__main__":
    unittest.main()
