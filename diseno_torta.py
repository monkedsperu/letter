# -*- coding: utf-8 -*-
"""Diseño 5: el topper de tarta. El nombre en grande, una palabra que lo acompaña arriba o
abajo, un número aún más grande a la derecha y hasta tres adornos. Todo cae sobre una placa
que sale de engordar las letras, y de ella baja el palo que se clava en la tarta."""
import re

import trimesh
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from comun import (GROSOR_MINIMO, _analizar, _poligonos, adorno_en_grupos, apartar_por_color,
                   extruir, texto_a_poligono)
from parametros import Parametros

MAX_LETRAS_TORTA = 20
ADORNOS_TORTA = 3        # cuántos adornos admite el topper


def _texto(texto: str, fuente: str, alto: float, que: str):
    """El texto a su altura, con el pie en y = 0 y centrado en x = 0."""
    if alto <= 0:
        raise ValueError(f"El alto de {que} debe ser mayor que 0.")
    g = texto_a_poligono(texto, fuente, 100)
    x0, y0, x1, y1 = g.bounds
    f = alto / (y1 - y0)
    g = affinity.scale(g, f, f, origin=(0, 0))
    x0, y0, x1, y1 = g.bounds
    return affinity.translate(g, -(x0 + x1) / 2, -y0)


def _revisar_torta(a: Parametros):
    """Lo que no depende de la geometría. Devuelve los tres textos ya limpios."""
    piezas = {}
    for campo, valor in (("nombre", a.tor_nombre), ("palabra", a.tor_palabra),
                         ("numero", a.tor_numero)):
        texto = (valor or "").strip()
        if len(texto) > MAX_LETRAS_TORTA:
            raise ValueError(f"'{texto[:12]}…' es demasiado largo para el topper.")
        piezas[campo] = texto
    if not any(piezas.values()) and not any(getattr(a, f"tor_ad{i}")
                                            for i in range(1, ADORNOS_TORTA + 1)):
        raise ValueError("El topper se queda vacío: ponle al menos un nombre, un número, "
                         "una palabra o un adorno.")
    for c in (a.tor_color_base, a.tor_color_letras, a.tor_color_extra):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError(f"Color inválido '{c}', usa formato #RRGGBB.")
    if min(a.tor_grueso, a.tor_relieve) <= 0:
        raise ValueError("El grosor de la placa y el relieve deben ser mayores que 0.")
    if a.tor_borde < 0:
        raise ValueError("El borde no puede ser negativo.")
    espiga = max(a.tor_espiga, 0.0) if a.tor_aparte else 0.0
    holgura = min(max(a.tor_holgura, 0.0), 1.0) if espiga else 0.0
    if espiga and espiga + holgura > a.tor_grueso - GROSOR_MINIMO:
        raise ValueError(f"Un hueco de {espiga + holgura:.1f} mm no cabe en una placa de "
                         f"{a.tor_grueso:.1f} mm: sube el grosor o baja la hondura del hueco.")
    return piezas, espiga, holgura


def _adornos_del_topper(a: Parametros, caja):
    """[(nombre, polígono, color)] de los adornos encendidos, colocados respecto al centro
    del bloque de texto. Cada adorno elige su color igual que en los demás diseños."""
    x0, y0, x1, y1 = caja
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    paleta = {"base": a.tor_color_base, "letras": a.tor_color_letras,
              "extra": a.tor_color_extra}
    puestos = []
    for i in range(1, ADORNOS_TORTA + 1):
        if not getattr(a, f"tor_ad{i}"):
            continue
        alto = getattr(a, f"tor_ad{i}_alto")
        sitio = getattr(a, f"tor_ad{i}_color")
        partes = adorno_en_grupos(
            getattr(a, f"tor_ad{i}_svg"), alto, getattr(a, f"tor_ad{i}_giro"),
            cx + getattr(a, f"tor_ad{i}_x"),
            cy + getattr(a, f"tor_ad{i}_y") - alto / 2,
            paleta, [sitio] * 3, a.tor_color_extra, ("extra",) * 3,
            (getattr(a, f"tor_ad{i}_tinta"),) * 3)
        varios = len(partes) > 1
        for j, (color, g) in enumerate(partes, 1):
            puestos.append((f"Adorno {i}" + (f".{j}" if varios else ""), g, color))
    return puestos


