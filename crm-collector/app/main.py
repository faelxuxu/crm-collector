"""App factory."""
from __future__ import annotations

import os
import sys

# Força UTF-8 no console (Windows cp125a quebra emojis)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask

from app import db
from app.routes import bp


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "crm-collector-dev-key")
    # Carrega .env se existir (best-effort)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    db.init_db()
    app.register_blueprint(bp)
    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
