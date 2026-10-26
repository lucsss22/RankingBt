@echo off
rem BT Ranking: sobe o servidor neste PC e abre o tunel gratuito do ngrok.
rem O endereco publico (https://....ngrok-free.app) aparece na janela do ngrok.
cd /d "%~dp0"

where ngrok >nul 2>nul
if errorlevel 1 (
    echo ngrok nao encontrado. Instale com:  winget install ngrok.ngrok
    echo e depois rode:  ngrok config add-authtoken SEU_TOKEN
    pause
    exit /b 1
)

start "ngrok - BT Ranking" ngrok http 8000
echo Servidor em http://localhost:8000  (feche esta janela para desligar)
python -m uvicorn web:app --host 127.0.0.1 --port 8000
pause
