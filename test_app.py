#!/usr/bin/env python3
"""Comprueba las plantillas por usuario y el cambio de contraseña.

    python test_app.py
"""
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

print("OK: plantillas por usuario y cambio de contraseña (propio y por el admin).")
