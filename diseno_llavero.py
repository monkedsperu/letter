# -*- coding: utf-8 -*-
"""Diseño 1: el llavero. Letra inicial con borde y texto en tres niveles de relieve.

    nivel 1 (0 -> alto 1): base completa; se ve como el borde de la letra y el borde 1 del texto
    nivel 2 (alto 1 -> alto 2): la letra + borde 2 del texto (el adorno va aquí con su color)
    nivel 3 (alto 2 -> alto 3): el texto y el patrón
"""
import math
import re

import trimesh
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, unary_union

from comun import (CARPETA_ADORNOS, GROSOR_MINIMO, _analizar, apartar_por_color,
                   capas_con_chaflan,
                   color_de_la_forma,
                   extruir, grupos_adorno, repartir_patron, svg_dentro_de,
                   texto_a_poligono, texto_en_lineas)
from parametros import MAX_LETRAS, Parametros

def colocar_adorno(a: Parametros, cx: float, cy: float):
    """Devuelve (partes, partes_del_segundo), cada una [(color, polígono)] ya colocada.
    El segundo es la forma reflejada (ej. el cuerno derecho)."""
    nombre = a.adorno
    ruta = svg_dentro_de(CARPETA_ADORNOS, nombre)
    if not ruta:
        raise ValueError(f"No encontré el adorno '{nombre}' en {CARPETA_ADORNOS}")
    if a.tam_adorno <= 0:
        raise ValueError("El tamaño del adorno debe ser mayor que 0.")
    # Del SVG se aprovechan las formas; el color lo pone el dibujo o la paleta del llavero
    grupos = grupos_adorno(ruta, mm_alto=a.tam_adorno)
    destinos = [a.adorno_c1, a.adorno_c2, a.adorno_c3]
    paleta = {"base": a.color_nivel1, "letra": a.color_nivel2,
              "texto": a.color_nivel3, "extra": a.color_adorno}
    porcolor = {}
    for i, (_, g) in enumerate(grupos):
        color = color_de_la_forma(i, grupos, destinos, paleta, a.color_adorno,
                                  ("extra", "base", "texto"),
                                  (a.adorno_tinta1, a.adorno_tinta2, a.adorno_tinta3))
        porcolor[color] = porcolor[color].union(g) if color in porcolor else g
    partes = list(porcolor.items())

    entero = unary_union([g for _, g in partes])
    minx, miny, maxx, maxy = entero.bounds
    f = a.tam_adorno / max(maxx - minx, maxy - miny)

    def encuadrar(g, espejo=False):
        g = affinity.translate(g, -(minx + maxx) / 2, -(miny + maxy) / 2)
        g = affinity.scale(g, -f if espejo else f, f, origin=(0, 0))
        return g

    def poner(lista, x, y, giro, espejo=False):
        return [(c, affinity.translate(affinity.rotate(encuadrar(g, espejo), giro, origin=(0, 0)),
                                       cx + x, cy + y)) for c, g in lista]

    modo = a.segundo_adorno
    if modo == "espejo":
        segundo = poner(partes, -a.adorno_x, a.adorno_y, -a.giro_adorno, espejo=True)
    elif modo == "libre":
        segundo = poner(partes, a.adorno2_x, a.adorno2_y, a.giro_adorno2, espejo=True)
    elif modo == "ninguno":
        segundo = []
    else:
        raise ValueError("segundo_adorno debe ser: espejo, libre o ninguno")
    return poner(partes, a.adorno_x, a.adorno_y, a.giro_adorno), segundo


