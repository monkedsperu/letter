#!/usr/bin/env python3
"""Comprueba las plantillas por usuario y el cambio de contraseña.

    python test_app.py
"""
import math
import os
import sqlite3
import tempfile

RUTA = os.path.join(tempfile.mkdtemp(), "prueba.db")
os.environ["MONKEDS_DB"] = RUTA

# --- la base vieja (plantillas globales, nombre UNIQUE) tiene que migrar sola
_con = sqlite3.connect(RUTA)
_con.executescript("""
CREATE TABLE usuarios (id INTEGER PRIMARY KEY, usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
    clave_hash TEXT NOT NULL, es_admin INTEGER NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1, creado TEXT NOT NULL);
CREATE TABLE plantillas (id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
    parametros TEXT NOT NULL, miniatura BLOB, creada TEXT NOT NULL);
INSERT INTO plantillas VALUES (1,'palote','{"texto":"hola"}',NULL,'2026-01-01');
""")
_con.commit()
_con.close()

import app as aplicacion   # noqa: E402  (importar después de fijar MONKEDS_DB)
import datos               # noqa: E402

datos.iniciar()
assert [p["nombre"] for p in datos.listar_plantillas(None)] == ["palote"], "la migración perdió filas"

admin = datos.crear_usuario("admin_prueba", "clave12", es_admin=True)
ana = datos.crear_usuario("ana", "clave12")
beto = datos.crear_usuario("beto", "clave12")
invitado = datos.crear_invitado("invi", "1.2.3.4")["id"]

cliente = aplicacion.app.test_client()


def como(uid):
    with cliente.session_transaction() as s:
        s["uid"] = uid
    return cliente


PARAMS = {"inicial": "M", "texto": "Monkeds"}


def guardar(uid, nombre):
    return como(uid).post("/api/plantillas", json={"nombre": nombre, "parametros": PARAMS})


def nombres(uid):
    return [p["nombre"] for p in como(uid).get("/api/plantillas").get_json()["plantillas"]]


# el admin guarda para todos; ana y beto, cada uno la suya (mismo nombre, no choca)
assert guardar(admin, "de_la_casa").status_code == 200
assert guardar(ana, "mi_diseno").status_code == 200
assert guardar(beto, "mi_diseno").status_code == 200
assert guardar(invitado, "de_invitado").status_code == 200, "un invitado también debe poder guardar"

assert sorted(nombres(ana)) == ["de_la_casa", "mi_diseno", "palote"], nombres(ana)
assert sorted(nombres(beto)) == ["de_la_casa", "mi_diseno", "palote"], nombres(beto)
assert "de_invitado" in nombres(invitado) and "de_invitado" not in nombres(ana)

# guardar con el mismo nombre pisa la propia, no crea otra ni toca la del vecino
assert guardar(ana, "mi_diseno").status_code == 200
assert nombres(ana).count("mi_diseno") == 1
assert nombres(beto).count("mi_diseno") == 1

# la de beto no se puede abrir ni borrar desde la cuenta de ana
pid_beto = [p["id"] for p in como(beto).get("/api/plantillas").get_json()["plantillas"]
            if p["mia"]][0]
assert como(ana).get(f"/api/plantilla/{pid_beto}").status_code == 404
assert como(ana).delete(f"/api/plantillas/{pid_beto}").status_code == 403
assert como(beto).delete(f"/api/plantillas/{pid_beto}").status_code == 200
assert "mi_diseno" not in nombres(beto)

# nadie borra las de la casa salvo el admin
pid_casa = [p["id"] for p in como(ana).get("/api/plantillas").get_json()["plantillas"]
            if not p["mia"]][0]
assert como(ana).delete(f"/api/plantillas/{pid_casa}").status_code == 403
assert como(admin).delete(f"/api/plantillas/{pid_casa}").status_code == 200

# tope por usuario
for i in range(datos.MAX_PLANTILLAS):
    guardar(ana, f"relleno{i}")
