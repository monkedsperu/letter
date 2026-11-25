# -*- coding: utf-8 -*-
"""Diseño 2: el organizador de escritorio. Un cuerpo con la forma del nombre y, delante,
portamóvil, vaso para lápices y bandeja para clips."""
import math
import re

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import transform as shapely_transform, unary_union

from comun import (APOYO, HUECO_APARTE, HUECO_MINIMO, SOBRA, _analizar, _booleana,
                   _borde_que_une, _circulo, _extruido, _poligonos, _tumbado,
                   adorno_en_grupos, apartar_por_color, texto_a_poligono)
from parametros import Parametros

MAX_LETRAS_ORG = 20
HOLGURA_BANDEJA = 1.5  # aire que se deja entre el borde de la bandeja y las letras (mm)

def _revisar_organizador(a: Parametros) -> str:
    """Comprueba lo que no depende de la geometría y devuelve el nombre ya limpio."""
    texto = (a.org_texto or "").strip()
    if not texto:
        raise ValueError("Falta el nombre del organizador.")
    if len(texto) > MAX_LETRAS_ORG:
        raise ValueError(f"El nombre admite como máximo {MAX_LETRAS_ORG} caracteres.")
    for c in (a.org_color_cuerpo, a.org_color_nombre, a.org_color_borde, a.org_color_adorno):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise ValueError(f"Color inválido '{c}', usa formato #RRGGBB.")
    if min(a.org_alto, a.org_fondo, a.org_relieve) <= 0:
        raise ValueError("El alto, el fondo y el relieve del nombre deben ser mayores que 0.")
    return texto


def _nombre_a_su_medida(a: Parametros, texto: str):
    """El nombre escalado a su altura, con la letra más baja apoyada sobre la franja de base
    y empezando en x = 0."""
    nombre = texto_a_poligono(texto, a.org_fuente, 100)
    x0, y0, x1, y1 = nombre.bounds
    escala = a.org_alto / (y1 - y0)
    nombre = affinity.scale(nombre, escala, escala, origin=(0, 0))
    x0, y0, _, _ = nombre.bounds
    return affinity.translate(nombre, -x0, max(a.org_base, 0) - y0)


def _silueta_del_cuerpo(a: Parametros, visible, colinas):
    """El cuerpo visto de frente: el nombre engordado, más las repisas que pida algún
    módulo, todo fundido en un contorno continuo y con el apoyo bien plano."""
    silueta = unary_union([visible.buffer(max(a.org_margen, 0.5), join_style=1)] + colinas)
    bx0, _, bx1, bz1 = silueta.bounds
    silueta = silueta.union(box(bx0, 0, bx1, max(a.org_base, 1.0)))
    s = max(a.org_suave, 0)
    if s:   # cierre: rellena los valles entre letras. apertura: redondea las esquinas de fuera
        silueta = silueta.buffer(s, join_style=1).buffer(-2 * s, join_style=1).buffer(s, join_style=1)
    # suelo plano: ni el redondeo ni las repisas pueden meterse por debajo de la mesa
    silueta = silueta.intersection(box(bx0 - s - 1, 0, bx1 + s + 1, bz1 + s + 1))
    if silueta.is_empty:
        raise ValueError("La silueta salió vacía. Revisa el margen y el suavizado.")
    # tanto redondeo deja miles de puntos y el canto los multiplica por cada escalón:
    # a décima de milímetro no se nota y la malla baja mucho de tamaño
    silueta = silueta.simplify(0.1)
    # el apoyo tiene que ser una sola cara plana: lo que el simplificado dejó a unas centésimas
    # de la mesa baja a cero, o el laminador se encuentra la base a dos alturas
    silueta = shapely_transform(lambda x, y: (x, np.where(y < 0.25, 0.0, y)), silueta)
    # y nada que casi toque la mesa puede quedar flotando: el último milímetro de silueta se
    # estira hacia abajo, así que apoya en todo su ancho. Lo que esté más alto sigue siendo arco.
    sx0, _, sx1, sz1 = silueta.bounds
    banda = silueta.intersection(box(sx0 - 1, 0, sx1 + 1, APOYO))
    if not banda.is_empty:
        silueta = silueta.union(affinity.scale(banda, 1.0, 50.0, origin=(0, APOYO)))
        silueta = silueta.intersection(box(sx0 - 1, 0, sx1 + 1, sz1 + 1))
    return silueta


