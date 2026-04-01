"""Generic intake app — case-type-driven intake funnels for Jaskot Law."""

import os
import logging

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from extensions import db
log = logging.getLogger("generic-intake")


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(32).hex())
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:////app/data/intake.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    from routes.intake import intake_bp
    from routes.api import api_bp
    from routes.webhooks import webhooks_bp
    from routes.staff import staff_bp

    app.register_blueprint(intake_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(staff_bp)

    with app.app_context():
        import models  # noqa: F401 — registers models with SQLAlchemy
        db.create_all()

        # --- Manual migrations (SQLite ALTER TABLE) ---
        _migrate_columns = [
            ("intake_session", "retainer_content_json", "TEXT"),
            ("intake_session", "custom_case_type_name", "VARCHAR(200) DEFAULT ''"),
            ("intake_session", "fee_type", "VARCHAR(20) DEFAULT 'hourly'"),
            ("intake_session", "initial_retainer_cents", "INTEGER"),
            ("intake_session", "monthly_payment_cents", "INTEGER"),
            ("intake_session", "monthly_start_date", "VARCHAR(100) DEFAULT ''"),
            ("intake_session", "trust_minimum_cents", "INTEGER"),
            ("intake_session", "scope_text", "TEXT DEFAULT ''"),
            ("intake_session", "signing_attorney", "VARCHAR(200) DEFAULT ''"),
            ("intake_session", "client_signatory", "VARCHAR(200) DEFAULT ''"),
        ]
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        existing = {col["name"] for col in inspector.get_columns("intake_session")}
        for table, col, col_type in _migrate_columns:
            if col not in existing:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                log.info("Added column %s.%s", table, col)
        db.session.commit()

    @app.route("/intake/health")
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5001)