r = guardar(ana, "una_mas")
assert r.status_code == 400 and "máximo" in r.get_json()["error"], r.get_json()

# sin sesión no se guarda nada
with cliente.session_transaction() as s:
    s.clear()
assert cliente.post("/api/plantillas", json={"nombre": "x", "parametros": PARAMS}).status_code == 401

# --------------------------------------------------------------- contraseñas
assert como(ana).post("/api/clave", json={"actual": "mala", "nueva": "nueva123"}).status_code == 403
assert como(ana).post("/api/clave", json={"actual": "clave12", "nueva": "corta"}).status_code == 400
assert datos.verificar_login("ana", "clave12"), "no debería haber cambiado nada aún"

assert como(ana).post("/api/clave", json={"actual": "clave12", "nueva": "nueva123"}).status_code == 200
assert datos.verificar_login("ana", "nueva123") and not datos.verificar_login("ana", "clave12")

# un invitado no tiene contraseña que cambiar
assert como(invitado).post("/api/clave", json={"actual": "x", "nueva": "nueva123"}).status_code == 400

# el admin cambia la de otro sin saber la anterior; nadie más puede
assert como(admin).post(f"/api/admin/usuarios/{ana}", json={"clave": "puesta_por_admin"}).status_code == 200
assert datos.verificar_login("ana", "puesta_por_admin")
assert como(beto).post(f"/api/admin/usuarios/{ana}", json={"clave": "nope12"}).status_code == 403
assert datos.verificar_login("ana", "puesta_por_admin"), "beto no debe poder tocarla"

with cliente.session_transaction() as s:
    s.clear()
assert cliente.post("/api/clave", json={"actual": "x", "nueva": "y"}).status_code == 401

# --------------------------------------------------------- los dos diseños
import generador_stl as gen     # noqa: E402
from shapely.affinity import scale as shapely_escalar   # noqa: E402

llavero = gen.construir_con_analisis(gen.Parametros())[0]
organizador, info = gen.construir_con_analisis(gen.Parametros(tipo="organizador"))
assert [n for n, _, _ in organizador] == ["Cuerpo", "Nombre", "Borde"], organizador
assert all(m.is_watertight for _, _, m in llavero + organizador), "las mallas tienen que cerrar"

# Los módulos tienen que vaciar material de verdad y con la medida pedida: se compara el
# mismo cuerpo cavado a dos honduras, y lo que desaparece debe ser el cilindro / la caja.
def volumen_cuerpo(**cambios):
    ajustes = dict(tipo="organizador", org_movil=False, org_vaso=False, org_bandeja=False)
    piezas = gen.construir_con_analisis(gen.Parametros(**dict(ajustes, **cambios)))[0]
    return {n: m.volume for n, _, m in piezas}["Cuerpo"]

d = gen.Parametros()
quitado = volumen_cuerpo(org_vaso=True, org_vaso_hondo=20) - volumen_cuerpo(org_vaso=True, org_vaso_hondo=64)
cilindro = math.pi * (d.org_vaso_diametro / 2) ** 2 * 44
assert abs(quitado - cilindro) < cilindro * 0.02, (quitado, cilindro)

quitado = (volumen_cuerpo(org_bandeja=True, org_bandeja_alto=20, org_bandeja_hondo=6)
           - volumen_cuerpo(org_bandeja=True, org_bandeja_alto=20, org_bandeja_hondo=12))
caja = (d.org_bandeja_ancho - 2 * d.org_pared) * (d.org_bandeja_fondo - 2 * d.org_pared) * 6
# el 5% de margen es por las esquinas redondeadas del hueco, que le quitan un poco de área
assert abs(quitado - caja) < caja * 0.05, (quitado, caja)

# la ranura del móvil llega hasta arriba, así que su hondura la marca el cuerpo: basta con
# que una ranura más ancha se lleve más material que una estrecha
assert volumen_cuerpo(org_movil=True, org_movil_grueso=18) < volumen_cuerpo(org_movil=True, org_movil_grueso=8)

