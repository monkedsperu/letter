#!/usr/bin/env python3
"""Monkeds Letter: servidor web con usuarios, licencias y panel de administración.

Arranque local:   python app.py
En producción:    gunicorn -w 3 -b 0.0.0.0:8000 app:app
La configuración (admin, contraseña, clave de sesión) sale del archivo .env.

La vista previa es gratis. "Generar archivos" descuenta 1 de la licencia y deja listos el
3MF y el STL, que luego se bajan desde "Mis generaciones" sin volver a cobrar.
"""
import csv
import json
import os
import re
import threading
import time
from dataclasses import asdict
from datetime import timedelta
from functools import wraps
from io import BytesIO, StringIO
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, request, send_file, session

import datos
from generador_stl import (APP, AQUI, CARPETA_ADORNOS, CARPETA_PATRONES, CONTACTO,
                           CAMA_TIPICA, MARCA, VERSION, Parametros,
                           adornos_disponibles, construir_con_analisis, exportar_3mf,
                           exportar_stl, exportar_stl_por_color, fuentes_instaladas,
                           miniatura_png, parametros_desde_dict, patrones_disponibles,
                           svg_a_poligono, svg_dentro_de)

REGALO_DE_BIENVENIDA = 1    # generaciones limpias que lleva de serie una cuenta nueva
MAX_SVG = 2_000_000
CARPETA_WEB = os.path.join(AQUI, "web")
LIMITE_INVITADO = 40      # vistas previas por minuto e IP (los invitados no pagan nada)
LIMITE_CUENTA = 150
LIMPIAR_CADA = 3600       # cada cuánto se revisa si hay invitados viejos (segundos)


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

_peticiones = {}          # ponytail: contador por IP en memoria, por proceso
_ultima_limpieza = 0.0

_lock_dibujo = threading.Lock()  # ponytail: matplotlib no es seguro entre hilos; 1 miniatura a la vez
_fallos_login = {}               # ponytail: freno anti-fuerza-bruta en memoria, por proceso


# ------------------------------------------------------------------ IP y bloqueos
def ip_cliente():
    """Detrás de nginx o un balanceador llega en X-Forwarded-For; si no, la conexión directa."""
    reenviada = request.headers.get("X-Forwarded-For", "")
    return (reenviada.split(",")[0].strip() if reenviada else request.remote_addr) or "?"


def permitido(clave: str, limite: int, ventana: int = 60) -> bool:
    """Freno sencillo por IP: como mucho `limite` llamadas en `ventana` segundos."""
    ahora = time.time()
    marcas = [t for t in _peticiones.get(clave, []) if ahora - t < ventana]
    if len(marcas) >= limite:
        _peticiones[clave] = marcas
        return False
    marcas.append(ahora)
    _peticiones[clave] = marcas
    if len(_peticiones) > 5000:   # no dejar que el diccionario crezca sin fin
        for k in [k for k, v in _peticiones.items() if not v or ahora - v[-1] > ventana]:
            _peticiones.pop(k, None)
    return True


def limpiar_invitados_de_vez_en_cuando():
    global _ultima_limpieza
    if time.time() - _ultima_limpieza < LIMPIAR_CADA:
        return
    _ultima_limpieza = time.time()
    dias = int(os.environ.get("INVITADOS_DIAS", "2") or 0)
    borrados = datos.borrar_invitados_viejos(dias)
    if borrados:
        print(f"Limpieza: {borrados} invitado(s) sin actividad en {dias} días.")


@app.before_request
def cortar_bloqueados():
    if request.endpoint == "estilo":
        return None
    if datos.ip_bloqueada(ip_cliente()):
        session.clear()   # además de cortar, se le cierra la sesión
        if request.path.startswith("/api/"):
            return jsonify(error="Acceso bloqueado."), 403
        return (f"<h1>Acceso bloqueado</h1><p>Escribe a {CONTACTO} "
                "si crees que es un error.</p>"), 403
    limpiar_invitados_de_vez_en_cuando()
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
    """Un invitado SÍ puede abrir esta pantalla: es la única forma de que se cree la cuenta
    que necesita para generar. Solo se redirige a quien ya tiene cuenta de verdad."""
    u = usuario_actual()
    return redirect("/") if (u and not u["es_invitado"]) else pagina("login.html")


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


