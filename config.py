"""設定の読み書き（未設定の項目は既定値で補う）。"""
import json
from datetime import date
from pathlib import Path

from paths import CONFIG_FILE


def current_academic_year() -> str:
    """4 月始まりの年度を返す。"""
    today = date.today()
    return str(today.year if today.month >= 4 else today.year - 1)


def defaults() -> dict:
    return {
        "download_dir": str(Path.home() / "Documents" / "kibaco"),
        "site_prefixes": [current_academic_year()],
        "enable_files": True,
        "enable_calendar": True,
        "calendar_name": "kibaco課題",
        "past_days": 14,
        "event_minutes": 30,
        "reminders_minutes": [1440, 180],
        "interval_minutes": 120,
        "auto_sync": False,
    }


def load() -> dict:
    cfg = defaults()
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