# El organizador se imprime de pie: la base tiene que ser una cara plana contra la cama,
# sin nada flotando y sin aleros del redondeo. Se comprueba en varias combinaciones porque
# el canto, el suavizado y los módulos tocan todos la misma zona.
def revisar_apoyo(nombre, **cambios):
    piezas, _ = gen.construir_con_analisis(gen.Parametros(tipo="organizador", **cambios))
    cuerpo = piezas[0][2]
    centro = cuerpo.triangles.mean(axis=1)
    plana = cuerpo.face_normals[:, 2] < -0.99
    apoyo = cuerpo.area_faces[plana & (centro[:, 2] < 0.1)].sum()
    flotante = cuerpo.area_faces[plana & (centro[:, 2] > 0.12) & (centro[:, 2] < 1.0)].sum()
    assert all(m.is_watertight and m.volume > 0 for _, _, m in piezas), nombre
    assert min(m.bounds[0][2] for _, _, m in piezas) > -1e-6, (nombre, "algo baja de la mesa")
    assert apoyo > 500, (nombre, "casi no apoya", apoyo)
    assert flotante < 0.5, (nombre, "hay un alero sobre la mesa", flotante)

revisar_apoyo("por defecto")
revisar_apoyo("sin canto", org_canto=0)
revisar_apoyo("canto grande", org_canto=6)
revisar_apoyo("sin suavizado", org_suave=0)
revisar_apoyo("muy suavizado", org_suave=20)
revisar_apoyo("sin módulos", org_movil=False, org_vaso=False, org_bandeja=False)
revisar_apoyo("nombre corto", org_texto="Ana")

# El borde del nombre es una pieza más, con su color, que rodea a las letras sin pisarlas,
# y el adorno otra: cada una con su filamento.
sin_borde, _ = gen.construir_con_analisis(gen.Parametros(tipo="organizador", org_borde=0))
assert [n for n, _, _ in sin_borde] == ["Cuerpo", "Nombre"], sin_borde
# el adorno se parte en las formas que traiga el SVG, cada una con el color que se le
# asigne de la paleta de la pieza: por eso nunca se pasa de 4 filamentos
con_adorno, datos_adorno = gen.construir_con_analisis(
    gen.Parametros(tipo="organizador", org_adorno=True))
nombres_piezas = [n for n, _, _ in con_adorno]
assert nombres_piezas[:2] == ["Cuerpo", "Nombre"] and nombres_piezas[-1] == "Borde", nombres_piezas
assert datos_adorno["grupos_adorno"] == 3, datos_adorno["grupos_adorno"]
assert sum(n.startswith("Adorno") for n in nombres_piezas) == 3, nombres_piezas
assert len(datos_adorno["colores"]) == 4, datos_adorno["colores"]

# y si todas las formas van al mismo sitio, no aparece un filamento de más
de_un_color = gen.construir_con_analisis(gen.Parametros(
    tipo="organizador", org_adorno=True, org_adorno_c1="nombre", org_adorno_c2="nombre",
    org_adorno_c3="nombre"))[1]
assert len(de_un_color["colores"]) == 3, de_un_color["colores"]

# el adorno se lee de una subcarpeta, y ningún nombre puede salirse de la carpeta de adornos
assert "desktop/lapiz.svg" in gen.adornos_disponibles(), gen.adornos_disponibles()
assert gen.svg_dentro_de(gen.CARPETA_ADORNOS, "desktop/lapiz.svg")
for fuga in ("../app.py", "..\app.py", "/etc/passwd", "desktop/../../app.py"):
    assert gen.svg_dentro_de(gen.CARPETA_ADORNOS, fuga) is None, fuga

