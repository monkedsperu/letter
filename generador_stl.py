#!/usr/bin/env python3
"""
Monkeds Letter - generador 3MF a color: letra inicial con borde + texto con dos bordes, en 3 niveles de relieve.

Niveles apilados, cada uno es una capa maciza de un solo color:
    nivel 1 (0 -> alto 1): base completa; se ve como el borde de la letra y el borde 1 del texto
    nivel 2 (alto 1 -> alto 2): la letra + borde 2 del texto (el adorno va aquí con su color)
    nivel 3 (alto 2 -> alto 3): el texto y el patrón

Instalación:
    pip install trimesh shapely matplotlib numpy mapbox_earcut svgelements

Uso por consola (valores por defecto: inicial 80 mm, Cooper Black, texto Pacifico girado 15°):
    python generador_stl.py --inicial M --texto "aria"
    python generador_stl.py --inicial M --texto "aria" --giro-texto 0      # sin giro
    python generador_stl.py --inicial M --texto "aria" --color-nivel3 "#ff0000"

Pantalla web:
    python servidor_web.py

Fuentes: nombre de fuente instalada, ruta a un .ttf/.otf, o un archivo copiado en la
carpeta "fuentes" junto a este script (basta con que el nombre del archivo contenga
el nombre de la fuente, ej. "CooperBlack.ttf" o "Pacifico-Regular.ttf").
Patrón (nivel 3): un SVG de la carpeta "patrones". Cada figura separada del SVG es un motivo
(ej. estrella y punto); se reparten al azar por toda la letra grande, enteros, sin tocar el texto.
Adorno (ej. cuernos): un SVG de la carpeta "adornos", a la altura del nivel 2 con su propio color,
con el mismo borde que la letra (nivel 1). Puede salir de la letra. Lleva un segundo adorno
(la forma reflejada, ej. cuerno derecho) en espejo automático o en posición libre.
Todas las medidas están en milímetros.
"""
import argparse
import math
import os
import random
import re
import sys
import zipfile
from io import BytesIO
from dataclasses import dataclass, fields

import numpy as np
import trimesh
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, unary_union

# En el ejecutable portable las carpetas (fuentes, patrones, adornos) están junto al .exe
AQUI = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CARPETA_FUENTES = os.path.join(AQUI, "fuentes")
CARPETA_PATRONES = os.path.join(AQUI, "patrones")
CARPETA_ADORNOS = os.path.join(AQUI, "adornos")


@dataclass
class Parametros:
    inicial: str = "M"
    texto: str = "Monkeds"
    fuente_inicial: str = "Cooper Black"
    tam_inicial: float = 80.0      # ALTURA real de la letra, en mm (8 cm)
    borde: float = 3.0             # ancho del borde alrededor de la letra (0 = sin borde)
    fuente_texto: str = "Pacifico"
    tam_texto: float = 30.0        # tamaño de fuente del texto (mm)
    borde_texto1: float = 2.0      # ancho del primer borde (exterior) del texto
    borde_texto2: float = 2.0      # ancho del segundo borde (interior) del texto
    giro_texto: float = 15.0       # grados, positivo = antihorario
    posicion: str = "sobre"        # sobre | arriba | derecha
    separacion: float = 5.0        # separación letra-texto (arriba / derecha)
    cortar_letra: bool = False     # True = el borde 1 del texto corta la letra grande
    alto_nivel1: float = 5.0       # altura donde termina cada capa, desde la base (mm)
    alto_nivel2: float = 10.0
    alto_nivel3: float = 13.0
    color_nivel1: str = "#2b2b2b"
    color_nivel2: str = "#f2f2f2"
    color_nivel3: str = "#d63a2f"
    patron: str = "copos_y_puntos.svg"      # archivo en "patrones"; "" = sin patrón
    tam_patron: float = 8.0        # medida del motivo más grande (mm); el resto guarda su proporción
    separacion_patron: float = 8.0 # espacio mínimo entre motivos (mm): más chico = más denso
    margen_patron: float = 1.0     # distancia mínima al texto y al borde de la letra (mm)
    semilla: int = 1               # cambia el reparto al azar
    girar_patron: bool = True      # giro libre; False = solo leve inclinación (ej. arbolitos derechos)
    adorno: str = "horn.svg"       # archivo en "adornos"; "" = sin adorno
    tam_adorno: float = 40.0       # medida mayor del adorno (mm)
    adorno_x: float = -42.0        # centro del adorno en mm desde el centro de la letra
    adorno_y: float = 38.0
    giro_adorno: float = 0.0
    segundo_adorno: str = "espejo" # espejo (simétrico) | libre (posición propia) | ninguno
    adorno2_x: float = 30.0        # posición/giro del segundo adorno (solo en modo libre)
    adorno2_y: float = 42.0
    giro_adorno2: float = 0.0
    cortar_adorno: bool = True     # True = el borde del adorno corta la letra grande
    color_adorno: str = "#8a5a33"
    # Aro para llavero: anillo plano pegado a la letra, con el grosor del nivel 1
    aro: bool = False
    aro_diametro: float = 17.0     # diámetro exterior (mm)
    aro_agujero: float = 7.0       # diámetro del agujero (mm)
    aro_x: float = 0.0             # centro del aro en mm desde el centro de la letra
    aro_y: float = 50.0


