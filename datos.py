#!/usr/bin/env python3
"""Base de datos de Monkeds Letter: usuarios, licencias y generaciones (SQLite).

No se guardan los archivos STL/3MF (ocuparían demasiado): de cada generación se guardan
solo los parámetros y una miniatura PNG pequeña. Los archivos se rehacen al vuelo.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from generador_stl import AQUI

RUTA_DB = os.environ.get("MONKEDS_DB") or os.path.join(AQUI, "monkeds.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY,
    usuario    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    clave_hash TEXT NOT NULL,
    es_admin   INTEGER NOT NULL DEFAULT 0,
    activo     INTEGER NOT NULL DEFAULT 1,
    creado     TEXT NOT NULL,
    es_invitado INTEGER NOT NULL DEFAULT 0,
    alias      TEXT,
    ultima_ip  TEXT
);
CREATE TABLE IF NOT EXISTS licencias (
    id               INTEGER PRIMARY KEY,
    usuario_id       INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    nota             TEXT NOT NULL DEFAULT '',
    creada           TEXT NOT NULL,
    expira           TEXT,             -- NULL = sin límite de tiempo
    max_generaciones INTEGER,          -- NULL = sin límite de cantidad
    usadas           INTEGER NOT NULL DEFAULT 0,
    activa           INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS generaciones (
    id          INTEGER PRIMARY KEY,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    licencia_id INTEGER REFERENCES licencias(id),
    creada      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    formato     TEXT NOT NULL,
    parametros  TEXT NOT NULL,         -- JSON; con esto se rehace el archivo
    miniatura   BLOB,                  -- PNG pequeño
    ip          TEXT
);
CREATE TABLE IF NOT EXISTS ips_bloqueadas (
    ip     TEXT PRIMARY KEY,
    motivo TEXT NOT NULL DEFAULT '',
    creada TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gen_usuario ON generaciones(usuario_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_lic_usuario ON licencias(usuario_id);
"""


class SinLicencia(Exception):
    """El usuario no tiene una licencia vigente con cupo disponible."""


def ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def en_dias(dias: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S")


@contextmanager
def conexion():
    con = sqlite3.connect(RUTA_DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
    finally:
        con.close()


def _migrar(con):
    """Añade a una base ya creada las columnas nuevas (invitados y IP)."""
    def columnas(tabla):
        return {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
    nuevas = [("usuarios", "es_invitado", "INTEGER NOT NULL DEFAULT 0"),
              ("usuarios", "alias", "TEXT"),
              ("usuarios", "ultima_ip", "TEXT"),
              ("generaciones", "ip", "TEXT")]
    for tabla, col, tipo in nuevas:
        if col not in columnas(tabla):
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")


def iniciar():
    with conexion() as con:
        con.execute("PRAGMA journal_mode = WAL")  # varios procesos (gunicorn) sobre el mismo archivo
        con.executescript(ESQUEMA)
        _migrar(con)
        con.commit()


# ------------------------------------------------------------------ usuarios
def crear_usuario(usuario: str, clave: str, es_admin: bool = False) -> int:
    usuario = (usuario or "").strip()
    if not usuario:
        raise ValueError("Falta el nombre de usuario.")
    if len(clave or "") < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    with conexion() as con:
        try:
            cur = con.execute(
                "INSERT INTO usuarios (usuario, clave_hash, es_admin, creado) VALUES (?,?,?,?)",
                (usuario, generate_password_hash(clave), int(es_admin), ahora()))
            con.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"El usuario '{usuario}' ya existe.")


def verificar_login(usuario: str, clave: str):
    with conexion() as con:
        u = con.execute("SELECT * FROM usuarios WHERE usuario = ? AND es_invitado = 0",
                        ((usuario or "").strip(),)).fetchone()
    if u and u["activo"] and check_password_hash(u["clave_hash"], clave or ""):
        return dict(u)
    return None


def obtener_usuario(usuario_id: int):
    with conexion() as con:
        u = con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    return dict(u) if u else None


def listar_usuarios():
    with conexion() as con:
        filas = con.execute("""
            SELECT u.id, u.usuario, u.es_admin, u.activo, u.creado, u.es_invitado, u.alias, u.ultima_ip,
                   (SELECT COUNT(*) FROM generaciones g WHERE g.usuario_id = u.id) AS generaciones
            FROM usuarios u ORDER BY u.es_invitado, u.es_admin DESC, u.usuario""").fetchall()
    return [dict(f) for f in filas]


def cambiar_clave(usuario_id: int, clave: str):
    if len(clave or "") < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    with conexion() as con:
        con.execute("UPDATE usuarios SET clave_hash = ? WHERE id = ?",
                    (generate_password_hash(clave), usuario_id))
        con.commit()


def activar_usuario(usuario_id: int, activo: bool):
    with conexion() as con:
        con.execute("UPDATE usuarios SET activo = ? WHERE id = ?", (int(activo), usuario_id))
        con.commit()


def asegurar_admin(usuario: str, clave: str):
    """Crea (o actualiza) el admin del .env en cada arranque."""
    with conexion() as con:
        u = con.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,)).fetchone()
    if u:
        cambiar_clave(u["id"], clave)
        with conexion() as con:
            con.execute("UPDATE usuarios SET es_admin = 1, activo = 1 WHERE id = ?", (u["id"],))
            con.commit()
        return u["id"]
    return crear_usuario(usuario, clave, es_admin=True)


