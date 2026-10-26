@echo off
rem Doble clic para renovar los tokens de Multiadmin.
rem Busca un Python que funcione de verdad (el del venv puede apuntar a una
rem instalacion que ya no existe). El script no necesita librerias externas.
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."

set "PY="
call :probar "venv\Scripts\python.exe"
if not defined PY call :probar py -3
if not defined PY call :probar python
if not defined PY call :probar python3
if not defined PY call :probar "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY call :probar "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY call :probar "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if not defined PY (
  echo.
  echo No se encontro ningun Python que funcione en este equipo.
  echo Instala Python 3 desde https://www.python.org/downloads/
  echo y marca la casilla "Add python.exe to PATH". Luego vuelve a hacer doble clic aqui.
  echo.
  pause
  exit /b 1
)

%PY% "tools\generar_env_multiadmin_tokens.py" %*
echo.
pause
exit /b

:probar
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=%*"
exit /b