# ------------------------------------------------------------------ fuentes
def _norm(s: str) -> str:
    return s.lower().replace(" ", "").replace("-", "").replace("_", "")


def _fuentes_carpeta() -> dict:
    """{nombre_de_familia: ruta} de los .ttf/.otf de la carpeta fuentes/ (van junto al .exe)."""
    res = {}
    if os.path.isdir(CARPETA_FUENTES):
        for nombre in sorted(os.listdir(CARPETA_FUENTES)):
            if nombre.lower().endswith((".ttf", ".otf")):
                ruta = os.path.join(CARPETA_FUENTES, nombre)
                try:
                    res[FontProperties(fname=ruta).get_name()] = ruta
                except Exception:
                    pass
    return res


def cargar_fuente(fuente: str) -> FontProperties:
    if os.path.isfile(fuente):
        return FontProperties(fname=fuente)

    # 1) fuentes de la carpeta: por nombre de familia exacto, luego laxo (familia o archivo)
    carpeta = _fuentes_carpeta()
    if fuente in carpeta:
        return FontProperties(fname=carpeta[fuente])
    buscado = _norm(fuente)
    for familia, ruta in carpeta.items():
        if buscado == _norm(familia) or buscado in _norm(os.path.basename(ruta)):
            return FontProperties(fname=ruta)
    # 2) fuentes instaladas en el sistema
    try:
        ruta = font_manager.findfont(FontProperties(family=fuente), fallback_to_default=False)
        return FontProperties(fname=ruta)
    except ValueError:
        raise ValueError(
            f"No encontré la fuente '{fuente}'. Instálala en el sistema o copia su archivo "
            f".ttf/.otf a la carpeta: {CARPETA_FUENTES}"
        )


def fuentes_instaladas() -> dict:
    """Dos grupos para la pantalla: las de la carpeta fuentes/ y las instaladas en el equipo."""
    carpeta = sorted(_fuentes_carpeta().keys())
    sistema = sorted({f.name for f in font_manager.fontManager.ttflist} - set(carpeta))
    return {"carpeta": carpeta, "sistema": sistema}


# ------------------------------------------------------------------ patrón SVG
def svgs_en(carpeta):
    if not os.path.isdir(carpeta):
        return []
    return sorted(n for n in os.listdir(carpeta) if n.lower().endswith(".svg"))


def patrones_disponibles():
    return svgs_en(CARPETA_PATRONES)


def adornos_disponibles():
    return svgs_en(CARPETA_ADORNOS)