# ------------------------------------------------------------------ invitados
def crear_invitado(alias: str, ip: str) -> dict:
    """Entra como invitado con un alias. Se reutiliza el mismo si vuelve desde la misma IP."""
    alias = (alias or "").strip()[:40]
    if len(alias) < 2:
        raise ValueError("Pon un alias de al menos 2 caracteres.")
    with conexion() as con:
        f = con.execute("""SELECT * FROM usuarios WHERE es_invitado = 1
                            AND alias = ? COLLATE NOCASE AND ultima_ip = ? AND activo = 1""",
                        (alias, ip)).fetchone()
        if f:
            return dict(f)
        base = "inv:" + alias
        usuario, n = base, 1
        while con.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
            n += 1
            usuario = f"{base}#{n}"
        cur = con.execute("""INSERT INTO usuarios
                 (usuario, clave_hash, es_admin, es_invitado, alias, ultima_ip, creado)
                 VALUES (?, '-', 0, 1, ?, ?, ?)""", (usuario, alias, ip, ahora()))
        con.commit()
        return dict(con.execute("SELECT * FROM usuarios WHERE id = ?", (cur.lastrowid,)).fetchone())


def anotar_ip(usuario_id: int, ip: str):
    with conexion() as con:
        con.execute("UPDATE usuarios SET ultima_ip = ? WHERE id = ?", (ip, usuario_id))
        con.commit()


# ------------------------------------------------------------------ bloqueo por IP
def bloquear_ip(ip: str, motivo: str = ""):
    ip = (ip or "").strip()
    if not ip:
        raise ValueError("Falta la IP.")
    with conexion() as con:
        con.execute("INSERT OR REPLACE INTO ips_bloqueadas (ip, motivo, creada) VALUES (?,?,?)",
                    (ip, (motivo or "").strip(), ahora()))
        con.commit()


def desbloquear_ip(ip: str):
    with conexion() as con:
        con.execute("DELETE FROM ips_bloqueadas WHERE ip = ?", ((ip or "").strip(),))
        con.commit()


def ips_bloqueadas():
    with conexion() as con:
        return [dict(f) for f in con.execute("SELECT * FROM ips_bloqueadas ORDER BY creada DESC")]


def ip_bloqueada(ip: str) -> bool:
    if not ip:
        return False
    with conexion() as con:
        return con.execute("SELECT 1 FROM ips_bloqueadas WHERE ip = ?", (ip,)).fetchone() is not None


# ------------------------------------------------------------------ licencias
def crear_licencia(usuario_id: int, dias=None, max_generaciones=None, nota: str = "") -> int:
    dias = int(dias) if str(dias or "").strip() not in ("", "0", "None") else None
    max_generaciones = int(max_generaciones) if str(max_generaciones or "").strip() not in ("", "0", "None") else None
    if dias is not None and dias <= 0:
        raise ValueError("Los días deben ser mayores que 0 (vacío = sin límite de tiempo).")
    if max_generaciones is not None and max_generaciones <= 0:
        raise ValueError("La cantidad debe ser mayor que 0 (vacío = sin límite de cantidad).")
    with conexion() as con:
        if not con.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone():
            raise ValueError("Ese usuario no existe.")
        cur = con.execute(
            "INSERT INTO licencias (usuario_id, nota, creada, expira, max_generaciones) VALUES (?,?,?,?,?)",
            (usuario_id, (nota or "").strip(), ahora(), en_dias(dias) if dias else None, max_generaciones))
        con.commit()
        return cur.lastrowid