# Imprimir aparte: el nombre sale tumbado y al lado del cuerpo, nunca encima, para poder
# imprimirlo sin soportes. Su grosor es el relieve más la espiga que encaja en el hueco.
suelto = gen.Parametros(tipo="organizador", org_aparte=True, org_borde=3)
piezas, info = gen.construir_con_analisis(suelto)
cuerpo_suelto = piezas[0][2]
for nombre_pieza, _, malla in piezas[1:]:
    grueso = malla.bounds[1][2] - malla.bounds[0][2]
    assert abs(grueso - (suelto.org_relieve + suelto.org_hueco)) < 1e-6, (nombre_pieza, grueso)
    assert malla.bounds[1][1] < cuerpo_suelto.bounds[0][1], (nombre_pieza, "se pisa con el cuerpo")
    assert abs(malla.bounds[0][2]) < 1e-6, (nombre_pieza, "no apoya en la mesa")
assert any("aparte" in s for s in info["avisos"]), info["avisos"]

# y el cuerpo lleva cajeada la silueta del nombre, con su holgura: lo que se quita tiene que
# ser el área del nombre engordado por la hondura del hueco
def volumen_del_cuerpo(**cambios):
    ajustes = dict(tipo="organizador", org_aparte=True, org_borde=3)
    return gen.construir_con_analisis(gen.Parametros(**dict(ajustes, **cambios)))[0][0][2].volume

# y tiene que estar ABIERTO a la cara, no ser una burbuja dentro del cuerpo: un corte a
# ras de la cara delantera debe encontrar el contorno de las letras, que no está sin hueco
import trimesh.intersections as _cortes    # noqa: E402

def contorno_a_ras(hondura):
    piezas, _ = gen.construir_con_analisis(gen.Parametros(
        tipo="organizador", org_aparte=hondura > 0, org_borde=3, org_hueco=max(hondura, 4)))
    corte = _cortes.mesh_plane(piezas[0][2], plane_normal=[0, 1, 0], plane_origin=[0, 0.2, 0])
    return len(corte)

for hondura in (4, 6, 9):
    assert contorno_a_ras(hondura) > contorno_a_ras(0) * 2, (hondura, "el hueco no llega a la cara")

# (el hueco no admite menos de 4 mm, así que se comparan dos honduras por encima)
cajeado = volumen_del_cuerpo(org_hueco=4) - volumen_del_cuerpo(org_hueco=6)
plano = gen.texto_a_poligono(suelto.org_texto, suelto.org_fuente, 100)
escala = suelto.org_alto / (plano.bounds[3] - plano.bounds[1])
plano = shapely_escalar(plano, escala, escala, origin=(0, 0))
hueco_esperado = plano.buffer(suelto.org_borde).buffer(suelto.org_holgura).area * 2
assert abs(cajeado - hueco_esperado) < hueco_esperado * 0.03, (cajeado, hueco_esperado)

# Un nombre de varias palabras sale en trozos sueltos, y el borde los une cuando llega a
# tapar la mitad del hueco entre ellas. La app tiene que decir ese ancho, y tiene que valer.
import shapely.affinity as _af    # noqa: E402

plano = gen.texto_a_poligono("Edgar Medina", gen.Parametros().org_fuente, 100)
plano = _af.scale(plano, 45 / (plano.bounds[3] - plano.bounds[1]),
                  45 / (plano.bounds[3] - plano.bounds[1]), origin=(0, 0))
assert len(gen._poligonos(plano)) > 1, "este nombre debería venir en varios trozos"
une = gen._borde_que_une(plano, 0.0)
assert une and len(gen._poligonos(plano.buffer(une))) == 1, (une, "el ancho que dice no une")
assert len(gen._poligonos(plano.buffer(une * 0.8))) > 1, (une, "no es el mínimo, sobra borde")

