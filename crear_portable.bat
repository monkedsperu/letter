@echo off
rem Crea la version portable OFUSCADA en dist\MonkedsLetter (y dist\MonkedsLetter.zip).
rem El codigo Python se cifra con PyArmor y el pantalla.html se minifica.
rem Requiere: pip install pyinstaller pyarmor rjsmin rcssmin trimesh shapely matplotlib numpy mapbox_earcut svgelements
cd /d "%~dp0"

echo [1/4] Ofuscando el codigo Python con PyArmor...
rmdir /s /q obf 2>nul
pyarmor gen -O obf --recursive generador_stl.py servidor_web.py || exit /b 1
copy /y lanzador.py obf\ >nul

echo [2/4] Minificando pantalla.html...
python minify_html.py pantalla.html obf\pantalla_min.html || exit /b 1

echo [3/4] Empaquetando con PyInstaller...
cd obf
python -m PyInstaller --noconfirm --clean --onedir --name MonkedsLetter ^
  --distpath ..\dist --workpath ..\build --specpath ..\build ^
  --hidden-import generador_stl --hidden-import servidor_web ^
  --hidden-import pyarmor_runtime_000000 --collect-all pyarmor_runtime_000000 ^
  --hidden-import mapbox_earcut --hidden-import svgelements --collect-data trimesh ^
  --exclude-module torch --exclude-module torchaudio --exclude-module torchvision ^
  --exclude-module onnxruntime --exclude-module scipy --exclude-module cryptography ^
  --exclude-module pandas --exclude-module pydantic --exclude-module pydantic_core ^
  --exclude-module networkx --exclude-module IPython --exclude-module tkinter ^
  lanzador.py || (cd .. & exit /b 1)
cd ..

echo [4/4] Copiando datos y comprimiendo...
for %%d in (web patrones adornos fuentes) do xcopy /e /i /y /q %%d dist\MonkedsLetter\%%d >nul
copy /y obf\pantalla_min.html dist\MonkedsLetter\pantalla.html >nul
copy /y LEEME.txt dist\MonkedsLetter\ >nul
powershell -NoProfile -Command "Compress-Archive -Force dist\MonkedsLetter dist\MonkedsLetter.zip"
echo.
echo Listo: dist\MonkedsLetter\MonkedsLetter.exe  (codigo ofuscado; copia la carpeta o el .zip)
