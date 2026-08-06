aiogram==3.22.0
psycopg2-binary==2.9.10
python-dotenv==1.0.1
httpx==0.28.1
Pillow==11.1.0
pytesseract==0.3.13
easyocr==1.7.2
openpyxl==3.1.5
google-api-python-client==2.169.0
google-auth==2.40.0
fastapi==0.116.1
uvicorn[standard]==0.35.0
# ocr_text_llm 需 Ollama：ollama pull qwen2.5:3b
# Webhook 模式：ATTENDANCE_RUN_MODE=webhook + uvicorn webhook_app:app
# Gateway 联调默认不启动后台 worker；需要处理通知/日报等后台任务时再显式设置 ATTENDANCE_WEBHOOK_RUN_WORKERS=1