@app.post("/registro")
def registro():
    """Cualquiera puede crearse una cuenta con su correo. Sin licencia ya puede generar,
    pero los archivos salen con el texto marcado; la licencia la da el administrador."""
    if not permitido("registro:" + ip_cliente(), 6):
        return redirect("/login?error=espera")
    try:
        uid = datos.crear_usuario(request.form.get("usuario", ""),
                                  request.form.get("clave", ""),
                                  correo=request.form.get("correo", ""))
    except ValueError as e:
        return redirect("/login?error=" + quote(str(e)))
    # de bienvenida, una generación limpia: para probarlo de verdad hay que poder bajarse
    # un archivo sin la marca, y ya luego se pide licencia
    datos.crear_licencia(uid, None, REGALO_DE_BIENVENIDA, nota="regalo de bienvenida")
    datos.anotar_ip(uid, ip_cliente())
    session.clear()
    session["uid"] = uid
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


@app.get("/api/svg/<tipo>/<path:nombre>")
@pide_login
def api_svg(tipo, nombre):
    """Sirve un patrón o adorno para verlo en la biblioteca."""
    ruta = _ruta_svg(tipo, nombre)
    if not ruta:
        return "No encontrado", 404
    return send_file(ruta, mimetype="image/svg+xml")


# ------------------------------------------------------------------ API del usuario
@app.get("/api/yo")
@pide_login
def api_yo():
    u = request.usuario
    return jsonify(usuario=u["alias"] or u["usuario"], es_admin=bool(u["es_admin"]),
                   es_invitado=bool(u["es_invitado"]), correo=u["correo"],
                   con_licencia=bool(datos.licencia_vigente(u["id"])),
                   contacto=CONTACTO, resumen=datos.resumen_usuario(u["id"]))


@app.post("/api/clave")
@pide_login
def api_cambiar_clave():
    """Cada uno cambia la suya, comprobando antes la que tenía."""
    u = request.usuario
    if u["es_invitado"]:
        return jsonify(error="Los invitados no tienen contraseña."), 400
    try:
        d = cuerpo_json()
        if not datos.verificar_login(u["usuario"], d.get("actual", "")):
            return jsonify(error="La contraseña actual no es correcta."), 403
        datos.cambiar_clave(u["id"], d.get("nueva", ""))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.get("/api/config")
@pide_login
def api_config():
    return jsonify(app={"nombre": APP, "version": VERSION, "marca": MARCA,
                        "contacto": CONTACTO, "cama": CAMA_TIPICA},
                   defaults=asdict(Parametros()), fuentes=fuentes_instaladas(),
                   patrones=patrones_disponibles(), adornos=adornos_disponibles())


def _construir_desde(cuerpo):
    """dict -> (Parametros, niveles, analisis). Los errores suben como ValueError."""
    p = parametros_desde_dict(cuerpo or {})
    niveles, analisis = construir_con_analisis(p)
    return p, niveles, analisis