def _cerrar_el_cuerpo(cuerpo, anadidos, cortes):
    """Pega los módulos, vacía los huecos, deja la base a ras de mesa y comprueba que cierra."""
    if anadidos:
        cuerpo = _booleana(trimesh.boolean.union, [cuerpo] + anadidos, "pegar los módulos al cuerpo")
    if cortes:
        cuerpo = _booleana(trimesh.boolean.difference, [cuerpo] + cortes, "vaciar los módulos")
    if cuerpo.bounds[0][2] < -1e-3:   # alguna garganta se asomó por debajo de la mesa
        (mx0, my0, mz0), (mx1, my1, _) = cuerpo.bounds.tolist()
        losa = trimesh.creation.box((mx1 - mx0 + 20, my1 - my0 + 20, -mz0 + 10))
        losa.apply_translation([(mx0 + mx1) / 2, (my0 + my1) / 2, (mz0 - 10) / 2])
        cuerpo = _booleana(trimesh.boolean.difference, [cuerpo, losa], "aplanar la base")
    if not cuerpo.is_watertight:
        raise ValueError("El cuerpo salió con agujeros: prueba a cambiar el canto o el suavizado.")
    return cuerpo


def _tumbar_las_letras(letras, cuerpo):
    """Para imprimirlas aparte: de cara arriba, apoyadas en la mesa y al lado del cuerpo,
    y cada color en su propio sitio, que es lo que se imprime por separado."""
    tumbar = trimesh.transformations.rotation_matrix(-math.pi / 2, (1, 0, 0))
    for _, _, _, m in letras:
        m.apply_transform(tumbar)
    # al tumbarlas quedan delante del cuerpo y mirando abajo: se bajan y se apartan
    dy = cuerpo.bounds[0][1] - HUECO_APARTE - max(m.bounds[1][1] for _, _, _, m in letras)
    for _, _, _, m in letras:
        m.apply_translation([0, dy, 0])
    apartar_por_color([(n, c, m) for n, c, _, m in letras],
                      cuerpo.bounds[0][0] - HUECO_APARTE)


def _avisos_del_organizador(a: Parametros, analisis, cuerpo, puesto, visible, borde, cima, ancho):
    """Lo que conviene saber antes de imprimir. Nada de esto impide generar la pieza."""
    avisos = analisis["avisos"]
    if a.org_aparte:
        avisos.append(f"Cada color sale suelto y tumbado al lado del cuerpo: imprímelo con "
                      f"su filamento y pégalo en su hueco "
                      f"({max(a.org_hueco, HUECO_MINIMO):.1f} mm de hondura y "
                      f"{min(max(a.org_holgura, 0.0), max(a.org_margen, 1.0) / 2):.1f} mm "
                      "de holgura).")
        sueltas = len(_poligonos(visible))
        if sueltas > 1:
            une = _borde_que_une(puesto, borde)
            consejo = (f" Con un borde de {une:.1f} mm saldría de una pieza." if une else
                       " Las palabras están demasiado separadas para unirlas con el borde.")
            avisos.append(f"El nombre son {sueltas} trozos sueltos, a pegar uno a uno.{consejo}")
    else:
        avisos.append("El nombre sobresale de una cara vertical: imprime la pieza tumbada sobre "
                      "su parte de atrás, activa los soportes, o marca \"imprimir aparte\".")
    if cima > cuerpo.bounds[1][2] + 0.1:
        avisos.append("El nombre asoma por encima del cuerpo: sube el margen o baja su alto.")
    if cuerpo.bounds[1][0] - cuerpo.bounds[0][0] > 1.8 * ancho:
        avisos.append("Los módulos son bastante más anchos que el nombre y el cuerpo crece "
                      "mucho: muévelos o hazlos más pequeños.")