# Unas medidas disparatadas tienen que salir como aviso, no como error del servidor: la
# librería de geometría revienta con ellas y eso llegaba al usuario como un 500.
for disparate in (dict(tam_inicial=0), dict(tam_inicial=-5), dict(borde=1000),
                  dict(borde_texto1=1000), dict(margen_patron=1000), dict(tam_adorno=1000),
                  dict(tipo="organizador", org_alto=0), dict(tipo="organizador", org_fondo=-1)):
    try:
        gen.construir_con_analisis(gen.Parametros(**disparate))
    except ValueError:
        pass                                   # mensaje para el usuario: correcto
    except Exception as e:
        raise AssertionError((disparate, "revienta en vez de avisar", type(e).__name__))

# y un patrón con el motivo demasiado pequeño se rechaza en vez de colgar el proceso
# repartiendo millones de figuras
try:
    gen.construir_con_analisis(gen.Parametros(tam_patron=0.5))
    raise AssertionError("un motivo de medio milímetro debería rechazarse")
except ValueError as e:
    assert "pequeño" in str(e), e

# --------------------------------------------------- el cuadro de las llaves
cuadro, datos_cuadro = gen.construir_con_analisis(gen.Parametros(tipo="cuadro"))
piezas_cuadro = [n for n, _, _ in cuadro]
assert piezas_cuadro[:4] == ["Placa", "Familia", "Titulo", "Nombre 1"], piezas_cuadro
assert "Gancho 3" in piezas_cuadro, piezas_cuadro
assert all(m.is_watertight and m.volume > 0 for _, _, m in cuadro), piezas_cuadro
assert len(datos_cuadro["colores"]) <= 4, datos_cuadro["colores"]

# un gancho por nombre -cada uno su propia pieza, para poder arrastrarlos- debajo del
# suyo y sobresaliendo de la placa
ganchos = [m for n, _, m in cuadro if n.startswith("Gancho ")]
placa_3 = [m for n, _, m in cuadro if n == "Placa"][0]
assert len(ganchos) == 3, ("un gancho por nombre", len(ganchos))
assert all(g.bounds[1][2] > placa_3.bounds[1][2] + 10 for g in ganchos), "no sobresalen"
for i, g in enumerate(ganchos, 1):
    suyo = [m for n, _, m in cuadro if n == f"Nombre {i}"][0]
    assert abs(g.centroid[0] - suyo.centroid[0]) < 12, ("gancho descolocado", i)
# y al arrastrar un nombre, su gancho le sigue
movido = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_pos="0,0;0,0;30,-20"))[0]
antes = [m for n, _, m in cuadro if n == "Gancho 3"][0].centroid
ahora = [m for n, _, m in movido if n == "Gancho 3"][0].centroid
assert abs(ahora[0] - antes[0] - 30) < 0.6 and abs(ahora[1] - antes[1] + 20) < 0.6,     ("el gancho no acompaña al nombre", antes, ahora)
# la palabra de arriba también se mueve
corrida = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_titulo_x=25))[0]
assert abs([m for n, _, m in corrida if n == "Titulo"][0].centroid[0]
           - [m for n, _, m in cuadro if n == "Titulo"][0].centroid[0] - 25) < 0.6

# sin nombres no hay ni fila ni ganchos, pero el cuadro sigue saliendo
solo = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_integrantes=" "))[0]
assert [n for n, _, _ in solo if n.startswith(("Nombre", "Gancho"))] == [], solo

# la palabra pequeña va encima del apellido y en su propio color
titulo = [m for nn, _, m in cuadro if nn == "Titulo"][0]
familia_3 = [m for nn, _, m in cuadro if nn == "Familia"][0]
assert titulo.bounds[0][1] > familia_3.bounds[1][1] - 1, "la palabra de arriba no está arriba"
sin_titulo = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_titulo=" "))[0]
assert [nn for nn, _, _ in sin_titulo if nn == "Titulo"] == [], "la palabra vacía sigue saliendo"

# con el reparto en corona los nombres siguen el contorno: se ensanchan y, además, suben
# por los lados en vez de quedarse todos en la misma línea de abajo
import trimesh    # noqa: E402


def _los_nombres(piezas):
    return trimesh.util.concatenate([m for n, _, m in piezas if n.startswith("Nombre ")])