def colocar_adorno(a: Parametros, cx: float, cy: float):
    """Devuelve (adorno, segundo) ya colocados. El segundo es la forma reflejada (ej. cuerno
    derecho): simétrico respecto al centro de la letra, en su propia posición, o vacío."""
    nombre = os.path.basename(a.adorno)
    ruta = os.path.join(CARPETA_ADORNOS, nombre)
    if not os.path.isfile(ruta):
        raise ValueError(f"No encontré el adorno '{nombre}' en {CARPETA_ADORNOS}")
    if a.tam_adorno <= 0:
        raise ValueError("El tamaño del adorno debe ser mayor que 0.")
    g = svg_a_poligono(ruta)
    minx, miny, maxx, maxy = g.bounds
    f = a.tam_adorno / max(maxx - minx, maxy - miny)
    g = affinity.translate(g, -(minx + maxx) / 2, -(miny + maxy) / 2)
    g = affinity.scale(g, f, f, origin=(0, 0))
    reflejo = affinity.scale(g, -1, 1, origin=(0, 0))

    def poner(forma, x, y, giro):
        return affinity.translate(affinity.rotate(forma, giro, origin=(0, 0)), cx + x, cy + y)

    modo = a.segundo_adorno
    if modo == "espejo":
        segundo = poner(reflejo, -a.adorno_x, a.adorno_y, -a.giro_adorno)
    elif modo == "libre":
        segundo = poner(reflejo, a.adorno2_x, a.adorno2_y, a.giro_adorno2)
    elif modo == "ninguno":
        segundo = Polygon()
    else:
        raise ValueError("segundo_adorno debe ser: espejo, libre o ninguno")
    return poner(g, a.adorno_x, a.adorno_y, a.giro_adorno), segundo


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
        cuello = LineString([p1, p2]).buffer(max(pared, 3.0) / 2, cap_style=2)
        anillo = anillo.union(cuello).difference(agujero)
    return anillo, agujero


def svg_a_poligono(ruta: str):
    """SVG -> polígono shapely (solo formas con relleno; regla par-impar para los huecos)."""
    from svgelements import SVG, Close, Line, Move, Path, Shape

    piezas = []
    for e in SVG.parse(ruta).elements():
        if not isinstance(e, Shape) or e.fill is None or e.fill.value is None:
            continue
        forma = Polygon()
        for sub in Path(e).as_subpaths():
            pts = []
            for seg in Path(sub):
                if isinstance(seg, (Move, Line, Close)):
                    if seg.end is not None:
                        pts.append((seg.end.x, seg.end.y))
                else:  # curvas y arcos: 16 puntos por tramo
                    pts += [(q.x, q.y) for q in (seg.point(t) for t in np.linspace(0, 1, 17)[1:])]
            if len(pts) >= 3:
                forma = forma.symmetric_difference(Polygon(pts).buffer(0))
        piezas.append(forma)
    g = unary_union(piezas) if piezas else Polygon()
    if g.is_empty or g.area <= 0:
        raise ValueError(f"'{os.path.basename(ruta)}' no tiene formas rellenas "
                         "(en Inkscape: Trayecto > Trazo a trayecto).")
    return affinity.scale(g, 1, -1, origin=(0, 0))  # SVG tiene la Y hacia abajo


def repartir_patron(a: Parametros, zona):
    """Reparte al azar los motivos del SVG dentro de `zona`, enteros y sin tocarse entre sí."""
    nombre = os.path.basename(a.patron)
    ruta = os.path.join(CARPETA_PATRONES, nombre)
    if not os.path.isfile(ruta):
        raise ValueError(f"No encontré el patrón '{nombre}' en {CARPETA_PATRONES}")
    if a.tam_patron <= 0:
        raise ValueError("El tamaño del patrón debe ser mayor que 0.")
    motivos = _poligonos(svg_a_poligono(ruta))
    mayor = max(max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) for p in motivos)
    f = a.tam_patron / mayor
    piezas = []  # (motivo centrado y escalado, radio)
    for p in motivos:
        c = p.centroid
        p = affinity.scale(affinity.translate(p, -c.x, -c.y), f, f, origin=(0, 0))
        piezas.append((p, max(math.hypot(x, y) for x, y in p.exterior.coords)))

    from shapely.prepared import prep
    dentro = prep(zona)
    minx, miny, maxx, maxy = zona.bounds
    rnd = random.Random(a.semilla)
    gap = max(a.separacion_patron, 0)
    puestos, colocados = [], []  # puestos: (x, y, radio)
    cuenta = [0] * len(piezas)   # se intenta siempre el motivo con menos colocados -> mezcla pareja
    vivos = set(range(len(piezas)))
    fallos = 0
    # ponytail: dardos al azar con choque por círculos envolventes; Poisson-disk si hace falta más parejo
    while vivos:
        i = min(vivos, key=lambda k: (cuenta[k], k))
        p, r = piezas[i]
        x, y = rnd.uniform(minx, maxx), rnd.uniform(miny, maxy)
        ok = not any(math.hypot(x - px, y - py) < r + pr + gap for px, py, pr in puestos)
        if ok:
            giro = rnd.uniform(0, 360) if a.girar_patron else rnd.uniform(-12, 12)
            m = affinity.translate(affinity.rotate(p, giro, origin=(0, 0)), x, y)
            ok = dentro.contains(m)
        if not ok:
            fallos += 1
            if fallos >= 400:  # ya no cabe este motivo
                vivos.discard(i)
                fallos = 0
            continue
        puestos.append((x, y, r))
        colocados.append(m)
        cuenta[i] += 1
        fallos = 0
    return unary_union(colocados) if colocados else Polygon()