def aro_llavero(a: Parametros, cx: float, cy: float, cuerpo):
    """(anillo, agujero) del aro de llavero, o vacíos si está desactivado. Va en el nivel 1,
    así que tiene su mismo grosor, y el agujero atraviesa la pieza. Si el aro queda separado
    del cuerpo se le añade un cuello que los une: si no, saldría una rosquilla suelta."""
    if not a.aro:
        return Polygon(), Polygon()
    if a.aro_diametro <= 0:
        raise ValueError("El diámetro del aro debe ser mayor que 0.")
    if a.aro_agujero <= 0 or a.aro_agujero >= a.aro_diametro:
        raise ValueError("El agujero del aro debe ser mayor que 0 y menor que su diámetro.")
    pared = (a.aro_diametro - a.aro_agujero) / 2
    centro = Point(cx + a.aro_x, cy + a.aro_y)
    agujero = centro.buffer(a.aro_agujero / 2, 64)
    anillo = centro.buffer(a.aro_diametro / 2, 64).difference(agujero)
    if not cuerpo.is_empty and not anillo.intersects(cuerpo):
        p1, p2 = nearest_points(anillo, cuerpo)
        # se alarga un poco por los dos extremos: si solo tocara, shapely dejaría dos piezas
        dx, dy = p2.x - p1.x, p2.y - p1.y
        largo = math.hypot(dx, dy) or 1.0
        ux, uy = dx / largo * 0.6, dy / largo * 0.6
        cuello = LineString([(p1.x - ux, p1.y - uy), (p2.x + ux, p2.y + uy)])
        anillo = anillo.union(cuello.buffer(max(pared, 3.0) / 2, cap_style=2)).difference(agujero)
    return anillo, agujero


def hueco_iman(a: Parametros, cx: float, cy: float):
    """Círculo del bolsillo del imán, o vacío. Se resta solo al tramo de abajo del nivel 1."""
    if not a.iman:
        return Polygon()
    if a.iman_diametro <= 0:
        raise ValueError("El diámetro del imán debe ser mayor que 0.")
    if not 0 < a.iman_hondo < a.alto_nivel1:
        raise ValueError(f"La profundidad del imán debe estar entre 0 y {a.alto_nivel1} mm "
                         "(el grosor del nivel 1).")
    return Point(cx + a.iman_x, cy + a.iman_y).buffer(a.iman_diametro / 2, 64)


def _rebanar(tramos, altura: float, recorte, arriba: bool):
    """Parte los tramos [(región, za, zb)] a esa altura y le quita `recorte` a los de
    arriba (o a los de abajo, si arriba=False). Sirve lo mismo para el bolsillo del imán
    que para el hueco donde encaja la pieza de encima."""
    fuera = []
    for region, za, zb in tramos:
        for a0, b0 in ((za, min(zb, altura)), (max(za, altura), zb)):
            if b0 - a0 > 1e-4:
                toca = (a0 >= altura - 1e-9) == arriba
                fuera.append((region.difference(recorte) if toca else region, a0, b0))
    return fuera