fila_abajo = _los_nombres(cuadro)
alrededor = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_alrededor=True))[0]
corona = _los_nombres(alrededor)
assert corona.extents[0] > fila_abajo.extents[0] + 20, "el reparto en corona no ensancha nada"
assert corona.extents[1] > fila_abajo.extents[1] + 15, "los nombres no suben por los lados"
assert len([m for nn, _, m in alrededor if nn.startswith("Gancho ")]) == 3, "faltan ganchos"
# y ningún nombre pisa a otro: si se solaparan, al fundirlos se perdería volumen
for muchos in ("Edgar, Giu", "A, B, C, D, E, F, G, H"):
    def _nombres_de(**extra):
        piezas_m = gen.construir_con_analisis(gen.Parametros(
            tipo="cuadro", cua_integrantes=muchos, **extra))[0]
        return _los_nombres(piezas_m).volume
    assert abs(_nombres_de(cua_alrededor=True) - _nombres_de()) < 1.0, \
        ("nombres pisados entre sí", muchos)

# imprimir cada color por separado: la placa se vacía el hueco de cada pieza, las piezas
# crecen su espiga por detrás y salen apoyadas en la mesa, al lado de la placa
sueltas, datos_sueltas = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_aparte=True))
por_nombre = {n_: m for n_, _, m in sueltas}
pegada = {n_: m for n_, _, m in cuadro}
assert por_nombre["Placa"].volume < pegada["Placa"].volume - 5000, "la placa no se vació"
assert por_nombre["Placa"].bounds[1][2] == pegada["Placa"].bounds[1][2], "cambió el grosor"
espiga_3 = gen.Parametros().cua_espiga
assert abs(por_nombre["Familia"].extents[2] - pegada["Familia"].extents[2] - espiga_3) < 0.01, \
    "al nombre no le creció la espiga"
assert all(m.is_watertight and m.bounds[0][2] > -0.01 for m in por_nombre.values()), "mal apoyo"
assert all(abs(m.bounds[0][2]) < 0.01 for n_, m in por_nombre.items() if n_ != "Placa"), \
    "alguna pieza suelta no apoya en la mesa"
assert por_nombre["Familia"].bounds[1][1] < por_nombre["Placa"].bounds[0][1], \
    "las piezas sueltas se solapan con la placa"
# el hueco de cada gancho no atraviesa la placa por detrás
assert por_nombre["Placa"].section(plane_origin=[0, 0, 0.3], plane_normal=[0, 0, 1]), \
    "el hueco del gancho perfora la placa"
try:
    gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_aparte=True, cua_espiga=9))
    raise AssertionError("un hueco más hondo que la placa debería rechazarse")
except ValueError as e:
    assert "no cabe" in str(e), e

# el patrón: por defecto ahueca la letra (no hay pieza Patron y la letra pierde volumen);
# si se monta encima, aparece la pieza y en otro color para que se distinga
sin_patron = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_patron=False))[0]
letra_entera = [m for nn, _, m in sin_patron if nn == "Familia"][0].volume
assert "Patron" not in piezas_cuadro, "ahuecando no debe haber pieza aparte"
assert familia_3.volume < letra_entera - 100, "el patrón no ahueca la letra"
encima, _ = gen.construir_con_analisis(gen.Parametros(tipo="cuadro", cua_patron_corta=False))
pat = [(c, m) for nn, c, m in encima if nn == "Patron"]
assert pat and pat[0][1].bounds[1][2] > familia_3.bounds[1][2], "el patrón no sobresale"
assert pat[0][0].lower() != gen.Parametros().cua_color_familia.lower(),     "el patrón encima debe llevar otro color"

# los agujeros de colgar: dos, pasantes, nivelados, en las esquinas de arriba y sin
# acercarse al relieve
import numpy as _np   # noqa: E402