# ------------------------------------------------------------------ geometría 2D
def _area_firmada(r):
    x, y = r[:, 0], r[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def texto_a_poligono(texto: str, fuente: str, tam: float):
    """Texto -> polígono shapely con agujeros. Une los trazos que se solapan (fuentes cursivas)."""
    ruta = TextPath((0, 0), texto, size=tam, prop=cargar_fuente(fuente))
    anillos = [np.asarray(r) for r in ruta.to_polygons() if len(r) >= 3]
    if not anillos:
        raise ValueError(f"El texto '{texto}' no generó contornos con la fuente '{fuente}'.")

    areas = [_area_firmada(r) for r in anillos]
    signo_externo = np.sign(areas[int(np.argmax(np.abs(areas)))])  # el anillo más grande es exterior

    externos, huecos = [], []
    for r, a in zip(anillos, areas):
        p = Polygon(r).buffer(0)
        if p.is_empty:
            continue
        (externos if np.sign(a) == signo_externo else huecos).append(p)

    piezas = []
    for ext in externos:
        for h in huecos:
            if ext.contains(h.representative_point()):
                ext = ext.difference(h)
        piezas.append(ext)
    return unary_union(piezas)


def _poligonos(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def extruir(poligono, alto: float, z0: float = 0.0):
    mallas = []
    # Limpieza para que el triangulador no deje mallas abiertas: encoger 0.01 mm separa/fusiona
    # anillos que se tocan en un punto, simplify quita puntos casi duplicados, y fuera huecos ínfimos.
    for p in _poligonos(poligono.buffer(-0.01, join_style=2).simplify(0.01)):
        if p.area < 1e-3:
            continue
        p = Polygon(p.exterior, [r for r in p.interiors if Polygon(r).area > 0.01])
        m = trimesh.creation.extrude_polygon(p, alto)
        m.apply_translation([0, 0, z0])
        mallas.append(m)
    return mallas


# ------------------------------------------------------------------ construcción
def construir(a: Parametros):
    """Devuelve [(nombre, color, malla)] para los 3 niveles (los vacíos se omiten)."""
    if not a.inicial.strip():
        raise ValueError("Falta la letra inicial.")
    if len(a.inicial.strip()) > 2:
        raise ValueError("La letra grande admite como máximo 2 letras.")
    for c in (a.color_nivel1, a.color_nivel2, a.color_nivel3, a.color_adorno):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError(f"Color inválido '{c}', usa formato #RRGGBB.")
    if not 0 < a.alto_nivel1 < a.alto_nivel2 < a.alto_nivel3:
        raise ValueError("Las alturas deben cumplir: 0 < nivel 1 < nivel 2 < nivel 3.")

    # Letra inicial escalada para que su ALTURA sea exactamente tam_inicial
    letra = texto_a_poligono(a.inicial.strip(), a.fuente_inicial, 100)  # 1 o 2 letras
    minx, miny, maxx, maxy = letra.bounds
    f = a.tam_inicial / (maxy - miny)
    letra = affinity.scale(letra, f, f, origin=(0, 0))
    minx, miny, _, _ = letra.bounds
    letra = affinity.translate(letra, -minx, -miny)
    minx, miny, maxx, maxy = letra.bounds
    # Adorno (y el segundo): forma parte de la silueta, así que el borde de nivel 1 lo rodea también.
    ad1 = ad2 = Polygon()
    if a.adorno:
        ad1, ad2 = colocar_adorno(a, (minx + maxx) / 2, (miny + maxy) / 2)
    h = ad1.union(ad2)
    hb = h.buffer(a.borde, join_style=1) if a.borde > 0 else h
    base = letra.difference(hb if a.cortar_adorno else h)  # la letra, sin lo que ocupa el adorno
    silueta = letra.union(h)
    contorno = silueta.buffer(a.borde, join_style=1) if a.borde > 0 else silueta
    cminx, cminy, cmaxx, cmaxy = contorno.bounds

    # Texto + sus dos bordes. t2 = texto con borde interior, t1 = huella completa.
    t = t1 = t2 = Polygon()
    if a.texto.strip():
        t = texto_a_poligono(a.texto, a.fuente_texto, a.tam_texto)
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
        t, t1, t2 = (affinity.translate(g, dx, dy) for g in (t, t1, t2))

    # Regiones disjuntas. Orden de pintado: letra -> adorno -> texto (el texto siempre manda).
    # cortar_letra: el texto con sus bordes tapa letra y adorno (el borde 1 los corta).
    # Si no, el borde 2 del texto se fusiona con la letra y el borde 1 solo se ve por fuera.
    tapa = t1 if a.cortar_letra else t2
    n_ad = h.difference(tapa)
    n2 = base.difference(tapa).union(t2.difference(t))
    # Patrón: solo sobre la parte de la letra en nivel 2, lejos del texto, del adorno y del borde.
    if a.patron:
        m = max(a.margen_patron, 0)
        zona = base.buffer(-m) if m else base
        zona = zona.difference(t1.buffer(m) if m else t1)
        deco = repartir_patron(a, zona)
        n2 = n2.difference(deco)
        t = t.union(deco)
    # Capas apiladas y macizas: lo que se ve arriba en 2D define qué tan alta es cada zona;
    # debajo de cada zona están completas las capas inferiores (nada llega a la base salvo el nivel 1).
    h1, h2, h3 = a.alto_nivel1, a.alto_nivel2, a.alto_nivel3
    cuerpo = unary_union([contorno, t1, n2, n_ad, t])
    anillo, agujero = aro_llavero(a, (minx + maxx) / 2, (miny + maxy) / 2, cuerpo)
    todo = cuerpo.union(anillo)
    regiones = [("Nivel 1", todo.difference(anillo), 0.0, h1, a.color_nivel1),
                ("Nivel 2", n2.union(t), h1, h2, a.color_nivel2),
                # adornos y aro por separado: la pantalla los mueve en vivo al arrastrar
                ("Adorno", n_ad.difference(ad2), h1, h2, a.color_adorno),
                ("Adorno derecho", n_ad.intersection(ad2), h1, h2, a.color_adorno),
                ("Aro", anillo, 0.0, h1, a.color_nivel1),
                ("Nivel 3", t, h2, h3, a.color_nivel3)]
    if not agujero.is_empty:   # el agujero del llavero atraviesa todas las capas
        regiones = [(n, r.difference(agujero), z0, z1, c) for n, r, z0, z1, c in regiones]
    niveles = []
    for nombre, region, z0, z1, color in regiones:
        mallas = extruir(region, z1 - z0, z0)
        if mallas:
            niveles.append((nombre, color, trimesh.util.concatenate(mallas)))
    if not niveles:
        raise ValueError("No se generó geometría. Revisa los parámetros.")
    return niveles


def exportar_stl(niveles) -> bytes:
    """STL: una sola malla con todas las capas (el formato no guarda colores)."""
    return trimesh.util.concatenate([m for _, _, m in niveles]).export(file_type="stl")


def miniatura_png(niveles, lado: int = 240) -> bytes:
    """Vista desde arriba en PNG para el historial. Sin pyplot (estado global) y en paleta
    de pocos colores, porque se guarda una por generación en la base de datos."""
    from matplotlib.collections import PolyCollection
    from matplotlib.figure import Figure
    from PIL import Image

    fig = Figure(figsize=(lado / 100, lado / 100), dpi=100)
    ax = fig.add_subplot(111)
    for _, color, m in sorted(niveles, key=lambda x: x[2].bounds[1][2]):  # de abajo hacia arriba
        ax.add_collection(PolyCollection(m.vertices[m.faces][:, :, :2], facecolors=color, edgecolors="none"))
    ax.autoscale()
    ax.set_aspect("equal")
    ax.axis("off")
    crudo = BytesIO()
    fig.savefig(crudo, format="png", transparent=True, bbox_inches="tight", pad_inches=0.04)

    crudo.seek(0)
    img = Image.open(crudo).convert("RGBA")
    fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))  # sin alfa: la paleta pesa menos
    img = Image.alpha_composite(fondo, img).convert("P", palette=Image.ADAPTIVE, colors=16)
    chico = BytesIO()
    img.save(chico, format="PNG", optimize=True)
    return chico.getvalue()