def _construir_llavero(a: Parametros):
    """Llavero o cartel: la letra inicial con su borde más el texto, en tres niveles."""
    if not a.inicial.strip():
        raise ValueError("Falta la letra inicial.")
    if len(a.inicial.strip()) > MAX_LETRAS:
        raise ValueError(f"La letra grande admite como máximo {MAX_LETRAS} caracteres.")
    for c in (a.color_nivel1, a.color_nivel2, a.color_nivel3, a.color_adorno):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError(f"Color inválido '{c}', usa formato #RRGGBB.")
    if not 0 < a.alto_nivel1 < a.alto_nivel2 < a.alto_nivel3:
        raise ValueError("Las alturas deben cumplir: 0 < nivel 1 < nivel 2 < nivel 3.")
    if a.tam_inicial <= 0:
        raise ValueError("La altura de la letra debe ser mayor que 0.")
    if a.texto.strip() and a.tam_texto <= 0:
        raise ValueError("El tamaño del texto debe ser mayor que 0.")
    espiga = max(a.espiga, 0.0) if a.aparte else 0.0
    holgura = min(max(a.holgura, 0.0), 1.0) if espiga else 0.0
    if espiga:
        capa = min(a.alto_nivel1, a.alto_nivel2 - a.alto_nivel1)
        if espiga + holgura > capa - GROSOR_MINIMO:
            raise ValueError(f"Un hueco de {espiga + holgura:.1f} mm no cabe en una capa de "
                             f"{capa:.1f} mm: sube las alturas o baja la hondura del hueco.")
        if a.iman and a.iman_hondo + espiga + holgura > a.alto_nivel1 - GROSOR_MINIMO:
            raise ValueError("El hueco del imán y el de encaje no caben los dos en el "
                             "nivel 1: sube su altura o baja una de las dos honduras.")

    # Letra inicial escalada para que su ALTURA sea exactamente tam_inicial
    letra = texto_a_poligono(a.inicial.strip(), a.fuente_inicial, 100)
    minx, miny, maxx, maxy = letra.bounds
    f = a.tam_inicial / (maxy - miny)
    letra = affinity.scale(letra, f, f, origin=(0, 0))
    minx, miny, _, _ = letra.bounds
    letra = affinity.translate(letra, -minx, -miny)
    minx, miny, maxx, maxy = letra.bounds
    # Adorno (y el segundo): forma parte de la silueta, así que el borde de nivel 1 lo rodea también.
    partes1 = partes2 = []
    if a.adorno:
        partes1, partes2 = colocar_adorno(a, (minx + maxx) / 2, (miny + maxy) / 2)
    h = unary_union([g for _, g in partes1 + partes2]) if (partes1 or partes2) else Polygon()
    if a.adorno_detras:
        # el adorno pasa por detrás: manda la letra y es ella la que lo corta
        base = letra
        recorte_adorno = letra.buffer(a.borde, join_style=1) if (a.cortar_adorno and a.borde > 0) else letra
    else:
        # por delante (lo de siempre): el adorno tapa la letra
        hb = h.buffer(a.borde, join_style=1) if a.borde > 0 else h
        base = letra.difference(hb if a.cortar_adorno else h)
        recorte_adorno = Polygon()
    silueta = letra.union(h)
    contorno = silueta.buffer(a.borde, join_style=1) if a.borde > 0 else silueta
    cminx, cminy, cmaxx, cmaxy = contorno.bounds

    # Texto + sus dos bordes. t2 = texto con borde interior, t1 = huella completa.
    t = t1 = t2 = Polygon()
    if a.texto.strip():
        t = texto_en_lineas(a.texto, a.fuente_texto, a.tam_texto, a.curva_texto)
        if a.giro_texto:
            t = affinity.rotate(t, a.giro_texto, origin="center")
        t2 = t.buffer(a.borde_texto2, join_style=1) if a.borde_texto2 > 0 else t
        t1 = t2.buffer(a.borde_texto1, join_style=1) if a.borde_texto1 > 0 else t2
        tminx, tminy, tmaxx, tmaxy = t1.bounds

        if a.posicion == "sobre":
            dx = (minx + maxx) / 2 - (tminx + tmaxx) / 2
            dy = (miny + maxy) / 2 - (tminy + tmaxy) / 2
        elif a.posicion == "arriba":
            dx = (cminx + cmaxx) / 2 - (tminx + tmaxx) / 2
            dy = cmaxy + a.separacion - tminy
        elif a.posicion == "derecha":
            dx = cmaxx + a.separacion - tminx
            dy = (miny + maxy) / 2 - (tminy + tmaxy) / 2
        else:
            raise ValueError("posicion debe ser: sobre, arriba o derecha")
        dx += a.texto_x   # ajuste fino: el texto también se arrastra en la vista 3D
        dy += a.texto_y
        t, t1, t2 = (affinity.translate(g, dx, dy) for g in (t, t1, t2))

    # Regiones disjuntas. Orden de pintado: letra -> adorno -> texto (el texto siempre manda).
    # cortar_letra: el texto con sus bordes tapa letra y adorno (el borde 1 los corta).
    # Si no, el borde 2 del texto se fusiona con la letra y el borde 1 solo se ve por fuera.
    tapa = t1 if a.cortar_letra else t2
    deco = Polygon()           # motivos del patrón (pieza aparte del texto)
    n2 = base.difference(tapa).union(t2.difference(t))
    # Patrón: solo sobre la parte de la letra en nivel 2, lejos del texto, del adorno y del borde.
    if a.patron:
        m = max(a.margen_patron, 0)
        zona = base.buffer(-m) if m else base
        zona = zona.difference(t1.buffer(m) if m else t1)
        deco = repartir_patron(zona, a.patron, a.tam_patron, a.separacion_patron,
                               a.semilla, a.girar_patron)
        n2 = n2.difference(deco)
    # Capas apiladas y macizas: lo que se ve arriba en 2D define qué tan alta es cada zona;
    # debajo de cada zona están completas las capas inferiores (nada llega a la base salvo el nivel 1).
    h1, h2, h3 = a.alto_nivel1, a.alto_nivel2, a.alto_nivel3
    centro = ((minx + maxx) / 2, (miny + maxy) / 2)
    arriba = t.union(deco)
    cuerpo = unary_union([contorno, t1, n2, h.difference(tapa), arriba])
    anillo, agujero = aro_llavero(a, *centro, cuerpo)
    todo = cuerpo.union(anillo)
    nivel1 = todo.difference(anillo)
    regiones = [("Nivel 1", nivel1, 0.0, h1, a.color_nivel1),
                ("Nivel 2", n2.union(arriba), h1, h2, a.color_nivel2),
                ("Aro", anillo, 0.0, h1, a.color_nivel1),
                ("Patron", deco, h2, h3, a.color_nivel3),
                ("Texto", t, h2, h3, a.color_nivel3)]
    # Los adornos van aparte (la pantalla los arrastra) y con un trozo por color del SVG.
    for etiqueta, lista in (("Adorno", partes1), ("Adorno derecho", partes2)):
        varios = len(lista) > 1
        for i, (color, g) in enumerate(lista, 1):
            nombre = f"{etiqueta} {i}" if varios else etiqueta
            visible = g.difference(tapa)
            if not recorte_adorno.is_empty:      # por detrás: la letra lo tapa
                visible = visible.difference(recorte_adorno)
            regiones.append((nombre, visible, h1, h2, color))
    if not agujero.is_empty:   # el agujero del llavero atraviesa todas las capas
        regiones = [(n, r.difference(agujero), z0, z1, c) for n, r, z0, z1, c in regiones]

    # Hueco del imán: solo se quita del tramo de abajo del nivel 1, así queda un bolsillo.
    bolsillo = hueco_iman(a, *centro)
    # Por piezas: cada nivel crece una espiga hacia abajo y al de debajo se le vacía esa
    # silueta con holgura, así que al pegar cae solo en su sitio y no hay que alinear a ojo.
    bolsas = {}
    if espiga:
        for altura in (a.alto_nivel1, a.alto_nivel2):
            encima = [r for _, r, z0, _, _ in regiones
                      if abs(z0 - altura) < 1e-9 and not r.is_empty]
            if encima:
                bolsas[altura] = unary_union(encima).buffer(holgura, join_style=1)

    niveles, arranques = [], []
    for nombre, region, z0, z1, color in regiones:
        if espiga:
            tramos = [(region, max(z0 - espiga, 0.0), z1)]
            if z1 in bolsas:
                tramos = _rebanar(tramos, z1 - (espiga + holgura), bolsas[z1], True)
        else:
            tramos = capas_con_chaflan(region, z0, z1, a.chaflan)
        if not bolsillo.is_empty and z0 == 0.0:
            tramos = _rebanar(tramos, a.iman_hondo, bolsillo, False)
        mallas = []
        for r, za, zb in tramos:
            if zb - za > 1e-4:
                mallas += extruir(r, zb - za, za)
        if mallas:
            niveles.append((nombre, color, trimesh.util.concatenate(mallas)))
            arranques.append(z0)
    if not niveles:
        raise ValueError("No se generó geometría. Revisa los parámetros.")

    if espiga:   # cada color suelto, en fila a la derecha y apoyado en la mesa
        apartar_por_color([p for p, z in zip(niveles, arranques) if z > 0], todo.bounds[2])

    analisis = _analizar(niveles, todo, regiones, [c for c, _ in partes1])
    if espiga:
        analisis["avisos"].append(
            f"Cada nivel sale suelto y apoyado en la mesa, al lado del anterior: imprímelo "
            f"con su filamento y pégalo en su hueco ({espiga:.1f} mm de hondura y "
            f"{holgura:.1f} mm de holgura).")
    return niveles, analisis