_sitios = datos_cuadro["colgar"]
_placa = [m for n_, _, m in cuadro if n_ == "Placa"][0]
_sin = [m for n_, _, m in gen.construir_con_analisis(
    gen.Parametros(tipo="cuadro", cua_colgar=False))[0] if n_ == "Placa"][0]
assert len(_sitios) == 2, _sitios
assert _placa.euler_number == -2 and _sin.euler_number == 2, "no son agujeros pasantes"
assert abs(_sitios[0][1] - _sitios[1][1]) < 0.01, ("torcidos", _sitios)
_x0, _y0 = _placa.bounds[0][:2]
_x1, _y1 = _placa.bounds[1][:2]
assert _sitios[0][0] < _x0 + 0.3 * (_x1 - _x0), ("el izquierdo no está en su esquina", _sitios)
assert _sitios[1][0] > _x1 - 0.4 * (_x1 - _x0), ("el derecho no está en su esquina", _sitios)
assert _sitios[0][1] > _y0 + 0.6 * (_y1 - _y0), ("deberían ir arriba", _sitios)
_relieve = trimesh.util.concatenate([m for n_, _, m in cuadro if n_ in ("Familia", "Titulo")
                                     or n_.startswith(("Nombre", "Adorno"))])
_cerca = _np.linalg.norm(_relieve.vertices[:, :2] - _np.array(_sitios)[:, None, :],
                         axis=2).min() - gen.Parametros().cua_colgar_diametro / 2
assert _cerca > 1.5, ("un agujero roza el relieve", _cerca)

# y lo que falta en la placa es justo el cilindro de cada uno: taparlos la devuelve entera
_grueso = gen.Parametros().cua_placa
_radio = gen.Parametros().cua_colgar_diametro / 2
_tapones = []
for _x, _y in _sitios:
    _t = trimesh.creation.cylinder(radius=_radio, height=_grueso, sections=48)
    _t.apply_translation([_x, _y, _grueso / 2])
    _tapones.append(_t)
_tapada = trimesh.boolean.union([_placa] + _tapones)
assert abs((_tapada.volume - _placa.volume) - 2 * math.pi * _radio ** 2 * _grueso)     < 0.05 * 2 * math.pi * _radio ** 2 * _grueso, "los agujeros no son los dos cilindros"

# --------------------------------------------------- el marcapáginas
marca, datos_marca = gen.construir_con_analisis(gen.Parametros(tipo="marca"))
piezas_marca = [n for n, _, _ in marca]
assert piezas_marca[:3] == ["Lamina", "Inicial", "Nombre"], piezas_marca
assert any(n.startswith("Icono") for n in piezas_marca), piezas_marca
assert all(m.is_watertight and m.volume > 0 for _, _, m in marca), piezas_marca
assert len(datos_marca["colores"]) <= 4, datos_marca["colores"]

# todo plano y apoyado en la mesa: la lámina abajo y el relieve justo encima
_lamina = [m for n, _, m in marca if n == "Lamina"][0]
_grueso_m, _relieve_m = gen.Parametros().mar_grueso, gen.Parametros().mar_relieve
assert abs(_lamina.bounds[0][2]) < 1e-6 and abs(_lamina.bounds[1][2] - _grueso_m) < 1e-6
for _n, _, _m in marca:
    if _n != "Lamina":
        assert abs(_m.bounds[0][2] - _grueso_m) < 1e-6, ("el relieve no apoya en la lámina", _n)
        assert abs(_m.bounds[1][2] - _grueso_m - _relieve_m) < 1e-6, ("relieve raro", _n)

# y nada vuela: cada pieza en relieve tiene lámina debajo de toda su superficie
for _n, _, _m in marca:
    if _n == "Lamina":
        continue
    _bajado = _m.copy()
    _bajado.apply_translation([0, 0, -_grueso_m + 0.01])   # metido en la banda de la lámina
    _dentro = trimesh.boolean.intersection([_bajado, _lamina])
    assert _dentro.volume > 0.98 * _bajado.volume, (f"{_n} sobresale de la lámina",
                                                    _dentro.volume, _bajado.volume)

