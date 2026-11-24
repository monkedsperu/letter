# -*- coding: utf-8 -*-
"""Lo que comparten todos los diseños: carpetas, fuentes, SVG, patrones, adornos, la
geometría de 2D a 3D, el análisis de imprimibilidad y la exportación a 3MF/STL.

Todas las medidas están en milímetros.
"""
import math
import os
import random
import sys
import zipfile
from io import BytesIO

import numpy as np
import trimesh
from matplotlib import font_manager
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextPath
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import transform as shapely_transform, unary_union

# En el ejecutable portable las carpetas (fuentes, patrones, adornos) están junto al .exe
AQUI = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                       else os.path.abspath(__file__))
CARPETA_FUENTES = os.path.join(AQUI, "fuentes")
CARPETA_PATRONES = os.path.join(AQUI, "patrones")
CARPETA_ADORNOS = os.path.join(AQUI, "adornos")

GROSOR_MINIMO = 0.8   # mm: dos perímetros de una boquilla de 0.4
CAMA_TIPICA = 250     # mm: aviso si no cabe en una impresora corriente
SOBRA = 50.0          # cuánto se alarga un corte por encima de la pieza, para que salga limpio
PASOS_CANTO = 3       # escalones con los que se dibuja cada cuarto de redondeo
APOYO = 1.0           # lo que casi toca la mesa (mm) se baja a ella: nada se imprime flotando
HUECO_APARTE = 10.0   # separación entre una pieza suelta y el cuerpo, para imprimirlas juntas
HUECO_MINIMO = 4.0    # hueco de encaje: menos no se aprecia en pantalla ni sujeta bien


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
    """Los SVG de la carpeta y de sus subcarpetas, nombrados en relativo: 'desktop/lapiz.svg'."""
    if not os.path.isdir(carpeta):
        return []
    nombres = []
    for raiz, _, ficheros in os.walk(carpeta):
        rel = os.path.relpath(raiz, carpeta)
        for f in ficheros:
            if f.lower().endswith(".svg"):
                nombres.append(f if rel == "." else rel.replace(os.sep, "/") + "/" + f)
    return sorted(nombres)


def svg_dentro_de(carpeta, nombre):
    """Ruta de un SVG de esa carpeta, admitiendo subcarpetas. None si el nombre se sale de
    ella: lo elige el usuario, así que no puede acabar leyendo cualquier cosa del disco."""
    ruta = os.path.normpath(os.path.join(carpeta, (nombre or "").replace("\\", "/")))
    dentro = ruta.startswith(os.path.join(carpeta, ""))
    return ruta if dentro and os.path.isfile(ruta) else None


def patrones_disponibles():
    return svgs_en(CARPETA_PATRONES)


def adornos_disponibles():
    return svgs_en(CARPETA_ADORNOS)


def svg_por_color(ruta: str):
    """SVG -> [(color, polígono)] respetando el orden de dibujo: lo de encima tapa lo de abajo.
    Solo cuenta lo que tiene relleno; los huecos salen por la regla par-impar."""
    from svgelements import SVG, Close, Line, Move, Path, Shape

    formas = []   # (color, polígono) en el orden en que están dibujadas
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
        if not forma.is_empty:
            try:
                color = e.fill.hex[:7].lower()
            except Exception:
                color = None
            formas.append((color, forma))

    if not formas:
        raise ValueError(f"'{os.path.basename(ruta)}' no tiene formas rellenas "
                         "(en Inkscape: Trayecto > Trazo a trayecto).")

    # de arriba hacia abajo: a cada forma se le quita lo que ya tapan las de encima
    visto, visibles = Polygon(), []
    for color, forma in reversed(formas):
        trozo = forma.difference(visto)
        if not trozo.is_empty:
            visibles.append((color, trozo))
        visto = visto.union(forma)
    visibles.reverse()

    grupos, orden = {}, []
    for color, trozo in visibles:
        if color not in grupos:
            grupos[color] = []
            orden.append(color)
        grupos[color].append(trozo)
    salida = [(c, affinity.scale(unary_union(grupos[c]), 1, -1, origin=(0, 0))) for c in orden]
    salida = [(c, g) for c, g in salida if not g.is_empty and g.area > 0]
    if not salida:
        raise ValueError(f"'{os.path.basename(ruta)}' no tiene formas rellenas.")
    return salida   # la Y del SVG va al revés, por eso el espejo vertical


