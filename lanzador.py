#!/usr/bin/env python3
"""Lanzador del ejecutable portable.

El código real (generador_stl, servidor_web) va cifrado con PyArmor, así que PyInstaller no
puede ver qué librerías usa. Aquí se importan a propósito para que queden incluidas en el .exe.
"""
import matplotlib          # noqa: F401
import matplotlib.font_manager  # noqa: F401
import mapbox_earcut       # noqa: F401
import numpy               # noqa: F401
import PIL.Image           # noqa: F401
import shapely             # noqa: F401
import shapely.geometry    # noqa: F401
import shapely.ops         # noqa: F401
import svgelements         # noqa: F401
import trimesh             # noqa: F401
import trimesh.creation    # noqa: F401

import servidor_web

if __name__ == "__main__":
    servidor_web.main()