def exportar_3mf(niveles) -> bytes:
    """3MF: un objeto con una pieza por capa. Colores en m:colorgroup (extensión Materials):
    Bambu Studio / Orca los leen y piden asignar cada color a un filamento."""
    colores = list(dict.fromkeys(c.upper() for _, c, _ in niveles))  # únicos: mismo color = mismo filamento
    grupo = "".join(f'<m:color color="{c}"/>' for c in colores)
    objetos, comps = [], []
    for i, (nombre, color, m) in enumerate(niveles, start=2):
        v = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in m.vertices)
        t = "".join(f'<triangle v1="{p}" v2="{q}" v3="{r}"/>' for p, q, r in m.faces)
        objetos.append(f'<object id="{i}" name="{nombre}" type="model" pid="1" pindex="{colores.index(color.upper())}">'
                       f'<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>')
        comps.append(f'<component objectid="{i}"/>')
    raiz = len(niveles) + 2
    objetos.append(f'<object id="{raiz}" name="Monkeds Letter" type="model"><components>{"".join(comps)}</components></object>')
    modelo = ('<?xml version="1.0" encoding="UTF-8"?>'
              '<model unit="millimeter" xml:lang="es" '
              'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
              'xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">'
              '<metadata name="Application">Monkeds Letter</metadata>'
              f'<resources><m:colorgroup id="1">{grupo}</m:colorgroup>{"".join(objetos)}</resources>'
              f'<build><item objectid="{raiz}"/></build></model>')
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", modelo)
    return buf.getvalue()


