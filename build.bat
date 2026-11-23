@echo off
rem Compila Estandria para Windows.
rem   build.bat           -> dist\Estandria\Estandria.exe   (onedir, recomendado)
rem   build.bat onefile   -> dist\Estandria.exe             (un solo archivo)
setlocal
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=onedir"
if /i not "%MODE%"=="onedir" if /i not "%MODE%"=="onefile" (
    echo Uso: build.bat [onedir^|onefile]
    exit /b 2
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creando entorno virtual .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv || goto :error
) else (
    echo [1/4] Entorno virtual existente: .venv
)
set "PY=.venv\Scripts\python.exe"

echo [2/4] Instalando dependencias ...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-dev.txt || goto :error

echo [3/4] Ejecutando pruebas ...
"%PY%" -m pytest -q || goto :error

echo [4/4] Compilando en modo %MODE% ...
if /i "%MODE%"=="onefile" (set "ESTANDRIA_ONEFILE=1") else (set "ESTANDRIA_ONEFILE=0")
"%PY%" -m PyInstaller --noconfirm --clean estandria.spec || goto :error

echo.
if /i "%MODE%"=="onefile" (
    echo Listo: dist\Estandria.exe
) else (
    echo Listo: dist\Estandria\Estandria.exe  ^(distribuya la carpeta dist\Estandria completa^)
)
exit /b 0

:error
echo.
echo ERROR: la compilacion se detuvo. Revise los mensajes anteriores.
exit /b 1
