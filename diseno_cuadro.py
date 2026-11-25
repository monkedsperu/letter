# -*- coding: utf-8 -*-
"""Diseño 3: el cuadro para colgar las llaves. El apellido en grande, los nombres de la
casa alrededor, un gancho bajo cada uno y la placa recortada con la forma del conjunto."""
import math
import re

import trimesh
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from comun import (HUECO_APARTE, _analizar, _booleana, _poligonos, adorno_en_grupos,
                   extruir, repartir_patron, texto_a_poligono, GROSOR_MINIMO)
from parametros import Parametros

MAX_INTEGRANTES = 8
MAX_LETRAS_CUADRO = 16


def _fila_de_nombres(a: Parametros, nombres):
    """Los nombres de la fila, todos a la misma escala y con la misma línea de apoyo,
    repartidos de izquierda a derecha. Devuelve [(polígono, centro x)] ya centrados en 0."""
    crudos = [texto_a_poligono(n, a.cua_fuente, 100) for n in nombres]
    escala = a.cua_alto_integrantes / max(p.bounds[3] - p.bounds[1] for p in crudos)
    piezas, x = [], 0.0
    for p in crudos:
        p = affinity.scale(p, escala, escala, origin=(0, 0))
        x0, _, x1, _ = p.bounds
        piezas.append(affinity.translate(p, x - x0, 0))
        x += (x1 - x0) + max(a.cua_hueco, 0)
    ancho = x - max(a.cua_hueco, 0)
    return [affinity.translate(p, -ancho / 2, 0) for p in piezas]


TRAMO_CORONA = 0.85    # del contorno: lo mas que se puede ocupar sin dar la vuelta entera


def _nombres_alrededor(piezas, zona, sep: float, hueco: float, sitio_gancho,
                       margen: float):
    """Reparte los nombres siguiendo el contorno del apellido, como un texto sobre un
    camino: los encadena separados por `hueco` y centrados abajo, de modo que suben por los
    lados cuando son muchos. Cada uno se empuja hacia fuera hasta que no roza ni el apellido
    ni al vecino -contando el sitio que necesita su gancho-, así la figura engorda por igual
    en todas las direcciones en vez de alargarse por un lado.
    Devuelve None si no caben alrededor, para que el que llama los ponga en fila."""
    blob = zona.buffer(margen, join_style=1).buffer(-margen, join_style=1)
    trozos = _poligonos(blob)
    if not trozos:
        return None
    blob = max(trozos, key=lambda p: p.area)
    curva = blob.exterior
    if not curva.is_ccw:        # al derecho, avanzar por el contorno va de izquierda a derecha
        curva = curva.reverse()
    anchos = [p.bounds[2] - p.bounds[0] for p in piezas]
    total = sum(anchos) + hueco * (len(piezas) - 1)
    if total > TRAMO_CORONA * curva.length:
        return None
    # aunque quepan de sobra, se reparten por buena parte del contorno: si no, unos pocos
    # nombres se quedarian apinados abajo y la figura crecerian solo por ese lado
    tramo = min(max(total, 0.55 * curva.length), TRAMO_CORONA * curva.length)
    hueco = (tramo - sum(anchos)) / max(len(piezas) - 1, 1)
    centro = blob.centroid
    abajo = Point((blob.bounds[0] + blob.bounds[2]) / 2, blob.bounds[1])
    s = curva.project(abajo) - tramo / 2
    puestas, ocupado = [], blob.buffer(sep, join_style=1)
    for p, ancho in zip(piezas, anchos):
        punto = curva.interpolate((s + ancho / 2) % curva.length)
        s += ancho + hueco
        x0, y0, x1, y1 = p.bounds
        base = affinity.translate(p, punto.x - (x0 + x1) / 2, punto.y - (y0 + y1) / 2)
        reserva = unary_union([base, sitio_gancho(base)])
        dx, dy = punto.x - centro.x, punto.y - centro.y
        largo = math.hypot(dx, dy) or 1.0
        dx, dy = dx / largo, dy / largo
        t = 0.0
        for _ in range(400):
            if not affinity.translate(reserva, dx * t, dy * t).intersects(ocupado):
                break
            t += 1.2
        puestas.append(affinity.translate(base, dx * t, dy * t))
        ocupado = ocupado.union(
            affinity.translate(reserva, dx * t, dy * t).buffer(1.0, join_style=1))
    return puestas