def construir_torta(a: Parametros):
    """Placa + nombre + palabra + número + adornos, y el palo para clavarlo en la tarta."""
    textos, espiga, holgura = _revisar_torta(a)
    hueco = max(a.tor_hueco, 0)

    # ---- el bloque de texto: el nombre manda, la palabra va encima o debajo y el número
    # a la derecha. Cada uno es su propia pieza, así que se arrastra por separado
    textuales = []
    nombre = _texto(textos["nombre"], a.tor_fuente, a.tor_alto_nombre, "el nombre") \
        if textos["nombre"] else Polygon()
    if not nombre.is_empty:
        textuales.append(("Nombre", nombre))
    if textos["palabra"]:
        palabra = _texto(textos["palabra"], a.tor_fuente, a.tor_alto_palabra, "la palabra")
        if not nombre.is_empty:
            dy = (nombre.bounds[3] + hueco - palabra.bounds[1]) if a.tor_palabra_arriba \
                else (nombre.bounds[1] - hueco - palabra.bounds[3])
            palabra = affinity.translate(palabra, 0, dy)
        textuales.append(("Palabra", palabra))
    if textos["numero"]:
        numero = _texto(textos["numero"], a.tor_fuente, a.tor_alto_numero, "el número")
        juntos = unary_union([g for _, g in textuales]) if textuales else Polygon()
        if not juntos.is_empty:    # a la derecha de todo y centrado con lo que haya
            bx0, by0, bx1, by1 = juntos.bounds
            nx0, ny0, nx1, ny1 = numero.bounds
            numero = affinity.translate(numero, bx1 + hueco - nx0,
                                        (by0 + by1) / 2 - (ny0 + ny1) / 2)
        textuales.append(("Numero", numero))
    # y encima, lo que el usuario haya arrastrado de cada texto. Se aplica al final para
    # que mover el nombre no empuje al número: cada pieza va por su cuenta
    movido = {"Nombre": (a.tor_nombre_x, a.tor_nombre_y),
              "Palabra": (a.tor_palabra_x, a.tor_palabra_y),
              "Numero": (a.tor_numero_x, a.tor_numero_y)}
    textuales = [(n, affinity.translate(g, *movido[n])) for n, g in textuales]
    bloque = unary_union([g for _, g in textuales]) if textuales else Polygon()
    if bloque.is_empty and not any(getattr(a, f"tor_ad{i}") for i in range(1, ADORNOS_TORTA + 1)):
        raise ValueError("El topper se queda vacío: ponle al menos un nombre, un número, "
                         "una palabra o un adorno.")

    adornos = _adornos_del_topper(a, bloque.bounds if not bloque.is_empty
                                  else (0.0, 0.0, 0.0, 0.0))
    todo = unary_union([bloque] + [g for _, g, _ in adornos])

    # ---- la placa: todo engordado y fundido, que es lo que mantiene unidas las letras
    borde = max(a.tor_borde, 0.0)
    placa = todo.buffer(borde, join_style=1) if borde else todo
    s = max(a.tor_suave, 0)
    if s:
        placa = placa.buffer(s, join_style=1).buffer(-2 * s, join_style=1) \
                     .buffer(s, join_style=1)
    placa = placa.simplify(0.05)

    # ---- el palo (o los dos) que se clava en la tarta, con la punta en pico
    if a.tor_palo and a.tor_palo_largo > 0 and a.tor_palo_ancho > 0:
        px0, py0, px1, _ = placa.bounds
        medio = a.tor_palo_ancho / 2
        sitios = ([(px0 + px1) / 2 + a.tor_palo_x] if a.tor_palos < 2 else
                  [(px0 + px1) / 2 + a.tor_palo_x + d
                   for d in (-(px1 - px0) / 4, (px1 - px0) / 4)])
        palos, sueltos = [], 0
        for x in sitios:
            # el palo arranca donde la placa termina JUSTO encima de él, no en el punto más
            # bajo de toda la placa: si no, nace en el aire y sale una pieza suelta
            franja = placa.intersection(box(x - medio, -1e4, x + medio, 1e4))
            if franja.is_empty:
                sueltos += 1
                continue
            # sube hasta media placa: así queda metido dentro y no colgando de un
            # pico. Es del mismo color que ella, así que no se ve
            arriba = (franja.bounds[1] + franja.bounds[3]) / 2
            pie = franja.bounds[1] - a.tor_palo_largo
            palos.append(Polygon([(x - medio, arriba), (x + medio, arriba),
                                  (x + medio, pie + medio), (x, pie),
                                  (x - medio, pie + medio)]))
        if sueltos:
            raise ValueError("El palo cae fuera del topper: muévelo hacia el centro.")
        placa = unary_union([placa] + palos)

    if placa.is_empty:
        raise ValueError("El topper salió vacío. Revisa las medidas.")

    # ---- las alturas: la placa abajo y las letras encima. Sueltas, cada pieza crece su
    # espiga hacia dentro y la placa se vacía su silueta con holgura
    suelo, techo = a.tor_grueso, a.tor_grueso + a.tor_relieve
    relieve = [(n, g, a.tor_color_letras) for n, g in textuales] + adornos
    relieve = [(n, g, c) for n, g, c in relieve if not g.is_empty]
    if espiga:
        hondo = espiga + holgura
        bolsa = unary_union([g for _, g, _ in relieve]).buffer(holgura, join_style=1)
        mallas = extruir(placa, suelo - hondo, 0.0) + \
            extruir(placa.difference(bolsa), hondo, suelo - hondo)
    else:
        mallas = extruir(placa, suelo, 0.0)

    niveles = [("Placa", a.tor_color_base, trimesh.util.concatenate(mallas))]
    for etiqueta, region, color in relieve:
        trozos = extruir(region, techo - suelo + espiga, suelo - espiga)
        if trozos:
            niveles.append((etiqueta, color, trimesh.util.concatenate(trozos)))

    if espiga:
        apartar_por_color([p for p in niveles if p[0] != "Placa"], placa.bounds[2])

    regiones = [("Placa", placa, 0.0, suelo, a.tor_color_base)]
    regiones += [(n, g, suelo - espiga, techo, c) for n, g, c in relieve]
    analisis = _analizar(niveles, placa, regiones,
                         [c for _, _, c in adornos])
    analisis["ancho_base"] = round(bloque.bounds[2] - bloque.bounds[0], 2)
    analisis["avisos"].append("Todo es plano: se imprime tumbado, con la cara buena hacia "
                              "arriba y sin soportes.")
    sueltas = len(_poligonos(placa))
    if sueltas > 1:
        analisis["avisos"].append(f"El topper son {sueltas} trozos sueltos: sube el borde o "
                                  "el suavizado para que quede de una pieza.")
    if espiga:
        analisis["avisos"].append(
            f"Cada color sale suelto y al lado de la placa: imprímelo con su filamento y "
            f"pégalo en su hueco ({espiga:.1f} mm de hondura y {holgura:.1f} mm de holgura).")
    if a.tor_palo and a.tor_palo_largo < 40:
        analisis["avisos"].append("Un palo de menos de 4 cm se queda corto para una tarta "
                                  "alta: el topper puede volcarse.")
    return niveles, analisis
