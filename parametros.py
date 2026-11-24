# -*- coding: utf-8 -*-
"""Los parámetros de los cuatro diseños, en un solo sitio: lo que viaja entre la pantalla
y el generador. Cada diseño usa los suyos, con su prefijo (org_, cua_, mar_)."""
from dataclasses import dataclass, fields

MAX_LETRAS = 6

@dataclass
class Parametros:
    tipo: str = "nombre"   # nombre (llavero) | organizador | cuadro (llaves) | marca
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
    curva_texto: float = 0.0       # arco en grados: 0 = recto, + hacia arriba, - hacia abajo
    posicion: str = "sobre"        # sobre | arriba | derecha
    separacion: float = 5.0        # separación letra-texto (arriba / derecha)
    texto_x: float = 0.0           # desplazamiento fino del texto (se mueve arrastrando)
    texto_y: float = 0.0
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
    cortar_adorno: bool = True     # True = deja un borde de separación entre adorno y letra
    adorno_detras: bool = False    # True = el adorno pasa por detrás y la letra lo corta
    # El SVG solo sirve para separar las formas: el color sale de la paleta del llavero,
    # así nunca se pasa de 4 filamentos. Cada grupo va a "letra", "texto" o "extra".
    adorno_c1: str = "extra"
    adorno_c2: str = "letra"
    adorno_c3: str = "texto"
    color_adorno: str = "#8a5a33"  # el color "extra", el cuarto del llavero
    # Aro para llavero: anillo plano pegado a la letra, con el grosor del nivel 1
    aro: bool = False
    aro_diametro: float = 17.0     # diámetro exterior (mm)
    aro_agujero: float = 7.0       # diámetro del agujero (mm)
    aro_x: float = 0.0             # centro del aro en mm desde el centro de la letra
    aro_y: float = 50.0
    # Hueco para imán: bolsillo abierto por abajo, dentro del nivel 1
    iman: bool = False
    iman_diametro: float = 10.0
    iman_hondo: float = 2.0        # debe ser menor que alto_nivel1
    iman_x: float = 0.0
    iman_y: float = 0.0
    # Acabado
    chaflan: float = 0.0           # bisel en el canto superior de cada capa (mm); 0 = canto recto

    # ---------------- Diseño 2: organizador de escritorio ----------------
    # El cuerpo es un prisma con la silueta del nombre; los módulos se restan (vaso, ranura)
    # o se suman (bandeja). Cada módulo levanta su propia "colina" en la silueta, así que
    # el cuerpo siempre crece lo justo para alojarlo y el suavizado lo funde con las letras.
    org_texto: str = "Ned Stark"
    org_fuente: str = "Pacifico"
    org_alto: float = 45.0         # altura del nombre, de la letra más alta a la más baja (mm)
    org_relieve: float = 5.0       # cuánto sobresale el nombre de la cara delantera (mm)
    org_fondo: float = 70.0        # profundidad del organizador (mm)
    org_margen: float = 8.0        # cuerpo que sobra alrededor de las letras (mm)
    org_suave: float = 4.0         # redondeo: funde letras y módulos en una silueta continua
    org_base: float = 6.0          # cuerpo por debajo de la letra más baja (mm)
    org_canto: float = 2.0         # redondeo de los cantos (mm); 0 = canto vivo
    org_canto_pasos: int = 16      # escalones del redondeo; con 16 cada uno mide una capa
    org_pared: float = 4.0         # grosor de pared de los módulos (mm)
    org_color_cuerpo: str = "#2b2b2b"
    org_color_nombre: str = "#f2f2f2"
    org_borde: float = 3.0         # contorno alrededor de las letras (mm); 0 = sin borde
    org_color_borde: str = "#d63a2f"
    org_aparte: bool = False       # el nombre sale tumbado al lado, para pegarlo después
    org_hueco: float = 4.0         # hondura del hueco donde encaja el nombre suelto (mm)
    # Adorno: un SVG de la carpeta "adornos" puesto en la cara, al lado del nombre
    org_adorno: bool = False
    org_adorno_svg: str = "desktop/lapiz.svg"
    org_adorno_alto: float = 52.0  # alto del adorno (mm)
    org_adorno_x: float = 107.0    # % del ancho del nombre; pasado de 100 se sale por la derecha
    org_adorno_y: float = 8.0      # altura de su base, desde la mesa (mm)
    org_adorno_giro: float = -18.0
    # Como en el llavero: el SVG solo separa las formas y el color sale de la paleta de la
    # pieza, así que nunca se pasa de 4 filamentos. Cada grupo va a cuerpo, nombre, borde
    # o al color extra.
    org_adorno_c1: str = "extra"
    org_adorno_c2: str = "nombre"
    org_adorno_c3: str = "borde"
    org_color_adorno: str = "#e8b43a"
    org_holgura: float = 0.3       # aire alrededor del nombre para que entre en su hueco (mm)
    # Soporte para el móvil: ranura en lo alto del cuerpo. Medidas de un móvil corriente con funda.
    org_movil: bool = True
    org_movil_x: float = 0.0       # 0 = pegado al principio del nombre, 100 = al final
    org_movil_ancho: float = 84.0  # largo de la ranura (mm) = ancho del móvil + holgura
    org_movil_grueso: float = 14.0 # ancho de la ranura (mm) = grosor del móvil con funda
    org_movil_suelo: float = 20.0  # altura a la que apoya el móvil (mm); la ranura sube hasta arriba
    org_movil_angulo: float = 8.0  # inclinación hacia atrás (grados)
    # Vaso para lápices: agujero cilíndrico desde arriba.
    org_vaso: bool = True
    org_vaso_x: float = 100.0
    org_vaso_diametro: float = 52.0
    org_vaso_alto: float = 72.0    # altura del borde del vaso (mm)
    org_vaso_hondo: float = 58.0   # hondura del vaso, desde el borde (mm)
    # Bandeja de clips: cajón que sale por delante, bajo el nombre.
    org_bandeja: bool = True
    org_bandeja_x: float = 50.0
    org_bandeja_ancho: float = 72.0
    org_bandeja_fondo: float = 42.0 # cuánto sale hacia delante (mm)
    org_bandeja_alto: float = 0.0   # altura del borde (mm); 0 = justo debajo del nombre
    org_bandeja_hondo: float = 10.0 # hondura de la bandeja, desde el borde (mm)

    # ---------------- Diseño 3: cuadro para colgar llaves ----------------
    # Una placa plana que se cuelga en la pared: arriba el apellido en relieve, debajo una
    # fila con los de la casa, y bajo cada uno su pincho para las llaves.
    cua_familia: str = "Medina"
    cua_titulo: str = "Familia"         # palabra pequeña sobre el apellido (vacía = nada)
    cua_alto_titulo: float = 13.0
    cua_sep_titulo: float = 5.0         # hueco entre la palabra y el apellido (mm)
    cua_titulo_x: float = 0.0           # lo que se ha arrastrado la palabra (mm)
    cua_color_titulo: str = "#e8872b"
    cua_integrantes: str = "Edgar, Giu, Matias"
    cua_alrededor: bool = False         # repartir los nombres a los lados, no solo debajo
    cua_pos: str = ""                   # "dx,dy;dx,dy": lo arrastrado de cada nombre
    cua_fuente: str = "Pacifico"
    cua_alto_familia: float = 48.0      # altura del apellido (mm)
    cua_alto_integrantes: float = 20.0  # altura del nombre más alto de la fila (mm)
    cua_separacion: float = 4.0         # hueco entre el apellido y la fila (mm)
    cua_hueco: float = 14.0             # hueco entre un nombre y el siguiente (mm)
    cua_placa: float = 5.0              # grosor de la placa del fondo (mm)
    cua_relieve: float = 3.0            # cuánto sobresalen las letras (mm)
    cua_margen: float = 9.0             # placa que sobra alrededor de las letras (mm)
    cua_suave: float = 7.0              # redondeo: funde el contorno en una sola forma
    cua_color_placa: str = "#2b2b2b"
    cua_color_familia: str = "#f2f2f2"
    cua_color_integrantes: str = "#d63a2f"
    # Adorno: un SVG de la carpeta "adornos", al lado o encima del apellido
    cua_adorno: bool = True
    cua_adorno_svg: str = "hogar/casa.svg"
    cua_adorno_alto: float = 38.0
    cua_adorno_x: float = 74.0          # % del ancho del apellido
    cua_adorno_y: float = -8.0          # mm desde lo alto del apellido; negativo = lo monta
    cua_adorno_giro: float = 0.0
    cua_adorno_c1: str = "familia"      # cada forma del dibujo, a un color distinto
    cua_adorno_c2: str = "extra"
    cua_adorno_c3: str = "placa"
    cua_color_adorno: str = "#e8872b"
    # Patrón: motivos repartidos DENTRO del apellido, en relieve sobre las letras
    cua_patron: bool = True
    cua_patron_svg: str = "copos_y_puntos.svg"
    cua_tam_patron: float = 4.0
    cua_separacion_patron: float = 2.5
    cua_margen_patron: float = 1.5      # distancia que respeta al borde de la letra
    cua_semilla: int = 1
    cua_girar_patron: bool = True
    cua_patron_corta: bool = True       # ahuecar la letra en vez de montar el motivo encima
    cua_patron_relieve: float = 1.2     # cuánto sobresale el patrón sobre la letra (mm)
    cua_color_patron: str = "#d63a2f"
    # Ganchos: un pincho inclinado bajo cada nombre
    cua_ganchos: bool = True
    cua_gancho_largo: float = 20.0
    cua_gancho_grueso: float = 6.0
    cua_gancho_angulo: float = 25.0     # inclinación hacia arriba (grados)
    cua_gancho_baja: float = 9.0        # cuánto baja respecto al pie del nombre (mm)
    cua_color_gancho: str = "#d63a2f"
    # Agujeros para colgar el cuadro
    cua_aparte: bool = False            # cada color se imprime suelto y se pega
    cua_espiga: float = 3.0             # hondura del hueco donde encaja cada pieza (mm)
    cua_holgura: float = 0.3            # aire del hueco, por las tolerancias (mm)

    cua_colgar: bool = True
    cua_colgar_diametro: float = 6.0

    # ---------------------------------------------------------- diseño 4: marcapáginas
    mar_inicial: str = "S"              # la letra grande, lo primero de arriba (vacía = no)
    mar_fuente_inicial: str = "Cooper Black"
    mar_alto_inicial: float = 34.0
    mar_inicial_y: float = 26.0         # del extremo de arriba al centro de la letra (mm)
    mar_color_inicial: str = "#fdf6ee"
    mar_texto: str = "Sophia"
    mar_fuente: str = "Pacifico"
    mar_alto_texto: float = 14.0        # alto de las letras del nombre (mm)
    mar_texto_y: float = 22.0           # del extremo de arriba al centro del nombre (mm);
                                        # si choca con la letra grande, baja lo justo
    mar_hueco: float = 3.0              # aire entre la letra grande y el nombre (mm)
    mar_largo: float = 135.0            # de punta a punta de la lámina (mm)
    mar_ancho: float = 24.0
    mar_grueso: float = 2.4             # lo que mide de canto: va dentro del libro
    mar_relieve: float = 1.2            # cuánto sobresalen las letras y el icono
    mar_margen: float = 4.0             # lámina que sobra alrededor de lo que sobresale
    mar_suave: float = 4.0              # funde el contorno en una sola forma
    mar_color_cuerpo: str = "#e8a07a"
    mar_color_texto: str = "#fdf6ee"

    mar_adorno: bool = True
    mar_adorno_svg: str = "marcapaginas/hoja.svg"
    mar_adorno_alto: float = 26.0
    mar_adorno_x: float = 18.0          # desde el centro de la letra grande (mm)
    mar_adorno_y: float = 12.0          # arrástralo también en la vista 3D
    mar_adorno_giro: float = 0.0
    mar_adorno_c1: str = "svg"          # "svg" = el color que trae el dibujo
    mar_adorno_c2: str = "svg"
    mar_adorno_c3: str = "svg"
    mar_color_adorno: str = "#9ec77a"

    mar_aparte: bool = False            # cada color se imprime suelto y se pega
    mar_espiga: float = 1.2             # hondura del hueco donde encaja cada pieza (mm)
    mar_holgura: float = 0.25           # aire del hueco, por las tolerancias (mm)


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