def licencias_de(usuario_id: int):
    with conexion() as con:
        filas = con.execute(
            "SELECT * FROM licencias WHERE usuario_id = ? ORDER BY activa DESC, id DESC", (usuario_id,)).fetchall()
    hoy = ahora()
    salida = []
    for f in filas:
        d = dict(f)
        d["vencida"] = bool(d["expira"] and d["expira"] <= hoy)
        d["restantes"] = None if d["max_generaciones"] is None else max(d["max_generaciones"] - d["usadas"], 0)
        d["vigente"] = bool(d["activa"]) and not d["vencida"] and (d["restantes"] is None or d["restantes"] > 0)
        salida.append(d)
    return salida


def activar_licencia(licencia_id: int, activa: bool):
    with conexion() as con:
        con.execute("UPDATE licencias SET activa = ? WHERE id = ?", (int(activa), licencia_id))
        con.commit()


_SQL_LICENCIA_VIGENTE = """
    SELECT * FROM licencias
     WHERE usuario_id = ? AND activa = 1
       AND (expira IS NULL OR expira > ?)
       AND (max_generaciones IS NULL OR usadas < max_generaciones)
     ORDER BY (expira IS NULL), expira, id
     LIMIT 1"""


def licencia_vigente(usuario_id: int):
    """La licencia que se usaría ahora: la que vence antes, para gastarla primero."""
    with conexion() as con:
        f = con.execute(_SQL_LICENCIA_VIGENTE, (usuario_id, ahora())).fetchone()
    return dict(f) if f else None


# ------------------------------------------------------------------ generaciones
def registrar_generacion(usuario_id: int, nombre: str, formato: str, parametros: dict,
                         miniatura: bytes, ip: str = None, exigir_licencia: bool = True):
    """Descuenta 1 de la licencia vigente y guarda la generación. Todo en una transacción.
    Los invitados generan sin licencia (exigir_licencia=False), con el texto modificado."""
    with conexion() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            lic = None
            if exigir_licencia:
                lic = con.execute(_SQL_LICENCIA_VIGENTE, (usuario_id, ahora())).fetchone()
                if not lic:
                    raise SinLicencia("No tienes una licencia vigente con generaciones disponibles.")
                con.execute("UPDATE licencias SET usadas = usadas + 1 WHERE id = ?", (lic["id"],))
            cur = con.execute("""INSERT INTO generaciones
                     (usuario_id, licencia_id, creada, nombre, formato, parametros, miniatura, ip)
                     VALUES (?,?,?,?,?,?,?,?)""",
                              (usuario_id, lic["id"] if lic else None, ahora(), nombre, formato,
                               json.dumps(parametros, ensure_ascii=False), miniatura, ip))
            con.commit()
            return cur.lastrowid
        except Exception:
            con.rollback()
            raise


def generaciones_de(usuario_id: int, limite: int = 60):
    with conexion() as con:
        filas = con.execute("""SELECT id, creada, nombre, formato, parametros
                                 FROM generaciones WHERE usuario_id = ?
                                ORDER BY id DESC LIMIT ?""", (usuario_id, limite)).fetchall()
    return [dict(f) for f in filas]


def generacion(gen_id: int, usuario_id=None):
    """Una generación; si se pasa usuario_id, solo si le pertenece."""
    sql = "SELECT * FROM generaciones WHERE id = ?"
    args = [gen_id]
    if usuario_id is not None:
        sql += " AND usuario_id = ?"
        args.append(usuario_id)
    with conexion() as con:
        f = con.execute(sql, args).fetchone()
    return dict(f) if f else None


def generaciones_todas(limite: int = 200, solo_invitados: bool = False):
    """Todas las generaciones, de cualquier usuario o invitado (para el administrador)."""
    sql = """SELECT g.id, g.creada, g.nombre, g.ip, u.id AS usuario_id, u.usuario,
                    u.alias, u.es_invitado
               FROM generaciones g JOIN usuarios u ON u.id = g.usuario_id"""
    if solo_invitados:
        sql += " WHERE u.es_invitado = 1"
    sql += " ORDER BY g.id DESC LIMIT ?"
    with conexion() as con:
        return [dict(f) for f in con.execute(sql, (limite,))]


def resumen_usuario(usuario_id: int):
    lic = licencias_de(usuario_id)
    vig = [l for l in lic if l["vigente"]]
    restantes = [l["restantes"] for l in vig if l["restantes"] is not None]
    with conexion() as con:
        n = con.execute("SELECT COUNT(*) c FROM generaciones WHERE usuario_id = ?", (usuario_id,)).fetchone()["c"]
    return {
        "generaciones": n,
        "licencias_vigentes": len(vig),
        # None = ilimitado (alguna licencia vigente sin tope de cantidad)
        "restantes": None if (vig and not restantes) else sum(restantes),
        "vence": min([l["expira"] for l in vig if l["expira"]], default=None),
    }