def parametros_desde_dict(d: dict) -> Parametros:
    base = Parametros()
    for fld in fields(Parametros):
        if fld.name in d and d[fld.name] not in (None, ""):
            tipo = type(getattr(base, fld.name))
            v = d[fld.name]
            if tipo is bool:  # bool("false") sería True
                v = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "on", "si", "sí")
            setattr(base, fld.name, tipo(v))
        elif fld.name in ("texto", "patron", "adorno") and fld.name in d:
            setattr(base, fld.name, "")  # vacío = sin texto / patrón / adorno
    return base


# ------------------------------------------------------------------ consola
def main():
    d = Parametros()
    p = argparse.ArgumentParser(description="Monkeds Letter: genera un 3MF a color con letra inicial + texto.")
    p.add_argument("--inicial", required=True, help="Letra grande: 1 o 2 letras (ej. M o MA)")
    p.add_argument("--texto", default=d.texto, help="Texto que acompaña a la inicial")
    p.add_argument("--fuente-inicial", default=d.fuente_inicial)
    p.add_argument("--tam-inicial", type=float, default=d.tam_inicial, help="Altura de la letra (mm)")
    p.add_argument("--borde", type=float, default=d.borde, help="Ancho del borde de la letra (mm), 0 = sin borde")
    p.add_argument("--fuente-texto", default=d.fuente_texto)
    p.add_argument("--tam-texto", type=float, default=d.tam_texto, help="Tamaño del texto (mm)")
    p.add_argument("--borde-texto1", type=float, default=d.borde_texto1, help="Primer borde (exterior) del texto (mm)")
    p.add_argument("--borde-texto2", type=float, default=d.borde_texto2, help="Segundo borde (interior) del texto (mm)")
    p.add_argument("--giro-texto", type=float, default=d.giro_texto, help="Giro del texto en grados (0 = recto)")
    p.add_argument("--posicion", choices=["sobre", "arriba", "derecha"], default=d.posicion)
    p.add_argument("--separacion", type=float, default=d.separacion)
    p.add_argument("--cortar-letra", action="store_true", help="El borde 1 del texto corta la letra grande")
    for n in (1, 2, 3):
        p.add_argument(f"--alto-nivel{n}", type=float, default=getattr(d, f"alto_nivel{n}"), help=f"Altura nivel {n} (mm)")
        p.add_argument(f"--color-nivel{n}", default=getattr(d, f"color_nivel{n}"), help=f"Color nivel {n} (#RRGGBB)")
    p.add_argument("--patron", default=d.patron, help='SVG de la carpeta "patrones" ("" = sin patrón)')
    p.add_argument("--tam-patron", type=float, default=d.tam_patron, help="Tamaño del motivo mayor (mm)")
    p.add_argument("--separacion-patron", type=float, default=d.separacion_patron, help="Espacio entre motivos (mm)")
    p.add_argument("--margen-patron", type=float, default=d.margen_patron)
    p.add_argument("--semilla", type=int, default=d.semilla, help="Cambia el reparto al azar del patrón")
    p.add_argument("--sin-girar-patron", dest="girar_patron", action="store_false", help="Motivos derechos (leve inclinación)")
    p.add_argument("--adorno", default=d.adorno, help='SVG de la carpeta "adornos" ("" = sin adorno)')
    p.add_argument("--tam-adorno", type=float, default=d.tam_adorno, help="Medida mayor del adorno (mm)")
    p.add_argument("--adorno-x", type=float, default=d.adorno_x, help="Centro X desde el centro de la letra (mm)")
    p.add_argument("--adorno-y", type=float, default=d.adorno_y, help="Centro Y desde el centro de la letra (mm)")
    p.add_argument("--giro-adorno", type=float, default=d.giro_adorno)
    p.add_argument("--segundo-adorno", choices=["espejo", "libre", "ninguno"], default=d.segundo_adorno,
                   help="Adorno reflejado (cuerno derecho): espejo, libre o ninguno")
    p.add_argument("--adorno2-x", type=float, default=d.adorno2_x, help="Segundo adorno, modo libre (mm)")
    p.add_argument("--adorno2-y", type=float, default=d.adorno2_y, help="Segundo adorno, modo libre (mm)")
    p.add_argument("--giro-adorno2", type=float, default=d.giro_adorno2)
    p.add_argument("--no-cortar-adorno", dest="cortar_adorno", action="store_false",
                   help="El adorno se funde con la letra en vez de cortarla")
    p.add_argument("--color-adorno", default=d.color_adorno)
    p.add_argument("--aro", action="store_true", help="Añade un aro para llavero")
    p.add_argument("--aro-diametro", type=float, default=d.aro_diametro)
    p.add_argument("--aro-agujero", type=float, default=d.aro_agujero)
    p.add_argument("--aro-x", type=float, default=d.aro_x, help="Centro X desde el centro de la letra (mm)")
    p.add_argument("--aro-y", type=float, default=d.aro_y, help="Centro Y desde el centro de la letra (mm)")
    p.add_argument("--salida", default="salida.3mf")
    args = vars(p.parse_args())
    salida = args.pop("salida")

    try:
        niveles = construir(Parametros(**args))
    except ValueError as e:
        raise SystemExit(f"Error: {e}")
    with open(salida, "wb") as fh:
        fh.write(exportar_3mf(niveles))
    x, y, z = trimesh.util.concatenate([m for _, _, m in niveles]).extents
    print(f"Listo: {salida}  |  tamaño {x:.1f} x {y:.1f} x {z:.1f} mm  |  {len(niveles)} niveles")


if __name__ == "__main__":
    main()
