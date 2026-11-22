#!/usr/bin/env python3
"""Monkeds Letter: pantalla web local para personalizar y descargar el 3MF.  Uso:  python servidor_web.py"""
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from generador_stl import (AQUI, CARPETA_PATRONES, Parametros, adornos_disponibles, construir, patrones_disponibles,
                           exportar_3mf, fuentes_instaladas, parametros_desde_dict, svg_a_poligono)
from dataclasses import asdict

PUERTO = 8000
MAX_SVG = 2_000_000  # bytes
WEB = os.path.join(AQUI, "web")  # three.js local: funciona sin internet


class Servidor(ThreadingHTTPServer):
    # En Windows SO_REUSEADDR deja abrir un puerto ya ocupado (otra copia de la app respondería).
    allow_reuse_address = False


class Manejador(BaseHTTPRequestHandler):
    def _enviar(self, codigo, tipo, datos: bytes, extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(AQUI, "pantalla.html"), "rb") as f:
                self._enviar(200, "text/html; charset=utf-8", f.read())
        elif self.path.startswith("/web/"):
            ruta = os.path.normpath(os.path.join(WEB, self.path[5:].split("?")[0]))
            if not ruta.startswith(WEB + os.sep) or not os.path.isfile(ruta):  # nada fuera de "web"
                return self._enviar(404, "text/plain", b"No encontrado")
            with open(ruta, "rb") as f:
                self._enviar(200, "text/javascript; charset=utf-8", f.read())
        elif self.path == "/api/config":
            datos = {"defaults": asdict(Parametros()), "fuentes": fuentes_instaladas(),
                     "patrones": patrones_disponibles(), "adornos": adornos_disponibles()}
            self._enviar(200, "application/json", json.dumps(datos).encode())
        else:
            self._enviar(404, "text/plain", b"No encontrado")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if self.path == "/api/3mf":
                params = parametros_desde_dict(json.loads(self.rfile.read(n) or b"{}"))
                self._enviar(200, "model/3mf", exportar_3mf(construir(params)))
            elif self.path == "/api/patron":
                nombre = self._guardar_svg(n)
                datos = {"nombre": nombre, "patrones": patrones_disponibles()}
                self._enviar(200, "application/json", json.dumps(datos).encode())
            else:
                self._enviar(404, "text/plain", b"No encontrado")
        except Exception as e:  # se devuelve el mensaje a la pantalla
            self._enviar(400, "application/json", json.dumps({"error": str(e)}).encode())

    def _guardar_svg(self, n):
        """Guarda un SVG subido en la carpeta patrones (solo si se puede usar)."""
        if n > MAX_SVG:
            raise ValueError("El SVG es demasiado grande (máx. 2 MB).")
        d = json.loads(self.rfile.read(n) or b"{}")
        base = os.path.splitext(os.path.basename(str(d.get("nombre", "patron"))))[0]
        nombre = (re.sub(r"[^\w\-]", "_", base)[:60] or "patron") + ".svg"
        os.makedirs(CARPETA_PATRONES, exist_ok=True)
        ruta = os.path.join(CARPETA_PATRONES, nombre)
        tmp = ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(d.get("svg", "")))
        try:
            svg_a_poligono(tmp)  # valida antes de dejarlo en la biblioteca
        except Exception as e:
            os.remove(tmp)
            raise ValueError(f"SVG no válido: {e}".replace(".svg.tmp", ".svg"))
        os.replace(tmp, ruta)
        return nombre

    def log_message(self, *args):
        pass


def main():
    for puerto in range(PUERTO, PUERTO + 20):  # si el 8000 está ocupado, prueba el siguiente
        try:
            srv = Servidor(("127.0.0.1", puerto), Manejador)
            break
        except OSError:
            continue
    else:
        raise SystemExit("No encontré un puerto libre entre 8000 y 8019.")
    url = f"http://127.0.0.1:{puerto}"
    print(f"Monkeds Letter: abriendo {url}")
    print("Deja esta ventana abierta mientras lo usas. Ciérrala (o Ctrl+C) para salir.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