# la letra grande manda: va arriba del todo y el nombre queda por debajo, sin pisarla
_letra = [m for n, _, m in marca if n == "Inicial"][0]
_nombre_m = [m for n, _, m in marca if n == "Nombre"][0]
assert _letra.bounds[0][1] > _nombre_m.bounds[1][1], "el nombre se monta sobre la letra"
assert _letra.extents[1] > _nombre_m.extents[1], "la letra grande debería ser la mayor"
_sin_letra = gen.construir_con_analisis(gen.Parametros(tipo="marca", mar_inicial=""))[0]
assert "Inicial" not in [n for n, _, _ in _sin_letra], "la letra vacía sigue saliendo"
assert [m for n, _, m in _sin_letra if n == "Nombre"][0].bounds[1][1] > \
    _nombre_m.bounds[1][1], "sin letra, el nombre debería subir"

# el icono orbita la letra grande: moverlo en X e Y lo mueve lo mismo
_movido = gen.construir_con_analisis(gen.Parametros(
    tipo="marca", mar_adorno_x=gen.Parametros().mar_adorno_x - 25,
    mar_adorno_y=gen.Parametros().mar_adorno_y + 8))[0]
_antes_i = trimesh.util.concatenate([m for n, _, m in marca if n.startswith("Icono")]).centroid
_ahora_i = trimesh.util.concatenate([m for n, _, m in _movido if n.startswith("Icono")]).centroid
assert abs(_ahora_i[0] - _antes_i[0] + 25) < 0.6 and abs(_ahora_i[1] - _antes_i[1] - 8) < 0.6, \
    ("el icono no se mueve con sus medidas", _antes_i, _ahora_i)

# imprimir cada color por separado: la lámina se vacía y las piezas salen a su lado
_sueltas_m, _ = gen.construir_con_analisis(gen.Parametros(tipo="marca", mar_aparte=True))
_pm = {n: m for n, _, m in _sueltas_m}
_espiga_m = gen.Parametros().mar_espiga
assert _pm["Lamina"].volume < _lamina.volume - 100, "la lámina no se vació"
assert abs(_pm["Inicial"].extents[2] - _letra.extents[2] - _espiga_m) < 0.01, "sin espiga"
assert all(abs(m.bounds[0][2]) < 0.01 for n, m in _pm.items() if n != "Lamina"), "no apoyan"
assert _pm["Inicial"].bounds[0][0] > _pm["Lamina"].bounds[1][0], "las piezas pisan la lámina"
try:
    gen.construir_con_analisis(gen.Parametros(tipo="marca", mar_aparte=True, mar_espiga=3))
    raise AssertionError("un hueco más hondo que la lámina debería rechazarse")
except ValueError as e:
    assert "no cabe" in str(e), e

# sin nada que poner, se avisa; y una lámina más ancha que larga tampoco vale
for _mal, _dice in (({"mar_texto": " ", "mar_inicial": "", "mar_adorno": False}, "vacío"),
                    ({"mar_largo": 20}, "más larga que ancha")):
    try:
        gen.construir_con_analisis(gen.Parametros(tipo="marca", **_mal))
        raise AssertionError(("debería rechazarse", _mal))
    except ValueError as e:
        assert _dice in str(e), (e, _dice)

# por la web: el diseño entero y un error claro cuando las medidas no encajan
assert como(ana).post("/api/preview", json={"tipo": "organizador"}).status_code == 200
mal = como(ana).post("/api/preview", json={"tipo": "organizador", "org_vaso_diametro": 200})
assert mal.status_code == 400 and "vaso" in mal.get_json()["error"], mal.get_json()
raro = como(ana).post("/api/preview", json={"tipo": "nave espacial"})
assert raro.status_code == 400, raro.get_json()

print("OK: plantillas, contraseñas y los cuatro diseños (llavero, organizador, cuadro y marcapáginas).")
