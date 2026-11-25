# -*- coding: utf-8 -*-
"""Diseño 4: el marcapáginas. Una lámina plana y alargada con la letra grande arriba del
todo, el nombre debajo y, si se quiere, un icono suelto alrededor de la letra. La lámina
crece para sostener lo que sobresalga, así que todo se imprime tumbado y sin soportes."""
import re

import trimesh
from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from comun import (GROSOR_MINIMO, _analizar, _poligonos, adorno_en_grupos, adornos_extra,
                   apartar_por_color, extruir, repartir_patron, texto_a_poligono)
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
    if letra is not None:                   # manda la letra: el icono orbita a su alrededor
        lx0, ly0, lx1, ly1 = letra.bounds
        cx, cy = (lx0 + lx1) / 2, (ly0 + ly1) / 2
    elif texto is not None:                 # sin letra, el hueco que queda sobre el nombre
        cx, cy = 0.0, (texto.bounds[3] + a.mar_largo) / 2
    else:
        cx, cy = 0.0, a.mar_largo - radio
    paleta_adorno = {"cuerpo": a.mar_color_cuerpo, "texto": a.mar_color_texto,
                     "inicial": a.mar_color_inicial, "extra": a.mar_color_adorno}
    if a.mar_adorno:
        partes = adorno_en_grupos(
            a.mar_adorno_svg, a.mar_adorno_alto, a.mar_adorno_giro,
            cx + a.mar_adorno_x, cy + a.mar_adorno_y - a.mar_adorno_alto / 2,
            paleta_adorno,
            [a.mar_adorno_c1, a.mar_adorno_c2, a.mar_adorno_c3], a.mar_color_adorno,
            ("extra", "cuerpo", "texto"),
            (a.mar_adorno_tinta1, a.mar_adorno_tinta2, a.mar_adorno_tinta3))
        # delante el icono tapa las letras; detrás son ellas las que lo cortan. En los dos
        # casos el que manda deja un aire alrededor, para que la junta se vea a propósito
        letras = unary_union([g for _, g, _ in piezas])
        aire = max(a.mar_adorno_aire, 0.0)
        if not letras.is_empty:
            if a.mar_adorno_detras:
                corte = letras.buffer(aire, join_style=1) if aire else letras
                partes = [(c, g.difference(corte)) for c, g in partes]
                partes = [(c, g) for c, g in partes if not g.is_empty]
            else:
                dibujo = unary_union([g for _, g in partes])
                corte = dibujo.buffer(aire, join_style=1) if aire else dibujo
                piezas = [(n, g.difference(corte), c) for n, g, c in piezas]
                piezas = [(n, g, c) for n, g, c in piezas if not g.is_empty]
        varios = len(partes) > 1
        for i, (color, g) in enumerate(partes, 1):
            piezas.append((f"Icono {i}" if varios else "Icono", g, color))
    else:
        partes = []

    # ---- dos iconos más, sueltos y cada uno con su capa: detrás los cortan las letras y
    # delante son ellos los que cortan, igual que el primero
    extra, formas_extra, recorte = adornos_extra(
        a, "mar_", (2, 3), cx, cy, paleta_adorno, a.mar_color_adorno,
        ("extra", "cuerpo", "texto"),
        unary_union([g for n, g, _ in piezas if not n.startswith("Icono")]))
    if not recorte.is_empty:
        piezas = [(n, g if n.startswith("Icono") else g.difference(recorte), c)
                  for n, g, c in piezas]
    piezas += [(n, g, c) for _, n, g, c in extra]
    piezas = [(n, g, c) for n, g, c in piezas if not g.is_empty]

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

    # ---- el tope: un murito cruzado justo debajo de lo que lleva escrito, para que el
    # marcapáginas no se cuele entero entre las páginas y se pierda dentro del libro
    pie = min([g.bounds[1] for _, g, _ in piezas] or [a.mar_largo]) - hueco
    tope = Polygon()
    if a.mar_tope and a.mar_tope_alto > 0 and a.mar_tope_grueso > 0:
        if pie - a.mar_tope_grueso <= radio:
            raise ValueError("No queda sitio para el tope: baja el nombre o alarga la lámina.")
        bx0, _, bx1, _ = cuerpo.bounds
        tope = cuerpo.intersection(box(bx0 - 1, pie - a.mar_tope_grueso, bx1 + 1, pie))

    # ---- el estilo de la lámina: entera, con una ranura o calada con un patrón
    estilo = (a.mar_estilo or "solido").strip().lower()
    alto_libre = pie - a.mar_tope_grueso - 2 * radio      # lo que queda de lámina por debajo
    if estilo not in ("solido", "ranura", "calado"):
        raise ValueError("El estilo de la lámina debe ser: solido, ranura o calado.")
    if estilo != "solido" and alto_libre < 10:
        raise ValueError("La lámina se queda sin sitio para el calado: alárgala o sube el "
                         "nombre.")
    if estilo == "ranura":
        # una LENGÜETA que cuelga de arriba y queda suelta por abajo, con el hueco dándole
        # la vuelta: la hoja del libro se mete entre ella y el marco, y por eso agarra. Si
        # la lengüeta acabara pegada al final de la lámina no habría por dónde meter la hoja
        hueco_lado = max(a.mar_ranura_ancho, 0.8)
        gorda = max(a.mar_ranura_centro, 2.0)
        if gorda + 2 * hueco_lado + 4 * GROSOR_MINIMO > a.mar_ancho:
            raise ValueError("La lengüeta y su hueco no caben a lo ancho: estréchalos o "
                             "ensancha la lámina.")
        arriba = pie - a.mar_tope_grueso - 2
        abajo = radio + hueco_lado + 2
        if arriba - abajo < 15:
            raise ValueError("No hay sitio para la lengüeta: alarga la lámina o sube el "
                             "nombre.")
        lengueta = LineString([(0, abajo), (0, arriba)]).buffer(gorda / 2, quad_segs=24)
        ranura = lengueta.buffer(hueco_lado, join_style=1).difference(lengueta)
        ranura = ranura.intersection(box(-1e4, -1e4, 1e4, arriba))   # arriba sigue unida
        cuerpo = cuerpo.difference(ranura)
    elif estilo == "calado":
        zona = cuerpo.intersection(box(-1e4, radio, 1e4, pie - a.mar_tope_grueso - 2))
        zona = zona.buffer(-max(GROSOR_MINIMO * 2, 1.6))
        if not zona.is_empty:
            deco = repartir_patron(zona, a.mar_patron_svg, a.mar_tam_patron,
                                   a.mar_separacion_patron, a.mar_semilla, False)
            if not deco.is_empty:
                cuerpo = cuerpo.difference(deco)
    if len(_poligonos(cuerpo)) > 1:
        raise ValueError("El calado parte la lámina en trozos: hazlo más pequeño o menos "
                         "ancho.")

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
    if not tope.is_empty:      # el murito va con la lámina: mismo color y misma pieza.
        # arranca medio milímetro por debajo de la cara para que queden pegados de verdad
        mordida = min(0.5, a.mar_grueso / 3)
        mallas += extruir(tope, a.mar_tope_alto + mordida, suelo - mordida)
    niveles = [("Lamina", a.mar_color_cuerpo, trimesh.util.concatenate(mallas))]
    for etiqueta, region, z0, z1, color in regiones[1:]:
        trozos = extruir(region, z1 - z0, z0)
        if trozos:
            niveles.append((etiqueta, color, trimesh.util.concatenate(trozos)))
    if len(niveles) < 2 and not espiga and len(piezas) == 0:
        raise ValueError("No se generó geometría. Revisa los parámetros.")

    if espiga:      # cada color en fila al lado de la lámina, apoyado en la mesa
        apartar_por_color([p for p in niveles if p[0] != "Lamina"], cuerpo.bounds[2])

    analisis = _analizar(niveles, cuerpo, regiones, [c for c, _ in partes])
    analisis["formas_adorno"] = formas_extra
    analisis["avisos"].append("Todo es plano: se imprime tumbado, con la cara buena hacia "
                              "arriba y sin soportes.")
    if not tope.is_empty:
        analisis["avisos"].append(f"El tope de {a.mar_tope_alto:.0f} mm va debajo del nombre: "
                                  "apoya en el canto del libro y no se cuela entre las hojas.")
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