def svg_a_poligono(ruta: str):
    """Todo el SVG en un solo polígono (para los patrones y para validar lo que se sube)."""
    return unary_union([g for _, g in svg_por_color(ruta)])


MAX_GRUPOS_ADORNO = 3     # un adorno no puede gastar más de 3 de los 4 filamentos
NEGRO_HASTA = 60          # canal máximo por debajo del cual se considera negro y se descarta
JUNTAR_SI_MENOS_DE = 60   # colores más parecidos que esto se tratan como uno solo


def _rgb(color: str):
    c = (color or "#000000").lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) >= 6 else (0, 0, 0)


def _es_negro(color: str) -> bool:
    return max(_rgb(color)) <= NEGRO_HASTA


def _distancia(a: str, b: str) -> float:
    x, y = _rgb(a), _rgb(b)
    return sum((p - q) ** 2 for p, q in zip(x, y)) ** 0.5


def grupos_adorno(ruta: str, maximo: int = MAX_GRUPOS_ADORNO):
    """Formas del SVG agrupadas y limpiadas, listas para pintar con la paleta del llavero:
    fuera lo negro (suele ser el contorno), los tonos casi iguales se juntan, y como mucho
    quedan `maximo` grupos ordenados de mayor a menor superficie."""
    grupos = svg_por_color(ruta)
    sin_negro = [(c, g) for c, g in grupos if not _es_negro(c)]
    if sin_negro:                      # si TODO era negro, es una silueta: se respeta
        grupos = sin_negro

    juntos = []                        # tonos casi iguales (ej. tres rojos) -> uno solo
    for color, g in sorted(grupos, key=lambda x: -x[1].area):
        for i, (c0, gs) in enumerate(juntos):
            if _distancia(color, c0) < JUNTAR_SI_MENOS_DE:
                juntos[i] = (c0, gs + [g])
                break
        else:
            juntos.append((color, [g]))
    juntos = [(c, unary_union(gs)) for c, gs in juntos]
    juntos.sort(key=lambda x: -x[1].area)

    if len(juntos) > maximo:           # los sobrantes se suman al color más parecido
        quedan, sobran = juntos[:maximo], juntos[maximo:]
        for color, g in sobran:
            i = min(range(maximo), key=lambda k: _distancia(color, quedan[k][0]))
            quedan[i] = (quedan[i][0], quedan[i][1].union(g))
        juntos = quedan
    return juntos


MAX_MOTIVOS = 600      # más motivos que esto no es un patrón, es una mancha
MAX_DARDOS = 25000     # y un tope de intentos: el reparto nunca puede eternizarse


def repartir_patron(zona, nombre: str, tam: float, separacion: float, semilla: int,
                    girar: bool):
    """Reparte al azar los motivos del SVG dentro de `zona`, enteros y sin tocarse entre sí."""
    ruta = svg_dentro_de(CARPETA_PATRONES, nombre)
    if not ruta:
        raise ValueError(f"No encontré el patrón '{nombre}' en {CARPETA_PATRONES}")
    if tam <= 0:
        raise ValueError("El tamaño del patrón debe ser mayor que 0.")
    motivos = _poligonos(svg_a_poligono(ruta))
    mayor = max(max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) for p in motivos)
    f = tam / mayor
    piezas = []  # (motivo centrado y escalado, radio)
    for p in motivos:
        c = p.centroid
        p = affinity.scale(affinity.translate(p, -c.x, -c.y), f, f, origin=(0, 0))
        piezas.append((p, max(math.hypot(x, y) for x, y in p.exterior.coords)))

    from shapely.prepared import prep
    dentro = prep(zona)
    minx, miny, maxx, maxy = zona.bounds
    rnd = random.Random(semilla)
    gap = max(separacion, 0)
    puestos, colocados = [], []  # puestos: (x, y, radio)
    cuenta = [0] * len(piezas)   # se intenta siempre el motivo con menos colocados -> mezcla pareja
    vivos = set(range(len(piezas)))
    fallos = dardos = 0
    # Tope de motivos y de intentos: el reparto es a dardos y el choque se mira contra todos
    # los puestos, así que sin tope un motivo diminuto en una letra grande cuelga el proceso.
    # Con los valores normales no se roza ninguno de los dos.
    if min(p.area for p, _ in piezas) * MAX_MOTIVOS < zona.area / 50:
        raise ValueError("El motivo del patrón es demasiado pequeño para esta letra: "
                         "sube su tamaño o baja el de la letra.")
    # ponytail: dardos al azar con choque por círculos envolventes; Poisson-disk si hace falta más parejo
    while vivos and len(colocados) < MAX_MOTIVOS and dardos < MAX_DARDOS:
        dardos += 1
        i = min(vivos, key=lambda k: (cuenta[k], k))
        p, r = piezas[i]
        x, y = rnd.uniform(minx, maxx), rnd.uniform(miny, maxy)
        ok = not any(math.hypot(x - px, y - py) < r + pr + gap for px, py, pr in puestos)
        if ok:
            giro = rnd.uniform(0, 360) if girar else rnd.uniform(-12, 12)
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