def _desplazamientos(texto: str, cuantos: int):
    """'12,-4;0,8' -> [(12,-4), (0,8), ...]: lo que el usuario ha arrastrado cada nombre.
    Lo que no se entienda cuenta como sin mover, y nada se va más allá de medio metro."""
    movidos = []
    for trozo in (texto or "").split(";"):
        partes = trozo.split(",")
        try:
            movidos.append((min(max(float(partes[0]), -500), 500),
                            min(max(float(partes[1]), -500), 500)))
        except (ValueError, IndexError):
            movidos.append((0.0, 0.0))
    return (movidos + [(0.0, 0.0)] * cuantos)[:cuantos]


def _pincho(cx: float, cy: float, z0: float, largo: float, grueso: float, angulo: float,
            espiga: float = 0.0, holgura: float = 0.0):
    """El gancho de las llaves -un palo con la punta redondeada para que la llave no se
    escape ni arañe- y, si va suelto, el hueco inclinado donde se clava.
    Clavado en la placa sale ya inclinado. Suelto sale recto y de pie, porque la inclinación
    la da el hueco: así se imprime sin soportes y al pegarlo cae solo en su ángulo."""
    radio = max(grueso, 1.0) / 2
    palo = trimesh.creation.cylinder(radius=radio, height=largo + espiga, sections=24)
    palo.apply_translation([0, 0, (largo - espiga) / 2])
    punta = trimesh.creation.icosphere(subdivisions=2, radius=radio)
    punta.apply_translation([0, 0, largo])
    gancho = _booleana(trimesh.boolean.union, [palo, punta], "formar el gancho")
    tumbar = trimesh.transformations.rotation_matrix(
        -math.radians(min(max(angulo, 0), 60)), (1, 0, 0))
    if not espiga:
        gancho.apply_transform(tumbar)
        gancho.apply_translation([cx, cy, z0])
        return gancho, None
    gancho.apply_translation([cx, cy, z0])
    hondo = espiga + holgura
    hueco = trimesh.creation.cylinder(radius=radio + holgura, height=hondo + 1, sections=24)
    hueco.apply_translation([0, 0, (1 - hondo) / 2])     # 1 mm de más por fuera, para cortar
    hueco.apply_transform(tumbar)
    hueco.apply_translation([cx, cy, z0])
    return gancho, hueco


