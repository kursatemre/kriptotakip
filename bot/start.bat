@echo off
rem GCM Bot'u başlatır. İlk çalıştırmada Python ortamını (.venv) kurar ve config.json oluşturur.
rem Ek parametreler run.py'ye geçer: start.bat backtest --compare / start.bat symbols EUR
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Python ortami kuruluyor, bir kere yapilir...
    py -3 -m venv .venv || goto :error
    .venv\Scripts\python.exe -m pip install --upgrade pip >nul
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
)
if not exist config.json (
    copy config.example.json config.json >nul
    echo config.json olusturuldu. Sembol adlarini kontrol edin: start.bat symbols EUR
)

.venv\Scripts\python.exe run.py %*
pause
exit /b

:error
echo Kurulum basarisiz. Python 3.11+ kurulu mu? https://www.python.org/downloads/
pause
exit /b 1