def _arquear(g, grados: float):
    """Dobla un polígono sobre un arco. Se densifica antes para que las rectas se curven."""
    if not grados or g.is_empty:
        return g
    minx, _, maxx, _ = g.bounds
    ancho = maxx - minx
    if ancho <= 0:
        return g
    radio = ancho / math.radians(abs(grados))
    centro = (minx + maxx) / 2
    signo = 1 if grados > 0 else -1
    g = g.segmentize(max(ancho / 400, 0.3))

    def doblar(x, y):
        ang = (x - centro) / radio
        r = radio - signo * y
        return (centro + r * np.sin(ang), signo * (radio - r * np.cos(ang)))

    return shapely_transform(lambda x, y: tuple(np.array(v) for v in doblar(x, y)), g).buffer(0)


def texto_en_lineas(texto: str, fuente: str, tam: float, curva: float = 0.0):
    """El texto completo. Con '|' se parte en varias líneas, centradas una sobre otra."""
    lineas = [l for l in str(texto).replace("\n", "|").split("|")]
    piezas, y = [], 0.0
    for linea in lineas:
        if linea.strip():
            g = texto_a_poligono(linea, fuente, tam)
            minx, miny, maxx, maxy = g.bounds
            piezas.append(affinity.translate(g, -(minx + maxx) / 2, y - maxy))
        y -= tam * 1.25
    if not piezas:
        raise ValueError("El texto está vacío.")
    return _arquear(unary_union(piezas), curva)


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


def _escalones(r: float, signo: int, pasos: int):
    """Un cuarto de circunferencia de radio r en escalones: [(desplazamiento, t0, t1)], con t
    medido desde la punta hacia dentro. signo +1 redondea el canto, -1 lo ensancha en
    garganta (la curva cóncava con la que una pieza nace de otra).
    Los escalones se reparten por ÁNGULO, no por profundidad: repartidos por profundidad el
    primero se come el 82% del radio por muchos pasos que se pongan, y el canto acaba en un
    chaflán recto. Por ángulo salen finos donde la curva es vertical y anchos donde es plana."""
    tramos = []
    for i in range(pasos):
        f0, f1 = (math.pi / 2) * i / pasos, (math.pi / 2) * (i + 1) / pasos
        t0, t1 = r * (1 - math.cos(f0)), r * (1 - math.cos(f1))
        tramos.append((signo * r * (1 - math.sin((f0 + f1) / 2)), t0, t1))
    return tramos


