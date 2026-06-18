@echo off
cd /d "%~dp0"

echo [1/3] ���� Ollama��OCR/AI ʶ�����
if exist ".\tools\ollama\ollama.exe" (
  start "attendance-ollama" cmd /k ".\tools\ollama\ollama.exe serve"
) else (
  start "attendance-ollama" cmd /k "ollama serve"
)

echo [2/3] ����������
start "attendance-main" cmd /k "python main.py"

echo [3/3] ���� ngrok
if exist ".\tools\ngrok\ngrok.exe" (
  start "attendance-ngrok" cmd /k ".\tools\ngrok\ngrok.exe http 8787"
) else (
  echo δ�ҵ� .\tools\ngrok\ngrok.exe
  echo ��� ngrok.exe �ŵ� tools\ngrok\ Ŀ¼������
)

echo ��ִ���������Ollama / main.py / ngrok
echo �����֡�AI���񲻿��á������� ollama �����Ƿ�ɹ����������� 11434��
pause