def construir_organizador(a: Parametros):
    """Organizador de escritorio: el nombre en relieve sobre un cuerpo con su misma silueta,
    con soporte para el móvil, vaso de lápices y bandeja de clips."""
    texto = _revisar_organizador(a)
    pared = max(a.org_pared, 0.8)
    canto = max(min(a.org_canto, a.org_fondo / 4), 0.0)
    garganta = -canto                      # las uniones nacen en curva, no a escuadra
    pasos = max(1, min(int(a.org_canto_pasos), 64))
    borde_ancho = max(a.org_borde, 0.0)
    engordar = lambda g: g.buffer(borde_ancho, join_style=1) if borde_ancho else g

    nombre = _nombre_a_su_medida(a, texto)
    x0, _, x1, _ = nombre.bounds
    ancho = x1 - x0
    visible = engordar(nombre)             # lo que se ve y lo que el cuerpo tiene que tapar

    def en(pct, semi):
        """Centro de un módulo de medio ancho `semi`: 0 lo deja pegado al principio del
        nombre y 100 al final, así que entre medias nunca sobra cuerpo por los lados.
        Si el módulo es más ancho que el nombre, se queda centrado."""
        libre = ancho - 2 * semi
        return x0 + ancho / 2 if libre <= 0 else x0 + semi + libre * pct / 100.0

    def suelo_de_la_cara(xa, xb, por_defecto):
        """Por dónde baja lo que hay en la cara entre dos x. Así la bandeja se pega al nombre
        y baja ella sola cuando encima hay una g, una j o una p con rabito."""
        trozo = visible.intersection(box(xa, 0, xb, 1e4))
        return por_defecto if trozo.is_empty else trozo.bounds[1]

    # La bandeja va pegada al nombre. Si en su tramo no hay sitio debajo, el nombre sube lo
    # justo: con una g o una j se queda abajo, y sin ellas no se encarama de más.
    if a.org_bandeja and a.org_bandeja_alto <= 0:
        medio = a.org_bandeja_ancho / 2
        cx = en(a.org_bandeja_x, medio)
        falta = (a.org_bandeja_hondo + pared + HOLGURA_BANDEJA) - suelo_de_la_cara(
            cx - medio, cx + medio, 1e4)
        if falta > 0:
            nombre = affinity.translate(nombre, 0, falta)

    # El adorno va en la cara como una letra más: comparte relieve y entra en el mismo hueco,
    # pero su borde es cosa suya (por defecto no lleva: el del texto no tiene por qué
    # rodearlo). Se coloca tras mover el nombre, porque su altura se mide desde la mesa y no
    # desde las letras.
    partes_adorno = adorno_en_grupos(
        a.org_adorno_svg, a.org_adorno_alto, a.org_adorno_giro,
        x0 + ancho * a.org_adorno_x / 100.0, a.org_adorno_y,
        {"cuerpo": a.org_color_cuerpo, "nombre": a.org_color_nombre,
         "borde": a.org_color_borde, "extra": a.org_color_adorno},
        [a.org_adorno_c1, a.org_adorno_c2, a.org_adorno_c3],
        a.org_color_adorno, ("extra", "cuerpo", "nombre"),
        (a.org_adorno_tinta1, a.org_adorno_tinta2, a.org_adorno_tinta3)) \
        if a.org_adorno else []
    adorno = unary_union([g for _, g in partes_adorno]) if partes_adorno else Polygon()
    puesto = nombre.union(adorno) if not adorno.is_empty else nombre
    borde_adorno = max(a.org_adorno_borde, 0.0)
    visible = engordar(nombre)
    if not adorno.is_empty:
        visible = visible.union(adorno.buffer(borde_adorno, join_style=1)
                                if borde_adorno else adorno)
    cima_cara = visible.bounds[3]

    # ---- silueta: solo la ranura del móvil pide repisa, porque necesita cuerpo donde
    # apoyarse; el vaso ya no, que es un cilindro aparte
    colinas = []
    if a.org_movil:
        if a.org_movil_suelo < pared:
            raise ValueError("El apoyo del móvil debe quedar por encima del grosor de pared.")
        if a.org_movil_grueso + 2 * pared > a.org_fondo:
            raise ValueError("La ranura del móvil no cabe: sube el fondo o baja el grueso.")
        cx = en(a.org_movil_x, a.org_movil_ancho / 2 + pared)
        colinas.append(box(cx - a.org_movil_ancho / 2 - pared, 0,
                           cx + a.org_movil_ancho / 2 + pared, a.org_movil_suelo + 4 * pared))
    silueta = _silueta_del_cuerpo(a, visible, colinas)

    def cima(xa, xb):
        """Lo alto que es el cuerpo entre dos x: desde ahí se cavan los huecos de arriba."""
        trozo = silueta.intersection(box(xa, 0, xb, 1e4))
        return 0.0 if trozo.is_empty else trozo.bounds[3]

    # ---- piezas que se suman al cuerpo y huecos que se le restan
    cortes, anadidos, avisos = [], [], []

    vaso_fuera, x_vaso = None, (0.0, 0.0)
    if a.org_vaso:
        if not 0 < a.org_vaso_hondo < a.org_vaso_alto:
            raise ValueError("El vaso debe ser menos hondo que su altura: si no, no tiene fondo.")
        if a.org_vaso_diametro + 2 * pared > a.org_fondo:
            raise ValueError("El vaso no cabe: sube el fondo o baja el diámetro.")
        if a.org_vaso_alto - a.org_vaso_hondo < pared:
            raise ValueError("Al vaso no le queda fondo: baja la hondura o sube el alto.")
        radio = a.org_vaso_diametro / 2
        cx = en(a.org_vaso_x, radio + pared)
        x_vaso = (cx - radio - pared, cx + radio + pared)
        # el vaso es un cilindro de verdad: lo que asoma por encima del cuerpo se ve redondo,
        # y nace del cuerpo en garganta en vez de a escuadra
        vaso_fuera = _extruido(_circulo(cx, a.org_fondo / 2, radio + pared), a.org_vaso_alto,
                               garganta, canto, "el vaso", pasos)
        anadidos.append(vaso_fuera)
        hueco = _extruido(_circulo(cx, a.org_fondo / 2, radio), a.org_vaso_hondo + SOBRA,
                          canto, 0.0, "el hueco del vaso", pasos)
        hueco.apply_translation([0, 0, a.org_vaso_alto - a.org_vaso_hondo])
        cortes.append(hueco)

    if a.org_movil:
        medio, suelo = a.org_movil_ancho / 2, a.org_movil_suelo
        cx = en(a.org_movil_x, medio + pared)
        perfil = box(cx - medio, 0, cx + medio, cima(cx - medio, cx + medio) - suelo + SOBRA)
        ranura = _tumbado(_extruido(perfil, a.org_movil_grueso, canto, canto, "la ranura", pasos),
                          (a.org_fondo + a.org_movil_grueso) / 2)
        ranura.apply_translation([0, 0, suelo])
        if a.org_movil_angulo:   # se inclina hacia atrás girando sobre su propio fondo
            ranura.apply_transform(trimesh.transformations.rotation_matrix(
                -math.radians(a.org_movil_angulo), (1, 0, 0), (cx, a.org_fondo / 2, suelo)))
        if vaso_fuera is not None and cx - medio < x_vaso[1] and x_vaso[0] < cx + medio:
            # se pisan: la ranura se para en la pared del vaso en vez de partirlo
            ranura = _booleana(trimesh.boolean.difference, [ranura, vaso_fuera],
                               "apartar la ranura del vaso")
            avisos.append("La ranura del móvil y el vaso se pisan: muévelos o hazlos "
                          "más pequeños.")
        cortes.append(ranura)

    if a.org_bandeja:
        fondo_b, w = a.org_bandeja_fondo, a.org_bandeja_ancho
        cx = en(a.org_bandeja_x, w / 2)
        alto = a.org_bandeja_alto
        if alto <= 0:    # automático: pegada al nombre, y más baja si ahí hay un rabito
            alto = suelo_de_la_cara(cx - w / 2, cx + w / 2,
                                    a.org_base + a.org_alto / 3) - HOLGURA_BANDEJA
            # no puede ser más baja que su propio hueco. La milésima de margen es porque el
            # nombre se ha subido justo lo necesario y el redondeo deja el cálculo al filo.
            if alto < a.org_bandeja_hondo + pared - 1e-3:
                alto = a.org_bandeja_hondo + pared
                avisos.append("La bandeja llega a las letras de ese tramo: muévela, bájale la "
                              "hondura o sube el alto del nombre.")
        if not 0 < a.org_bandeja_hondo < alto:
            raise ValueError("La bandeja no cabe bajo el nombre: baja su hondura, baja la base "
                             "del cuerpo o ponle una altura a mano.")
        if min(w, fondo_b) <= 2 * pared:
            raise ValueError("La bandeja es más pequeña que sus propias paredes.")
        # el perfil se redondea con MÁS radio que el canto: así las aristas largas quedan
        # suaves y, al rematar la punta, la esquina no acaba en pico
        redondeo = min(2 * canto, (alto - 1) / 2, w / 4)
        redondear = lambda g: (g.buffer(-redondeo, join_style=1).buffer(redondeo, join_style=1)
                               if redondeo > 0 else g)
        caja = redondear(box(cx - w / 2, 0, cx + w / 2, alto))
        anadidos.append(_tumbado(_extruido(caja, fondo_b, garganta, canto, "la bandeja",
                                           pasos, suelo=0.0)))
        dentro = redondear(box(cx - w / 2 + pared, -fondo_b + pared, cx + w / 2 - pared, -pared))
        vaciado = _extruido(dentro, a.org_bandeja_hondo + SOBRA, canto, 0.0,
                            "el hueco de la bandeja", pasos)
        vaciado.apply_translation([0, 0, alto - a.org_bandeja_hondo])
        cortes.append(vaciado)

    # Suelto, el nombre encaja en un hueco del cuerpo, así no hay que alinearlo a ojo al
    # pegarlo: le crece una espiga por detrás y al cuerpo se le caja su silueta con holgura.
    # Por debajo del mínimo el hueco no se aprecia en la vista 3D ni sujeta bien, así que se
    # sube solo: las generaciones viejas con menos se rehacen con este.
    espiga = max(a.org_hueco, HUECO_MINIMO) if a.org_aparte else 0.0
    holgura = min(max(a.org_holgura, 0.0), max(a.org_margen, 1.0) / 2)
    if espiga:
        if espiga + holgura > a.org_fondo - pared:
            raise ValueError("El hueco del nombre es más hondo que el cuerpo: baja su hondura.")
        # el hueco va a escuadra, sin redondear: tiene que copiar la espiga, y un canto vivo
        # se distingue en pantalla mucho mejor que una garganta
        caja = _extruido(visible.buffer(holgura, join_style=1), espiga + holgura,
                         que="el hueco del nombre")
        cortes.append(_tumbado(caja, espiga + holgura))

    # ---- el sólido, y la cara aparte: una pieza por color
    cuerpo = _cerrar_el_cuerpo(
        _tumbado(_extruido(silueta, a.org_fondo, canto, canto, "el cuerpo", pasos, suelo=0.0),
                 a.org_fondo), anadidos, cortes)

    def en_relieve(etiqueta, color, plano):
        return (etiqueta, color, plano,
                _tumbado(_extruido(plano, a.org_relieve + espiga, que=etiqueta), espiga))

    letras = [en_relieve("Nombre", a.org_color_nombre, nombre)]
    for i, (color, g) in enumerate(partes_adorno, 1):
        letras.append(en_relieve(f"Adorno {i}" if len(partes_adorno) > 1 else "Adorno", color, g))
    if borde_ancho or borde_adorno:
        letras.append(en_relieve("Borde", a.org_color_borde, visible.difference(puesto)))
    if a.org_aparte:
        _tumbar_las_letras(letras, cuerpo)

    niveles = [("Cuerpo", a.org_color_cuerpo, cuerpo)] + [(n, c, m) for n, c, _, m in letras]
    (tx0, ty0, _), (tx1, ty1, _) = trimesh.util.concatenate(
        [m for _, _, m in niveles]).bounds.tolist()
    analisis = _analizar(niveles, box(tx0, ty0, tx1, ty1),
                         [("Cuerpo", silueta)] + [(n, g) for n, _, g, _ in letras],
                         [c for c, _ in partes_adorno])
    analisis["avisos"] += avisos
    _avisos_del_organizador(a, analisis, cuerpo, puesto, visible, borde_ancho, cima_cara, ancho)
    analisis["ancho_base"] = round(ancho, 2)      # a lo que se refiere el % del adorno
    return niveles, analisis
