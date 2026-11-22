#!/usr/bin/env python3
"""Minifica pantalla.html (CSS + JS en una sola línea ilegible).  Uso: python minify_html.py entrada salida"""
import re
import sys

import rcssmin
import rjsmin


def minificar(html: str) -> str:
    html = re.sub(r"<style>(.*?)</style>",
                  lambda m: "<style>" + rcssmin.cssmin(m.group(1)) + "</style>", html, flags=re.S)
    html = re.sub(r'(<script type="module">)(.*?)(</script>)',
                  lambda m: m.group(1) + rjsmin.jsmin(m.group(2)) + m.group(3), html, flags=re.S)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)       # comentarios HTML
    html = re.sub(r">\s+<", "><", html)                       # espacios entre etiquetas
    return html.strip()


if __name__ == "__main__":
    entrada, salida = sys.argv[1], sys.argv[2]
    with open(entrada, encoding="utf-8") as f:
        out = minificar(f.read())
    with open(salida, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"Minificado {entrada} -> {salida}")
