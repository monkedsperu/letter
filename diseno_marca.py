# -*- coding: utf-8 -*-
"""Diseño 4: el marcapáginas. Una lámina plana y alargada con la letra grande arriba del
todo, el nombre debajo y, si se quiere, un icono suelto alrededor de la letra. La lámina
crece para sostener lo que sobresalga, así que todo se imprime tumbado y sin soportes."""
import re

import trimesh
from shapely import affinity
from shapely.geometry import LineString
from shapely.ops import unary_union

from comun import (GROSOR_MINIMO, HUECO_APARTE, _analizar, adorno_en_grupos, extruir,
                   texto_a_poligono)
from parametros import Parametros

MAX_LETRAS_MARCA = 16
GRUESO_QUE_ABULTA = 3.5   # mm: más que esto molesta al cerrar el libro
GRUESO_QUE_DOBLA = 1.2    # mm: menos que esto se dobla con solo usarlo


def _texto_a_su_alto(texto: str, fuente: str, alto: float, que: str):
    """El texto escalado a `alto` milímetros y centrado en el origen."""
    if alto <= 0:
        raise ValueError(f"El alto de {que} debe ser mayor que 0.")
    g = texto_a_poligono(texto, fuente, 100)
    x0, y0, x1, y1 = g.bounds
    f = alto / (y1 - y0)
    g = affinity.scale(g, f, f, origin=(0, 0))
    x0, y0, x1, y1 = g.bounds
    return affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2)


def _revisar_marca(a: Parametros):
    """Lo que no depende de la geometría. Devuelve el nombre y la letra ya limpios."""
    nombre = (a.mar_texto or "").strip()
    inicial = (a.mar_inicial or "").strip()
    if len(nombre) > MAX_LETRAS_MARCA:
        raise ValueError(f"El nombre admite como máximo {MAX_LETRAS_MARCA} caracteres.")
    if len(inicial) > 2:
        raise ValueError("La letra grande admite una o dos letras.")
    if not nombre and not inicial and not a.mar_adorno:
        raise ValueError("El marcapáginas se queda vacío: ponle al menos la letra grande, "
                         "un nombre o un icono.")
    for c in (a.mar_color_cuerpo, a.mar_color_texto, a.mar_color_inicial, a.mar_color_adorno):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError(f"Color inválido '{c}', usa formato #RRGGBB.")
    if min(a.mar_largo, a.mar_ancho, a.mar_grueso, a.mar_relieve) <= 0:
        raise ValueError("Largo, ancho, grueso y relieve de la lámina deben ser mayores que 0.")
    if a.mar_largo <= a.mar_ancho:
        raise ValueError("La lámina tiene que ser más larga que ancha.")
    espiga = max(a.mar_espiga, 0.0) if a.mar_aparte else 0.0
    holgura = min(max(a.mar_holgura, 0.0), 1.0) if espiga else 0.0
    if espiga and espiga + holgura > a.mar_grueso - GROSOR_MINIMO:
        raise ValueError(f"Un hueco de {espiga + holgura:.1f} mm no cabe en una lámina de "
                         f"{a.mar_grueso:.1f} mm: sube el grueso o baja la hondura del hueco.")
    return nombre, inicial, espiga, holgura