def texto_de_invitado(texto: str) -> str:
    """Sin licencia, el texto sale partido por la mitad con un '+': Medina -> Med+ina."""
    t = (texto or "").strip()
    if not t:
        return t
    return (t[:len(t) // 2] + "+" + t[len(t) // 2:]) if len(t) > 1 else t + "+"


def _nombre_archivo(p: Parametros):
    if p.tipo == "organizador":
        base = f"organizador_{p.org_texto.strip() or 'sin_nombre'}"
    elif p.tipo == "cuadro":
        base = f"llaves_{p.cua_familia.strip() or 'sin_nombre'}"
    elif p.tipo == "marca":
        base = f"marcapaginas_{(p.mar_texto or p.mar_inicial).strip() or 'sin_nombre'}"
    else:
        base = f"{p.inicial.strip() or 'letra'}_{p.texto.strip() or 'sin_texto'}"
    return re.sub(r"[^\w\-]+", "_", base)[:60] or "monkeds"


def _responder_modelo(niveles, p: Parametros, formato: str):
    if formato == "stl":
        datos_bin, tipo = exportar_stl(niveles), "model/stl"
    elif formato == "zip":   # un STL por filamento, para quien no lee los colores del 3MF
        datos_bin, tipo = exportar_stl_por_color(niveles), "application/zip"
    else:   # al descargar se funde una pieza por color: un objeto por filamento
        datos_bin, tipo = exportar_3mf(niveles, fundir=True), "model/3mf"
    nombre = _nombre_archivo(p) + ("_por_colores" if formato == "zip" else "")
    return send_file(BytesIO(datos_bin), mimetype=tipo, as_attachment=True,
                     download_name=f"{nombre}.{formato}")


@app.post("/api/preview")
@pide_login
def api_preview():
    """Vista previa 3D: no descuenta licencia ni se guarda. El análisis (volúmenes y avisos)
    viaja en una cabecera; el coste y el precio los calcula el navegador y no se guardan."""
    limite = LIMITE_INVITADO if request.usuario["es_invitado"] else LIMITE_CUENTA
    if not permitido(ip_cliente(), limite):
        return jsonify(error="Demasiadas vistas previas seguidas. Espera un momento."), 429
    try:
        p, niveles, analisis = _construir_desde(cuerpo_json())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    r = send_file(BytesIO(exportar_3mf(niveles)), mimetype="model/3mf")
    r.headers["X-Modelo"] = json.dumps(analisis, ensure_ascii=True)   # ASCII: va en una cabecera
    return r


@app.post("/api/generar")
@pide_login
def api_generar():
    """Registra la generación y deja listos los formatos: se bajan después por
    /api/generacion/<id>/3mf, /stl o /zip, sin volver a cobrar.
    Los invitados no generan: para eso hay que tener cuenta, que es gratis. Con licencia
    vigente consume 1 y el texto sale tal cual; sin licencia no consume nada, pero el texto
    sale marcado con un '+'."""
    try:
        cuerpo = cuerpo_json()
    except ValueError as e:
        return jsonify(error=str(e)), 400
    if request.usuario["es_invitado"]:
        return jsonify(error="Como invitado puedes diseñar y ver la vista previa todo lo que "
                             "quieras, pero para generar los archivos necesitas una cuenta. "
                             "Créala en un minuto desde la pantalla de entrada."), 403
    uid = request.usuario["id"]
    con_marca = not datos.licencia_vigente(uid)
    if con_marca:      # solo se marca lo que venga escrito: un campo ausente sigue ausente
        cuerpo = dict(cuerpo or {})
        for campo in ("texto", "org_texto", "cua_familia", "mar_texto"):
            if cuerpo.get(campo):
                cuerpo[campo] = texto_de_invitado(cuerpo[campo])
    try:
        p, niveles, analisis = _construir_desde(cuerpo)
    except ValueError as e:
        return jsonify(error=str(e)), 400

    with _lock_dibujo:
        mini = miniatura_png(niveles)
    try:
        gen_id = datos.registrar_generacion(uid, _nombre_archivo(p), "3mf+stl", asdict(p), mini,
                                            ip=ip_cliente(), exigir_licencia=not con_marca)
    except datos.SinLicencia as e:
        return jsonify(error=str(e)), 402
    return jsonify(id=gen_id, nombre=_nombre_archivo(p), con_marca=con_marca,
                   texto={"organizador": p.org_texto, "cuadro": p.cua_familia,
                          "marca": p.mar_texto}.get(p.tipo, p.texto),
                   analisis=analisis, resumen=datos.resumen_usuario(uid))


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
    if formato not in ("stl", "3mf", "zip"):
        return jsonify(error="Formato no válido."), 400
    g = datos.generacion(gen_id, None if request.usuario["es_admin"] else request.usuario["id"])
    if not g:
        return jsonify(error="No encontrada"), 404
    try:
        p, niveles, _ = _construir_desde(json.loads(g["parametros"]))
    except ValueError as e:
        return jsonify(error=f"No se pudo rehacer: {e}"), 400
    return _responder_modelo(niveles, p, formato)


@app.post("/api/canjear")
@pide_login
def api_canjear():
    """El usuario canjea un código y se le crea la licencia, sin pasar por el admin."""
    if request.usuario["es_invitado"]:
        return jsonify(error="Necesitas una cuenta para canjear un código."), 403
    try:
        datos.canjear_codigo(cuerpo_json().get("codigo", ""), request.usuario["id"])
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(resumen=datos.resumen_usuario(request.usuario["id"]))


# ---------- plantillas: cada uno guarda las suyas (invitados incluidos).
# Las del admin van sin dueño y las ve todo el mundo.
def _plantilla_visible(pid):
    """La plantilla si es de la casa o del que la pide; si no, None."""
    pl = datos.plantilla(pid)
    if pl and (pl["usuario_id"] is None or pl["usuario_id"] == request.usuario["id"]):
        return pl
    return None


@app.get("/api/plantillas")
@pide_login
def api_plantillas():
    return jsonify(plantillas=datos.listar_plantillas(request.usuario["id"]))


@app.get("/api/plantilla/<int:pid>")
@pide_login
def api_plantilla(pid):
    pl = _plantilla_visible(pid)
    if not pl:
        return jsonify(error="No encontrada"), 404
    return jsonify(parametros=json.loads(pl["parametros"]))


@app.get("/api/plantilla/<int:pid>/miniatura")
@pide_login
def api_plantilla_miniatura(pid):
    pl = _plantilla_visible(pid)
    if not pl or not pl["miniatura"]:
        return "No encontrada", 404
    return send_file(BytesIO(pl["miniatura"]), mimetype="image/png")


@app.post("/api/plantillas")
@pide_login
def api_guardar_plantilla():
    try:
        d = cuerpo_json()
        p, niveles, _ = _construir_desde(d.get("parametros") or {})
        with _lock_dibujo:
            mini = miniatura_png(niveles)
        # el admin guarda para todos; el resto (y los invitados) solo para sí mismos
        dueno = None if request.usuario["es_admin"] else request.usuario["id"]
        datos.guardar_plantilla(d.get("nombre", ""), asdict(p), mini, dueno)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(plantillas=datos.listar_plantillas(request.usuario["id"]))


@app.delete("/api/plantillas/<int:pid>")
@pide_login
def api_borrar_plantilla(pid):
    pl = datos.plantilla(pid)
    if not pl:
        return jsonify(error="No encontrada"), 404
    if pl["usuario_id"] != request.usuario["id"] and not request.usuario["es_admin"]:
        return jsonify(error="Esa plantilla no es tuya."), 403
    datos.borrar_plantilla(pid)
    return jsonify(plantillas=datos.listar_plantillas(request.usuario["id"]))


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


@app.delete("/api/admin/usuarios/<int:uid>")
@pide_admin
def api_admin_borrar_usuario(uid):
    """Elimina un usuario con sus licencias y generaciones. No tiene vuelta atrás."""
    if uid == request.usuario["id"]:
        return jsonify(error="No puedes eliminar tu propio usuario."), 400
    u = datos.obtener_usuario(uid)
    if not u:
        return jsonify(error="Ese usuario ya no existe."), 404
    if u["usuario"] == os.environ.get("ADMIN_USUARIO", "admin"):
        return jsonify(error="Es el administrador del .env: se volvería a crear al reiniciar."), 400
    datos.borrar_usuario(uid)
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


@app.get("/api/admin/codigos")
@pide_admin
def api_admin_codigos():
    return jsonify(codigos=datos.listar_codigos())


@app.post("/api/admin/codigos")
@pide_admin
def api_admin_crear_codigos():
    try:
        d = cuerpo_json()
        nuevos = datos.crear_codigos(d.get("cuantos", 1), d.get("dias"),
                                     d.get("max_generaciones"), d.get("nota", ""))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(nuevos=nuevos, codigos=datos.listar_codigos())


@app.delete("/api/admin/codigos/<codigo>")
@pide_admin
def api_admin_borrar_codigo(codigo):
    datos.borrar_codigo(codigo)
    return jsonify(codigos=datos.listar_codigos())


@app.get("/api/admin/estadisticas")
@pide_admin
def api_admin_estadisticas():
    return jsonify(datos.estadisticas())


@app.get("/api/admin/csv/<que>")
@pide_admin
def api_admin_csv(que):
    """Descarga en CSV para llevar las cuentas fuera de la aplicación."""
    if que == "generaciones":
        filas = datos.generaciones_todas(limite=100000)
        columnas = ["id", "creada", "nombre", "usuario", "alias", "es_invitado", "ip"]
    elif que == "usuarios":
        filas = datos.listar_usuarios()
        for f in filas:
            f.update({"restantes": datos.resumen_usuario(f["id"])["restantes"]})
        columnas = ["id", "usuario", "alias", "es_admin", "es_invitado", "activo",
                    "creado", "generaciones", "restantes", "ultima_ip"]
    else:
        return jsonify(error="Solo: generaciones o usuarios"), 404
    salida = StringIO()
    escritor = csv.DictWriter(salida, fieldnames=columnas, extrasaction="ignore")
    escritor.writeheader()
    escritor.writerows(filas)
    return Response(salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{que}.csv"'})


# ------------------------------------------------------------------ subir SVG (solo admin)
def _guardar_svg(carpeta, nombre, contenido):
    if len(contenido) > MAX_SVG:
        raise ValueError("El SVG es demasiado grande (máx. 2 MB).")
    base = os.path.splitext(os.path.basename(str(nombre or "archivo")))[0]
    limpio = (re.sub(r"[^\w\-]+", "_", base).strip("_")[:60] or "archivo") + ".svg"
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


def _carpeta_svg(tipo):
    return {"patron": CARPETA_PATRONES, "adorno": CARPETA_ADORNOS}.get(tipo)


def _ruta_svg(tipo, nombre):
    """Ruta real de un SVG, con subcarpetas, y solo si está dentro de su carpeta (nada de ../)."""
    carpeta = _carpeta_svg(tipo)
    return svg_dentro_de(carpeta, nombre) if carpeta else None


def _listas_svg():
    return {"patrones": patrones_disponibles(), "adornos": adornos_disponibles()}


@app.delete("/api/admin/svg/<tipo>/<path:nombre>")
@pide_admin
def api_admin_borrar_svg(tipo, nombre):
    ruta = _ruta_svg(tipo, nombre)
    if not ruta:
        return jsonify(error="No encontrado"), 404
    os.remove(ruta)
    return jsonify(**_listas_svg())


@app.post("/api/admin/svg/<tipo>/<path:nombre>")
@pide_admin
def api_admin_renombrar_svg(tipo, nombre):
    """Renombra un SVG. Las generaciones antiguas que lo usaban dejarán de rehacerse."""
    ruta = _ruta_svg(tipo, nombre)
    if not ruta:
        return jsonify(error="No encontrado"), 404
    try:
        nuevo = cuerpo_json().get("nombre", "")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    base = os.path.splitext(os.path.basename(str(nuevo)))[0]
    limpio = (re.sub(r"[^\w\-]+", "_", base).strip("_")[:60] or "") + ".svg"
    if limpio == ".svg":
        return jsonify(error="Ponle un nombre válido."), 400
    destino = os.path.join(_carpeta_svg(tipo), limpio)
    if os.path.exists(destino) and os.path.abspath(destino) != os.path.abspath(ruta):
        return jsonify(error=f"Ya existe un archivo llamado '{limpio}'."), 400
    os.replace(ruta, destino)
    return jsonify(nombre=limpio, **_listas_svg())


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