def _extruido(poligono, largo: float, r0: float = 0.0, r1: float = 0.0, que="la pieza",
              pasos: int = PASOS_CANTO, suelo=None):
    """Prisma de z=0 a z=largo con las dos puntas rematadas: r>0 redondea el canto,
    r<0 lo abre en garganta para que se funda con lo que tiene al lado, 0 lo deja a escuadra.
    Es la versión a lo largo de un eje de `capas_con_chaflan`.
    `suelo` es la altura a la que la pieza apoya en la mesa (en coordenadas del dibujo):
    ahí no se redondea nada, porque esto se imprime de pie y el apoyo tiene que ser plano."""
    a0, a1 = min(abs(r0), largo / 2), min(abs(r1), largo / 2)
    tramos = [(0.0, a0, largo - a1)]
    tramos += [(d, t0, t1) for d, t0, t1 in _escalones(a0, 1 if r0 >= 0 else -1, pasos)]
    tramos += [(d, largo - t1, largo - t0)
               for d, t0, t1 in _escalones(a1, 1 if r1 >= 0 else -1, pasos)]
    px0, _, px1, py1 = poligono.bounds
    mallas = []
    for desplazo, z0, z1 in tramos:
        if z1 - z0 < 1e-4:
            continue
        # a inglete: las siluetas ya vienen redondeadas y así el canto no multiplica los puntos
        g = poligono.buffer(-desplazo, join_style=2) if abs(desplazo) > 1e-6 else poligono
        if suelo is not None and abs(desplazo) > 1e-6:
            # el canto no puede levantar el apoyo: esto se imprime de pie. Al meter el
            # contorno hacia dentro, su borde de abajo sube `desplazo`; se le añade una falda
            # que es ese mismo contorno, a esa altura, estirado hasta la mesa. Copiar el
            # contorno de más arriba no vale: la silueta se ensancha al subir y dejaría un alero.
            if desplazo > 0:
                lamina = 0.2
                corte = g.intersection(box(px0 - 1, suelo + desplazo, px1 + 1,
                                           suelo + desplazo + lamina))
                if not corte.is_empty:
                    arriba = suelo + desplazo + lamina
                    g = g.union(affinity.scale(corte, 1.0, (desplazo + lamina) / lamina,
                                               origin=(0, arriba)))
            g = g.intersection(box(px0 - 5, suelo, px1 + 5, py1 + 5))
        mallas += extruir(g, z1 - z0, z0)
    if not mallas:
        raise ValueError(f"No se generó {que}. Revisa las medidas.")
    return mallas[0] if len(mallas) == 1 else _booleana(trimesh.boolean.union, mallas, f"formar {que}")


def _tumbado(malla, y: float = 0.0):
    """Pone de pie un prisma hecho sobre Z: su dibujo pasa a verse de frente (plano XZ) y
    crece hacia atrás sobre Y. La punta z=0 queda en y, y la otra hacia delante."""
    malla.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0)))
    malla.apply_translation([0, y, 0])
    return malla


def _booleana(fn, mallas, que: str):
    """Las booleanas 3D necesitan manifold3d (o blender). Si falla, el motivo se ve en pantalla.
    check_volume mide el volumen de cada pieza antes de operar y se lleva la mitad del tiempo;
    aquí todas salen de extrusiones cerradas, así que se comprueba el resultado al final."""
    try:
        return fn(mallas, check_volume=False)
    except Exception as e:
        raise ValueError(f"No se pudo {que}: {e}. Si acabas de actualizar, instala las "
                         f"dependencias otra vez (pip install -r requirements.txt).")


def _circulo(cx: float, cy: float, radio: float):
    return Point(cx, cy).buffer(radio, quad_segs=24)


def _borde_que_une(poligono, desde: float, maximo: float = 30.0):
    """Qué ancho de borde hace falta para que el nombre salga de una sola pieza. Dos letras
    se juntan cuando el borde cubre la mitad del hueco que las separa, así que el número
    depende del nombre y de la fuente: se busca a tientas, que cada prueba es un engorde."""
    if len(_poligonos(poligono.buffer(maximo, join_style=1))) > 1:
        return None                      # ni ensanchándolo mucho; son palabras muy separadas
    bajo, alto = desde, maximo
    for _ in range(9):          # 9 pruebas dejan el resultado en una decima de milimetro
        medio = (bajo + alto) / 2
        if len(_poligonos(poligono.buffer(medio, join_style=1))) == 1:
            alto = medio
        else:
            bajo = medio
    return alto