def construir_marca(a: Parametros):
    """Lámina + letra grande + nombre + icono, cada cosa en su color."""
    nombre, inicial, espiga, holgura = _revisar_marca(a)

    # ---- la lámina: una cápsula, con los dos extremos redondeados
    radio = a.mar_ancho / 2
    lamina = LineString([(0, radio), (0, a.mar_largo - radio)]).buffer(radio, quad_segs=32)

    # ---- la letra grande manda: va arriba del todo y el nombre se cuelga de ella
    hueco = max(a.mar_hueco, 0)
    piezas, letra, texto = [], None, None
    if inicial:
        letra = _texto_a_su_alto(inicial, a.mar_fuente_inicial, a.mar_alto_inicial,
                                 "la letra grande")
        letra = affinity.translate(letra, 0, a.mar_largo - a.mar_inicial_y)
        piezas.append(("Inicial", letra, a.mar_color_inicial))
    if nombre:
        texto = _texto_a_su_alto(nombre, a.mar_fuente, a.mar_alto_texto, "el nombre")
        centro = a.mar_largo - max(a.mar_texto_y, 0)
        if letra is not None:      # nunca encima de la letra: si choca, baja lo justo
            centro = min(centro, letra.bounds[1] - hueco - a.mar_alto_texto / 2)
        texto = affinity.translate(texto, 0, centro)
        piezas.append(("Nombre", texto, a.mar_color_texto))

    # ---- el icono, suelto alrededor de la letra grande (o del nombre, si no hay letra)
    if a.mar_adorno:
        if letra is not None:               # manda la letra: el icono orbita a su alrededor
            lx0, ly0, lx1, ly1 = letra.bounds
            cx, cy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
        elif texto is not None:             # sin letra, el hueco que queda sobre el nombre
            cx, cy = 0.0, (texto.bounds[3] + a.mar_largo) / 2
        else:
            cx, cy = 0.0, a.mar_largo - radio
        partes = adorno_en_grupos(
            a.mar_adorno_svg, a.mar_adorno_alto, a.mar_adorno_giro,
            cx + a.mar_adorno_x, cy + a.mar_adorno_y - a.mar_adorno_alto / 2,
            {"cuerpo": a.mar_color_cuerpo, "texto": a.mar_color_texto,
             "inicial": a.mar_color_inicial, "extra": a.mar_color_adorno},
            [a.mar_adorno_c1, a.mar_adorno_c2, a.mar_adorno_c3], a.mar_color_adorno)
        varios = len(partes) > 1
        for i, (color, g) in enumerate(partes, 1):
            piezas.append((f"Icono {i}" if varios else "Icono", g, color))
    else:
        partes = []

    # ---- el cuerpo: la lámina más lo que sobresalga, engordado y fundido en una silueta
    margen = max(a.mar_margen, 0.3)
    cuerpo = unary_union([lamina] + [g.buffer(margen, join_style=1) for _, g, _ in piezas])
    s = min(max(a.mar_suave, 0), radio / 2)     # pasado de suave se comería la lámina
    if s:   # cierre: une lo suelto. apertura: redondea las esquinas de fuera
        cuerpo = cuerpo.buffer(s, join_style=1).buffer(-2 * s, join_style=1) \
                       .buffer(s, join_style=1)
    cuerpo = cuerpo.simplify(0.05)
    if cuerpo.is_empty:
        raise ValueError("El marcapáginas salió vacío. Revisa las medidas.")

    # ---- las alturas. Sueltas, las piezas crecen una espiga hacia dentro de la lámina y
    # la lámina se vacía su silueta con holgura, así al pegarlas caen solas en su sitio
    suelo, techo = a.mar_grueso, a.mar_grueso + a.mar_relieve
    regiones = [("Lamina", cuerpo, 0.0, suelo, a.mar_color_cuerpo)]
    regiones += [(n, g, suelo - espiga, techo, c) for n, g, c in piezas]
    if espiga:
        hondo = espiga + holgura
        bolsa = unary_union([g for _, g, _ in piezas]).buffer(holgura, join_style=1)
        mallas = extruir(cuerpo, suelo - hondo, 0.0) + \
            extruir(cuerpo.difference(bolsa), hondo, suelo - hondo)
    else:
        mallas = extruir(cuerpo, suelo, 0.0)
    niveles = [("Lamina", a.mar_color_cuerpo, trimesh.util.concatenate(mallas))]
    for etiqueta, region, z0, z1, color in regiones[1:]:
        trozos = extruir(region, z1 - z0, z0)
        if trozos:
            niveles.append((etiqueta, color, trimesh.util.concatenate(trozos)))
    if len(niveles) < 2 and not espiga and len(piezas) == 0:
        raise ValueError("No se generó geometría. Revisa los parámetros.")

    if espiga:      # cada pieza al lado de la lámina y apoyada en la mesa, lista de imprimir
        sueltas = [m for n, _, m in niveles if n != "Lamina"]
        dx = cuerpo.bounds[2] + HUECO_APARTE - min(m.bounds[0][0] for m in sueltas)
        dz = -min(m.bounds[0][2] for m in sueltas)
        for m in sueltas:
            m.apply_translation([dx, 0, dz])

    analisis = _analizar(niveles, cuerpo, regiones, len(partes))
    analisis["avisos"].append("Todo es plano: se imprime tumbado, con la cara buena hacia "
                              "arriba y sin soportes.")
    if espiga:
        analisis["avisos"].append(
            f"Cada color sale suelto y al lado de la lámina: imprímelo con su filamento y "
            f"pégalo en su hueco ({espiga:.1f} mm de hondura y {holgura:.1f} mm de holgura).")
    if a.mar_grueso > GRUESO_QUE_ABULTA:
        analisis["avisos"].append(f"{a.mar_grueso:.1f} mm de lámina abultan al cerrar el "
                                  "libro: con 2 o 3 mm va de sobra.")
    if a.mar_grueso < GRUESO_QUE_DOBLA:
        analisis["avisos"].append(f"{a.mar_grueso:.1f} mm es muy poco: la lámina se doblará "
                                  "con el uso.")
    return niveles, analisis
