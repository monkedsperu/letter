#!/usr/bin/env python3
"""
Monkeds Letter: genera 3MF a color (una pieza por filamento) de cuatro diseños distintos.

    1. llavero      letra inicial con borde + texto en tres niveles de relieve
    2. organizador  cuerpo con la forma del nombre, portamóvil, vaso y bandeja
    3. cuadro       placa de pared para las llaves, con un gancho por nombre
    4. marcapáginas lámina con nombre, letra grande y un icono arriba

Este archivo es la fachada: reparte el trabajo entre los módulos de cada diseño y ofrece
la línea de órdenes. La geometría vive en comun.py y en diseno_*.py.

Instalación:
    pip install trimesh shapely matplotlib numpy mapbox_earcut svgelements manifold3d

Uso por consola (solo el diseño de llavero):
    python generador_stl.py --inicial M --texto "aria"

Pantalla web:
    python app.py

Fuentes: nombre de fuente instalada, ruta a un .ttf/.otf, o un archivo copiado en la
carpeta "fuentes" junto a este script. Patrones y adornos son SVG de sus carpetas.
Todas las medidas están en milímetros.
"""
import argparse

import trimesh
from shapely.errors import GEOSException

from comun import (APP, AQUI, CAMA_TIPICA, CARPETA_ADORNOS, CARPETA_FUENTES,  # noqa: F401
                   CARPETA_PATRONES, CONTACTO, MARCA, VERSION,
                   _borde_que_une, _poligonos, adornos_disponibles, cargar_fuente,
                   exportar_3mf, exportar_stl, exportar_stl_por_color, extruir,
                   fuentes_instaladas, grupos_adorno, miniatura_png, patrones_disponibles,
                   svg_a_poligono, svg_dentro_de, svgs_en, texto_a_poligono)
from diseno_cuadro import construir_cuadro
from diseno_llavero import _construir_llavero
from diseno_marca import construir_marca
from diseno_organizador import construir_organizador
from parametros import MAX_LETRAS, Parametros, parametros_desde_dict  # noqa: F401

DISENOS = {"nombre": _construir_llavero, "organizador": construir_organizador,
           "cuadro": construir_cuadro, "marca": construir_marca}


def construir_con_analisis(a: Parametros):
    """Devuelve ([(nombre, color, malla)], analisis) del diseño que pida `a.tipo`.
    Unas medidas disparatadas pueden reventar dentro de la librería de geometría; eso es
    culpa de lo que se pidió, no un fallo del programa, así que sale como aviso al usuario."""
    hacer = DISENOS.get(a.tipo)
    if hacer is None:
        raise ValueError(f"Tipo de diseño desconocido: {a.tipo}")
    try:
        return hacer(a)
    except GEOSException as e:
        raise ValueError("Con esas medidas no sale una figura válida: revisa los tamaños, "
                         "los bordes y las posiciones.") from e


def construir(a: Parametros):
    """Solo las mallas (para la consola y para quien no necesite el análisis)."""
    return construir_con_analisis(a)[0]


def main():
    d = Parametros()
    p = argparse.ArgumentParser(
        description=f"{MARCA}: genera un 3MF a color con letra inicial + texto.")
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
    p.add_argument("--adorno-detras", action="store_true",
                   help="El adorno pasa por detrás de la letra (la letra lo corta)")
    p.add_argument("--no-cortar-adorno", dest="cortar_adorno", action="store_false",
                   help="El adorno se funde con la letra en vez de cortarla")
    p.add_argument("--color-adorno", default=d.color_adorno, help="El color extra (el 4º)")
    for n in (1, 2, 3):
        p.add_argument(f"--adorno-c{n}", choices=["base", "letra", "texto", "extra"],
                       default=getattr(d, f"adorno_c{n}"),
                       help=f"A qué color de la paleta va el grupo {n} del adorno")
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
