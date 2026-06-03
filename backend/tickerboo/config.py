"""
TickerBoo configuration — all settings pulled from environment / .env file.
Import `settings` anywhere; never read os.environ directly in app code.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the repo root (two levels up from this file)
_repo_root = Path(__file__).parent.parent.parent
load_dotenv(_repo_root / ".env", override=False)


class Settings:
    # ── Runtime ──────────────────────────────────────────────────────────
    env: str          = os.getenv("TICKERBOO_ENV", "dev")
    port: int         = int(os.getenv("TICKERBOO_PORT", "8688"))
    host: str         = os.getenv("TICKERBOO_HOST", "0.0.0.0")
    root_path: str    = os.getenv("TICKERBOO_ROOT_PATH", "")   # "/tb" on server
    version: str      = "0.5.0"

    # ── Storage ───────────────────────────────────────────────────────────
    db_path: Path     = Path(os.getenv("TICKERBOO_DB_PATH", "./data/tickerboo.db"))
    log_path: Path    = Path(os.getenv("TICKERBOO_LOG_PATH", "./logs/tickerboo.log"))
    log_level: str    = os.getenv("TICKERBOO_LOG_LEVEL", "DEBUG")

    # ── Data sources ─────────────────────────────────────────────────────
    cafef_url_prefix: str = os.getenv(
        "CAFEF_URL_PREFIX",
        "https://cafef1.mediacdn.vn/data/ami_data/",
    )

    # ── Derived ──────────────────────────────────────────────────────────
    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


settings = Settings()
