#!/usr/bin/env python3
"""Monkeds Letter: servidor web con usuarios, licencias y panel de administración.

Arranque local:   python app.py
En producción:    gunicorn -w 3 -b 0.0.0.0:8000 app:app
La configuración (admin, contraseña, clave de sesión) sale del archivo .env.

La vista previa es gratis. "Generar archivos" descuenta 1 de la licencia y deja listos el
3MF y el STL, que luego se bajan desde "Mis generaciones" sin volver a cobrar.
"""
import json
import os
import re
import threading
import time
from dataclasses import asdict
from datetime import timedelta
from functools import wraps
from io import BytesIO

from flask import Flask, jsonify, redirect, request, send_file, session

import datos
from generador_stl import (AQUI, CARPETA_ADORNOS, CARPETA_PATRONES, Parametros,
                           adornos_disponibles, construir, exportar_3mf, exportar_stl,
                           fuentes_instaladas, miniatura_png, parametros_desde_dict,
                           patrones_disponibles, svg_a_poligono)

MAX_SVG = 2_000_000
CARPETA_WEB = os.path.join(AQUI, "web")


# ------------------------------------------------------------------ configuración (.env)
def cargar_env(ruta=os.path.join(AQUI, ".env")):
    """Lector mínimo de .env: LINEAS 'CLAVE=valor'. Lo ya definido en el entorno manda."""
    if not os.path.isfile(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


cargar_env()

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)
app.config.update(
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIES_SEGURAS", "0") == "1",  # ponlo en 1 con HTTPS
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
if not os.environ.get("SECRET_KEY"):
    print("AVISO: falta SECRET_KEY en el .env; las sesiones se perderán al reiniciar.")

CLAVE_POR_DEFECTO = "cambia-esta-clave"
_admin_clave = os.environ.get("ADMIN_CLAVE", CLAVE_POR_DEFECTO)
if CLAVE_POR_DEFECTO in _admin_clave:
    print("AVISO: ADMIN_CLAVE sigue siendo la de ejemplo. Cámbiala en el .env antes de publicar.")

datos.iniciar()
datos.asegurar_admin(os.environ.get("ADMIN_USUARIO", "admin"), _admin_clave)

_lock_dibujo = threading.Lock()  # ponytail: matplotlib no es seguro entre hilos; 1 miniatura a la vez
_fallos_login = {}               # ponytail: freno anti-fuerza-bruta en memoria, por proceso


# ------------------------------------------------------------------ IP y bloqueos
def ip_cliente():
    """Detrás de nginx o un balanceador llega en X-Forwarded-For; si no, la conexión directa."""
    reenviada = request.headers.get("X-Forwarded-For", "")
    return (reenviada.split(",")[0].strip() if reenviada else request.remote_addr) or "?"


@app.before_request
def cortar_bloqueados():
    if request.endpoint == "estilo":
        return None
    if datos.ip_bloqueada(ip_cliente()):
        session.clear()   # además de cortar, se le cierra la sesión
        if request.path.startswith("/api/"):
            return jsonify(error="Acceso bloqueado."), 403
        return "<h1>Acceso bloqueado</h1><p>Habla con el administrador.</p>", 403
    return None


# ------------------------------------------------------------------ sesión
def usuario_actual():
    uid = session.get("uid")
    return datos.obtener_usuario(uid) if uid else None


def pide_login(f):
    @wraps(f)
    def envoltorio(*a, **kw):
        u = usuario_actual()
        if not u or not u["activo"]:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify(error="Tienes que iniciar sesión."), 401
            return redirect("/login")
        request.usuario = u
        return f(*a, **kw)
    return envoltorio


def pide_admin(f):
    @wraps(f)
    @pide_login
    def envoltorio(*a, **kw):
        if not request.usuario["es_admin"]:
            if request.path.startswith("/api/"):
                return jsonify(error="Solo el administrador puede hacer esto."), 403
            return redirect("/")
        return f(*a, **kw)
    return envoltorio


def pagina(nombre):
    return send_file(os.path.join(AQUI, nombre))


def cuerpo_json():
    """Exige Content-Type JSON: un formulario de otro sitio no puede enviarlo (anti-CSRF)."""
    if not request.is_json:
        raise ValueError("Se esperaba una petición JSON.")
    return request.get_json(silent=True) or {}


# ------------------------------------------------------------------ entrar / salir
@app.get("/login")
def login_form():
    return redirect("/") if usuario_actual() else pagina("login.html")


@app.post("/login")
def login():
    ip = ip_cliente()
    fallos, hasta = _fallos_login.get(ip, (0, 0))
    if fallos >= 8 and time.time() < hasta:
        return redirect("/login?error=espera")

    u = datos.verificar_login(request.form.get("usuario", ""), request.form.get("clave", ""))
    if not u:
        _fallos_login[ip] = (fallos + 1, time.time() + 300)
        return redirect("/login?error=1")

    _fallos_login.pop(ip, None)
    datos.anotar_ip(u["id"], ip)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    return redirect("/")


@app.post("/invitado")
def entrar_invitado():
    """Entrada sin cuenta: solo pide un alias. Genera con el texto modificado."""
    try:
        u = datos.crear_invitado(request.form.get("alias", ""), ip_cliente())
    except ValueError:
        return redirect("/login?error=alias")
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    return redirect("/")


@app.get("/salir")
def salir():
    session.clear()
    return redirect("/login")


# ------------------------------------------------------------------ páginas
@app.get("/")
@pide_login
def inicio():
    return pagina("pantalla.html")


@app.get("/generaciones")
@pide_login
def pagina_generaciones():
    return pagina("generaciones.html")


@app.get("/licencias")
@pide_login
def pagina_licencias():
    return pagina("licencias.html")


@app.get("/admin")
@pide_admin
def admin():
    return pagina("admin.html")


@app.get("/estilo.css")
def estilo():
    return send_file(os.path.join(AQUI, "estilo.css"), mimetype="text/css")


@app.get("/web/<path:resto>")
@pide_login
def estaticos(resto):
    ruta = os.path.normpath(os.path.join(CARPETA_WEB, resto))
    if not ruta.startswith(CARPETA_WEB + os.sep) or not os.path.isfile(ruta):
        return "No encontrado", 404
    return send_file(ruta, mimetype="text/javascript")


@app.get("/api/svg/<tipo>/<nombre>")
@pide_login
def api_svg(tipo, nombre):
    """Sirve un patrón o adorno para verlo en la biblioteca."""
    carpeta = {"patron": CARPETA_PATRONES, "adorno": CARPETA_ADORNOS}.get(tipo)
    if not carpeta:
        return "No encontrado", 404
    ruta = os.path.normpath(os.path.join(carpeta, os.path.basename(nombre)))
    if not ruta.startswith(carpeta + os.sep) or not os.path.isfile(ruta):
        return "No encontrado", 404
    return send_file(ruta, mimetype="image/svg+xml")


# ------------------------------------------------------------------ API del usuario
@app.get("/api/yo")
@pide_login
def api_yo():
    u = request.usuario
    return jsonify(usuario=u["alias"] or u["usuario"], es_admin=bool(u["es_admin"]),
                   es_invitado=bool(u["es_invitado"]), resumen=datos.resumen_usuario(u["id"]))


@app.get("/api/config")
@pide_login
def api_config():
    return jsonify(defaults=asdict(Parametros()), fuentes=fuentes_instaladas(),
                   patrones=patrones_disponibles(), adornos=adornos_disponibles())


def _construir_desde(cuerpo):
    """dict -> (Parametros, niveles). Los errores de parámetros suben como ValueError."""
    p = parametros_desde_dict(cuerpo or {})
    return p, construir(p)


def texto_de_invitado(texto: str) -> str:
    """Los invitados reciben el texto partido por la mitad con un '+': Edgar -> Ed+gar."""
    t = (texto or "").strip()
    if not t:
        return t
    return (t[:len(t) // 2] + "+" + t[len(t) // 2:]) if len(t) > 1 else t + "+"


def _nombre_archivo(p: Parametros):
    base = f"{p.inicial.strip() or 'letra'}_{p.texto.strip() or 'sin_texto'}"
    return re.sub(r"[^\w\-]+", "_", base)[:60] or "monkeds"


def _responder_modelo(niveles, p: Parametros, formato: str):
    if formato == "stl":
        datos_bin, tipo = exportar_stl(niveles), "model/stl"
    else:
        datos_bin, tipo = exportar_3mf(niveles), "model/3mf"
    return send_file(BytesIO(datos_bin), mimetype=tipo, as_attachment=True,
                     download_name=f"{_nombre_archivo(p)}.{formato}")


@app.post("/api/preview")
@pide_login
def api_preview():
    """Vista previa 3D: no descuenta licencia ni se guarda."""
    try:
        p, niveles = _construir_desde(cuerpo_json())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return send_file(BytesIO(exportar_3mf(niveles)), mimetype="model/3mf")


@app.post("/api/generar")
@pide_login
def api_generar():
    """Consume 1 de la licencia y registra la generación. Deja listos los DOS formatos:
    se bajan después por /api/generacion/<id>/3mf y /stl, que ya no vuelven a cobrar."""
    try:
        cuerpo = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    uid = request.usuario["id"]
    invitado = bool(request.usuario["es_invitado"])
    if invitado:
        cuerpo = dict(cuerpo or {}, texto=texto_de_invitado((cuerpo or {}).get("texto", "")))
    elif not datos.licencia_vigente(uid):    # aviso rápido antes de calcular
        return jsonify(error="No tienes una licencia vigente con generaciones disponibles."), 402
    try:
        p, niveles = _construir_desde(cuerpo)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    with _lock_dibujo:
        mini = miniatura_png(niveles)
    try:
        gen_id = datos.registrar_generacion(uid, _nombre_archivo(p), "3mf+stl", asdict(p), mini,
                                            ip=ip_cliente(), exigir_licencia=not invitado)
    except datos.SinLicencia as e:
        return jsonify(error=str(e)), 402
    return jsonify(id=gen_id, nombre=_nombre_archivo(p), texto=p.texto,
                   resumen=datos.resumen_usuario(uid))


@app.get("/api/generaciones")
@pide_login
def api_generaciones():
    gs = datos.generaciones_de(request.usuario["id"])
    for g in gs:
        g.pop("parametros", None)
    return jsonify(generaciones=gs)


@app.get("/api/generacion/<int:gen_id>/miniatura")
@pide_login
def api_miniatura(gen_id):
    g = datos.generacion(gen_id, None if request.usuario["es_admin"] else request.usuario["id"])
    if not g or not g["miniatura"]:
        return "No encontrada", 404
    return send_file(BytesIO(g["miniatura"]), mimetype="image/png")


@app.get("/api/generacion/<int:gen_id>/parametros")
@pide_login
def api_gen_parametros(gen_id):
    g = datos.generacion(gen_id, None if request.usuario["es_admin"] else request.usuario["id"])
    if not g:
        return jsonify(error="No encontrada"), 404
    return jsonify(parametros=json.loads(g["parametros"]))


@app.get("/api/generacion/<int:gen_id>/<formato>")
@pide_login
def api_gen_descargar(gen_id, formato):
    """Bajar de nuevo algo ya generado: se rehace con sus parámetros y NO vuelve a cobrar."""
    if formato not in ("stl", "3mf"):
        return jsonify(error="Formato no válido."), 400
    g = datos.generacion(gen_id, None if request.usuario["es_admin"] else request.usuario["id"])
    if not g:
        return jsonify(error="No encontrada"), 404
    try:
        p, niveles = _construir_desde(json.loads(g["parametros"]))
    except ValueError as e:
        return jsonify(error=f"No se pudo rehacer: {e}"), 400
    return _responder_modelo(niveles, p, formato)


@app.get("/api/licencias")
@pide_login
def api_licencias():
    return jsonify(licencias=datos.licencias_de(request.usuario["id"]),
                   resumen=datos.resumen_usuario(request.usuario["id"]))


# ------------------------------------------------------------------ API de administración
@app.get("/api/admin/usuarios")
@pide_admin
def api_admin_usuarios():
    us = datos.listar_usuarios()
    for u in us:
        u["resumen"] = datos.resumen_usuario(u["id"])
    return jsonify(usuarios=us)


@app.post("/api/admin/usuarios")
@pide_admin
def api_admin_crear_usuario():
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        uid = datos.crear_usuario(d.get("usuario", ""), d.get("clave", ""), bool(d.get("es_admin")))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=uid)


@app.post("/api/admin/usuarios/<int:uid>")
@pide_admin
def api_admin_editar_usuario(uid):
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if uid == request.usuario["id"] and "activo" in d and not d["activo"]:
        return jsonify(error="No puedes desactivar tu propio usuario."), 400
    try:
        if d.get("clave"):
            datos.cambiar_clave(uid, d["clave"])
        if "activo" in d:
            datos.activar_usuario(uid, bool(d["activo"]))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.get("/api/admin/licencias/<int:uid>")
@pide_admin
def api_admin_licencias(uid):
    return jsonify(licencias=datos.licencias_de(uid))


@app.post("/api/admin/licencias")
@pide_admin
def api_admin_crear_licencia():
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        lid = datos.crear_licencia(int(d.get("usuario_id")), d.get("dias"),
                                   d.get("max_generaciones"), d.get("nota", ""))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=lid)


@app.post("/api/admin/licencias/<int:lid>")
@pide_admin
def api_admin_editar_licencia(lid):
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    datos.activar_licencia(lid, bool(d.get("activa")))
    return jsonify(ok=True)


@app.get("/api/admin/generaciones")
@pide_admin
def api_admin_generaciones():
    solo = request.args.get("invitados") == "1"
    return jsonify(generaciones=datos.generaciones_todas(solo_invitados=solo))


@app.get("/api/admin/ips")
@pide_admin
def api_admin_ips():
    return jsonify(bloqueadas=datos.ips_bloqueadas(), mi_ip=ip_cliente())


@app.post("/api/admin/ips")
@pide_admin
def api_admin_bloquear_ip():
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    ip = (d.get("ip") or "").strip()
    if d.get("bloquear"):
        if ip == ip_cliente():
            return jsonify(error="Esa es tu propia IP: te dejaría fuera."), 400
        try:
            datos.bloquear_ip(ip, d.get("motivo", ""))
        except ValueError as e:
            return jsonify(error=str(e)), 400
    else:
        datos.desbloquear_ip(ip)
    return jsonify(bloqueadas=datos.ips_bloqueadas())


# ------------------------------------------------------------------ subir SVG (solo admin)
def _guardar_svg(carpeta, nombre, contenido):
    if len(contenido) > MAX_SVG:
        raise ValueError("El SVG es demasiado grande (máx. 2 MB).")
    base = os.path.splitext(os.path.basename(str(nombre or "archivo")))[0]
    limpio = (re.sub(r"[^\w\-]", "_", base)[:60] or "archivo") + ".svg"
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, limpio)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(contenido)
    try:
        svg_a_poligono(tmp)  # se valida antes de dejarlo en la biblioteca
    except Exception as e:
        os.remove(tmp)
        raise ValueError(f"SVG no válido: {e}".replace(".svg.tmp", ".svg"))
    os.replace(tmp, ruta)
    return limpio


@app.post("/api/patron")
@pide_admin
def api_subir_patron():
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        nombre = _guardar_svg(CARPETA_PATRONES, d.get("nombre"), d.get("svg", ""))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(nombre=nombre, patrones=patrones_disponibles())


@app.post("/api/adorno")
@pide_admin
def api_subir_adorno():
    try:
        d = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    try:
        nombre = _guardar_svg(CARPETA_ADORNOS, d.get("nombre"), d.get("svg", ""))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(nombre=nombre, adornos=adornos_disponibles())


@app.errorhandler(413)
def demasiado_grande(_):
    return jsonify(error="El envío es demasiado grande."), 413


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)), threaded=True)