def construir_cuadro(a: Parametros):
    """Cuadro de pared para las llaves: el apellido en grande, los de la casa en una fila
    debajo y un gancho bajo cada nombre."""
    familia = (a.cua_familia or "").strip()
    if not familia:
        raise ValueError("Falta el apellido de la familia.")
    if len(familia) > MAX_LETRAS_CUADRO:
        raise ValueError(f"El apellido admite como máximo {MAX_LETRAS_CUADRO} caracteres.")
    nombres = [n.strip() for n in re.split(r"[,\n]", a.cua_integrantes or "") if n.strip()]
    if len(nombres) > MAX_INTEGRANTES:
        raise ValueError(f"Como mucho {MAX_INTEGRANTES} nombres en la fila.")
    for n in nombres:
        if len(n) > MAX_LETRAS_CUADRO:
            raise ValueError(f"'{n}' es demasiado largo para la fila.")
    for c in (a.cua_color_placa, a.cua_color_familia, a.cua_color_integrantes,
              a.cua_color_adorno, a.cua_color_patron, a.cua_color_gancho, a.cua_color_titulo):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError(f"Color inválido '{c}', usa formato #RRGGBB.")
    if min(a.cua_alto_familia, a.cua_placa, a.cua_relieve) <= 0:
        raise ValueError("El alto del apellido, el grosor de la placa y el relieve deben ser "
                         "mayores que 0.")
    if nombres and a.cua_alto_integrantes <= 0:
        raise ValueError("La altura de los nombres debe ser mayor que 0.")
    espiga = max(a.cua_espiga, 0.0) if a.cua_aparte else 0.0
    holgura = min(max(a.cua_holgura, 0.0), 1.0) if espiga else 0.0
    if espiga and espiga + holgura > a.cua_placa - GROSOR_MINIMO:
        raise ValueError(f"Un hueco de {espiga + holgura:.1f} mm no cabe en una placa de "
                         f"{a.cua_placa:.1f} mm: sube el grosor de la placa o baja la hondura "
                         "del hueco.")

    # ---- el apellido, centrado en x = 0 y apoyado en y = 0
    letras = texto_a_poligono(familia, a.cua_fuente, 100)
    x0, y0, x1, y1 = letras.bounds
    escala = a.cua_alto_familia / (y1 - y0)
    letras = affinity.scale(letras, escala, escala, origin=(0, 0))
    x0, y0, x1, y1 = letras.bounds
    letras = affinity.translate(letras, -(x0 + x1) / 2, -y0)
    ancho_familia = x1 - x0
    alto_familia = y1 - y0

    # ---- la palabra pequeña de encima ("Familia")
    titulo = Polygon()
    palabra = (a.cua_titulo or "").strip()
    if palabra:
        if len(palabra) > MAX_LETRAS_CUADRO:
            raise ValueError(f"La palabra de arriba admite como máximo {MAX_LETRAS_CUADRO} "
                             "caracteres.")
        if a.cua_alto_titulo <= 0:
            raise ValueError("El alto de la palabra de arriba debe ser mayor que 0.")
        t = texto_a_poligono(palabra, a.cua_fuente, 100)
        tx0, ty0, tx1, ty1 = t.bounds
        e = a.cua_alto_titulo / (ty1 - ty0)
        t = affinity.scale(t, e, e, origin=(0, 0))
        tx0, ty0, tx1, ty1 = t.bounds
        titulo = affinity.translate(t, -(tx0 + tx1) / 2 + a.cua_titulo_x,
                                    alto_familia + a.cua_sep_titulo - ty0)

    # ---- adorno (antes que los nombres: la corona tiene que esquivarlo)
    partes_adorno = adorno_en_grupos(
        a.cua_adorno_svg, a.cua_adorno_alto, a.cua_adorno_giro,
        -ancho_familia / 2 + ancho_familia * a.cua_adorno_x / 100.0,
        alto_familia + a.cua_adorno_y,
        {"placa": a.cua_color_placa, "familia": a.cua_color_familia,
         "integrantes": a.cua_color_integrantes, "extra": a.cua_color_adorno},
        [a.cua_adorno_c1, a.cua_adorno_c2, a.cua_adorno_c3],
        a.cua_color_adorno) if a.cua_adorno else []
    adorno = unary_union([g for _, g in partes_adorno]) if partes_adorno else Polygon()

    # ---- los de la casa: en fila debajo, o en corona alrededor del apellido
    fila = _fila_de_nombres(a, nombres) if nombres else []
    if fila:
        if a.cua_ganchos and (a.cua_gancho_largo <= 0 or a.cua_gancho_grueso <= 0):
            raise ValueError("El gancho debe tener largo y grueso mayores que 0.")
        baja = max(a.cua_gancho_baja, 0)
        radio = a.cua_gancho_grueso / 2 + max(a.cua_margen, 0.5) if a.cua_ganchos else 0.0

        def sitio_gancho(p):
            """El redondel que necesita el gancho debajo del nombre (nada si no lleva)."""
            px0, py0, px1, _ = p.bounds
            return (Point((px0 + px1) / 2, py0 - baja).buffer(radio, quad_segs=12)
                    if radio else Polygon())

        sep = max(a.cua_separacion, 0)
        corona = (_nombres_alrededor(fila, unary_union([letras, titulo, adorno]), sep,
                                     max(a.cua_hueco, 0), sitio_gancho, max(a.cua_margen, 0.5))
                  if a.cua_alrededor and len(fila) > 1 else None)
        if corona:
            fila = corona
        else:
            tope = max(p.bounds[3] for p in fila)
            fila = [affinity.translate(p, 0, -sep - tope) for p in fila]
        # y encima, lo que el usuario haya arrastrado cada uno en la vista 3D
        fila = [affinity.translate(p, dx, dy) for p, (dx, dy)
                in zip(fila, _desplazamientos(a.cua_pos, len(fila)))]
    integrantes = unary_union(fila) if fila else Polygon()

    # ---- ganchos: uno bajo cada nombre, y la placa tiene que llegar hasta ellos
    sitios = []
    if a.cua_ganchos and fila:
        for p in fila:
            px0, py0, px1, _ = p.bounds
            sitios.append(((px0 + px1) / 2, py0 - max(a.cua_gancho_baja, 0)))

    # ---- silueta de la placa: todo lo que lleva encima, engordado y fundido
    encima = [letras.buffer(max(a.cua_margen, 0.5), join_style=1)]
    if not titulo.is_empty:
        encima.append(titulo.buffer(max(a.cua_margen, 0.5), join_style=1))
    if not integrantes.is_empty:
        encima.append(integrantes.buffer(max(a.cua_margen, 0.5), join_style=1))
    if not adorno.is_empty:
        encima.append(adorno.buffer(max(a.cua_margen, 0.5), join_style=1))
    radio_gancho = a.cua_gancho_grueso / 2 + max(a.cua_margen, 0.5)
    encima += [Point(x, y).buffer(radio_gancho, quad_segs=16) for x, y in sitios]
    s = max(a.cua_suave, 0)

    def contornear(trozos):
        """Funde todo en un contorno continuo: el cierre une los trozos sueltos y la
        apertura redondea las esquinas de fuera."""
        g = unary_union(trozos)
        if s:
            g = g.buffer(s, join_style=1).buffer(-2 * s, join_style=1).buffer(s, join_style=1)
        return g.simplify(0.08)

    placa = contornear(encima)
    if placa.is_empty:
        raise ValueError("La placa salió vacía. Revisa el margen y el suavizado.")

    # ---- agujeros para colgarlo (opcionales: hay quien prefiere cinta de doble cara). Van
    # en las dos esquinas de arriba, nunca por el medio: se parte de cada esquina del
    # rectángulo que encierra la placa y se entra hacia el centro hasta pisar material libre,
    # sin acercarse al relieve. Luego los dos bajan a la altura del más bajo -si no, el cuadro
    # colgaría torcido- y ahí se vuelven a abrir todo lo que pueden. La placa crece un poco
    # alrededor de cada uno, así que siempre quedan con su reborde
    agujeros, donde_colgar = Polygon(), []
    if a.cua_colgar and a.cua_colgar_diametro > 0:
        r = a.cua_colgar_diametro / 2
        aire = max(a.cua_margen, 0.5) / 2       # lo que respetan al borde y a las letras
        estorbo = unary_union([letras, titulo, integrantes, adorno]).buffer(r + aire,
                                                                           join_style=1)
        px0, py0, px1, py1 = placa.bounds
        def buscar(x, y, dx, dy):
            """Entra desde la esquina en esa dirección hasta pisar placa libre de relieve."""
            for _ in range(600):
                p = Point(x, y)
                if placa.contains(p) and not estorbo.intersects(p):
                    return x, y
                x, y = x + dx, y + dy
            return None

        medio_x, medio_y = (px0 + px1) / 2, (py0 + py1) / 2
        esquinas = []
        for x_ini in (px0 + r + aire, px1 - r - aire):
            y_ini = py1 - (r + aire)
            dx, dy = medio_x - x_ini, medio_y - y_ini
            paso = math.hypot(dx, dy) or 1.0
            sitio = buscar(x_ini, y_ini, dx / paso, dy / paso)
            if sitio:
                esquinas.append(sitio)
        if len(esquinas) == 2:
            y = min(c[1] for c in esquinas)      # nivelados, o colgaría torcido
            nivelados = []
            for x_ini, hacia in ((px0 + r + aire, 1.0), (px1 - r - aire, -1.0)):
                sitio = buscar(x_ini, y, hacia, 0.0)
                if sitio:
                    nivelados.append(sitio)
            if len(nivelados) == 2 and nivelados[1][0] - nivelados[0][0] > 4 * r:
                encima += [Point(x, y).buffer(r + max(a.cua_margen, 0.5), quad_segs=24)
                           for x, y in nivelados]
                placa = contornear(encima)       # la placa crece para recibirlos
                agujeros = unary_union([Point(x, y).buffer(r, quad_segs=24)
                                        for x, y in nivelados])
                placa = placa.difference(agujeros)
                donde_colgar = nivelados

    # ---- patrón repartido dentro del apellido
    deco = Polygon()
    if a.cua_patron:
        zona = letras.buffer(-max(a.cua_margen_patron, 0))
        if not zona.is_empty:
            deco = repartir_patron(zona, a.cua_patron_svg, a.cua_tam_patron,
                                   a.cua_separacion_patron, a.cua_semilla, a.cua_girar_patron)

    # ---- regiones: la placa abajo y encima cada color en su banda de altura. Si se
    # imprimen sueltas, cada pieza crece una espiga hacia dentro y la placa se vacía su
    # silueta con holgura, así al pegarlas caen solas en su sitio y no hay que alinear a ojo
    suelo, techo = a.cua_placa, a.cua_placa + a.cua_relieve
    relieve = [("Familia", letras.difference(deco), techo, a.cua_color_familia),
               ("Titulo", titulo, techo, a.cua_color_titulo)]
    # cada nombre, su propia pieza: así se puede arrastrar por separado en la vista 3D
    relieve += [(f"Nombre {i}", p, techo, a.cua_color_integrantes)
                for i, p in enumerate(fila, 1)]
    if not a.cua_patron_corta:      # encima de la letra y en su color; si no, queda ahuecada
        relieve.append(("Patron", deco, techo + max(a.cua_patron_relieve, 0),
                        a.cua_color_patron))
    varios = len(partes_adorno) > 1
    for i, (color, g) in enumerate(partes_adorno, 1):
        relieve.append((f"Adorno {i}" if varios else "Adorno", g, techo, color))
    relieve = [r for r in relieve if not r[1].is_empty]

    if espiga:
        hondo = espiga + holgura
        bolsa = unary_union([g for _, g, _, _ in relieve]).buffer(holgura, join_style=1)
        mallas = extruir(placa, suelo - hondo, 0.0) + \
            extruir(placa.difference(bolsa), hondo, suelo - hondo)
    else:
        mallas = extruir(placa, suelo, 0.0)
    cuerpo = trimesh.util.concatenate(mallas)

    # ---- los ganchos, y el hueco inclinado que le abren a la placa si van sueltos
    pinchos, huecos = [], []
    for x, y in sitios:
        gancho, hueco = _pincho(x, y, suelo if espiga else suelo - 0.6, a.cua_gancho_largo,
                                a.cua_gancho_grueso, a.cua_gancho_angulo, espiga, holgura)
        pinchos.append(gancho)      # uno por nombre, para que le siga cuando lo arrastran
        if hueco is not None:
            huecos.append(hueco)
    if huecos:
        cuerpo = _booleana(trimesh.boolean.difference, [cuerpo] + huecos,
                           "los huecos de los ganchos")

    niveles = [("Placa", a.cua_color_placa, cuerpo)]
    for nombre, region, z1, color in relieve:
        trozos = extruir(region, z1 - suelo + espiga, suelo - espiga)
        if trozos:
            niveles.append((nombre, color, trimesh.util.concatenate(trozos)))
    for i, gancho in enumerate(pinchos, 1):
        niveles.append((f"Gancho {i}", a.cua_color_gancho, gancho))
    if len(niveles) < 2:
        raise ValueError("No se generó geometría. Revisa los parámetros.")

    if espiga:      # cada pieza al lado de la placa y apoyada en la mesa, lista de imprimir
        sueltas = [m for n, _, m in niveles if n != "Placa"]
        dy = placa.bounds[1] - HUECO_APARTE - max(m.bounds[1][1] for m in sueltas)
        dz = -min(m.bounds[0][2] for m in sueltas)
        for m in sueltas:
            m.apply_translation([0, dy, dz])
    # la huella que se mide es la de la placa: sueltas, las piezas se imprimen de una en una
    regiones = [("Placa", placa, 0.0, suelo, a.cua_color_placa)] + \
               [(n, g, suelo - espiga, z, c) for n, g, z, c in relieve]
    analisis = _analizar(niveles, placa, regiones, len(partes_adorno))
    analisis["colgar"] = [[round(x, 2), round(y, 2)] for x, y in donde_colgar]
    if sitios:
        analisis["avisos"].append(
            "Los ganchos salen rectos y de pie: se imprimen sin soportes y al pegarlos el "
            "hueco inclinado les da el ángulo." if espiga else
            "Los ganchos salen hacia fuera: imprime el cuadro tumbado, con la cara buena "
            "hacia arriba, y no hacen falta soportes.")
    if espiga:
        analisis["avisos"].append(
            f"Cada color sale suelto y apoyado en la mesa, al lado de la placa: imprímelo con "
            f"su filamento y pégalo en su hueco ({espiga:.1f} mm de hondura y {holgura:.1f} mm "
            "de holgura).")
    if a.cua_patron and deco.is_empty:
        analisis["avisos"].append("No cupo ningún motivo dentro de las letras: baja el tamaño "
                                  "del motivo o su margen, o sube el alto del apellido.")
    if a.cua_colgar and agujeros.is_empty:
        analisis["avisos"].append("No cupieron los agujeros para colgarlo: sube el margen o "
                                  "baja su diámetro.")
    return niveles, analisis
