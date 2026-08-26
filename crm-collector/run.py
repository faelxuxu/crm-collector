"""Atalho para rodar o servidor: python run.py"""
import os
import sys

# Garante UTF-8 no console (Windows cp1252 quebra emojis)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.main import create_app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n[CRM Collector] rodando em http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