def adorno_en_grupos(nombre: str, alto: float, giro: float, cx: float, y_base: float,
                     paleta: dict, destinos, por_defecto: str):
    """[(color, polígono)] de un SVG de la carpeta de adornos, escalado a `alto`, girado,
    centrado en `cx` y apoyado en `y_base`. Como en el llavero, del SVG solo se aprovechan
    las formas (hasta 3) y el color sale de la paleta de la pieza, así que por muchos
    colores que traiga el dibujo nunca hacen falta más de 4 filamentos. Con el destino
    "svg" se respeta el color que trae el dibujo, y entonces sí pueden hacer falta más
    (el análisis avisa)."""
    ruta = svg_dentro_de(CARPETA_ADORNOS, nombre)
    if not ruta:
        raise ValueError(f"No encontré el adorno '{nombre}' en la carpeta adornos.")
    if alto <= 0:
        raise ValueError("El alto del adorno debe ser mayor que 0.")
    propios = grupos_adorno(ruta)       # [(color del dibujo, forma)]
    grupos = [g for _, g in propios]
    x_ini, y_ini, x_fin, y_fin = unary_union(grupos).bounds
    escala = alto / (y_fin - y_ini)
    medio = ((x_ini + x_fin) / 2 * escala, (y_ini + y_fin) / 2 * escala)

    def colocar(g):
        g = affinity.scale(g, escala, escala, origin=(0, 0))
        return affinity.rotate(g, giro, origin=medio) if giro else g

    grupos = [colocar(g) for g in grupos]
    x_ini, y_ini, x_fin, y_fin = unary_union(grupos).bounds
    dx, dy = cx - (x_ini + x_fin) / 2, y_base - y_ini
    puestos = []
    for i, g in enumerate(grupos):
        destino = destinos[i] if i < len(destinos) else "extra"
        color = propios[i][0] if destino == "svg" else paleta.get(destino, por_defecto)
        puestos.append((color, affinity.translate(g, dx, dy)))
    return puestos


def _analizar(niveles, huella, regiones, grupos_del_adorno=0):
    """Volumen de cada pieza y avisos de imprimibilidad. No guarda nada: es informativo."""
    piezas = [{"nombre": n, "color": c, "cm3": round(m.volume / 1000, 2)} for n, c, m in niveles]
    colores = list(dict.fromkeys(p["color"].lower() for p in piezas))
    avisos = []
    if len(colores) > 4:
        avisos.append(f"Usa {len(colores)} colores: más de los 4 de un AMS.")

    sueltas = len(_poligonos(huella))
    if sueltas > 1:
        avisos.append(f"El diseño tiene {sueltas} piezas separadas: no saldrá de una sola pieza.")

    finas = 0
    for _, region, *_ in regiones:
        for p in _poligonos(region):
            if p.buffer(-GROSOR_MINIMO / 2).is_empty:
                finas += 1
    if finas:
        avisos.append(f"{finas} parte{'s' if finas > 1 else ''} más fina{'s' if finas > 1 else ''} "
                      f"que {GROSOR_MINIMO} mm: puede que no se impriman bien.")

    x0, y0, x1, y1 = huella.bounds
    if max(x1 - x0, y1 - y0) > CAMA_TIPICA:
        avisos.append(f"Mide {x1 - x0:.0f} × {y1 - y0:.0f} mm: no cabe en una cama de "
                      f"{CAMA_TIPICA / 10:.0f} cm.")
    return {"piezas": piezas, "cm3": round(sum(p["cm3"] for p in piezas), 2),
            "colores": colores, "grupos_adorno": grupos_del_adorno, "avisos": avisos}


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


def fundir_por_color(niveles):
    """Junta en una sola pieza todo lo que comparte color. Así el 3MF lleva exactamente
    un objeto por filamento, en vez de una pieza por nivel y adorno."""
    grupos = {}
    for nombre, color, malla in niveles:
        clave = color.upper()
        grupos.setdefault(clave, []).append(malla)
    return [(f"Color {i}", color, trimesh.util.concatenate(mallas))
            for i, (color, mallas) in enumerate(grupos.items(), 1)]


def exportar_3mf(niveles, fundir: bool = False) -> bytes:
    """3MF con los colores en m:colorgroup (extensión Materials): Bambu Studio / Orca los leen
    y piden asignar cada color a un filamento. Con fundir=True va un objeto por color."""
    if fundir:
        niveles = fundir_por_color(niveles)
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
