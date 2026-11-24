"""ファイルの置き場所をまとめて定義する。

exe 化しても動くように、利用者ごとのデータ（ログイン情報・設定・状態）は
%LOCALAPPDATA%\\kibaco-sync に置き、同梱リソースは exe の展開先から読む。
"""
import os
import sys
from pathlib import Path

APP_NAME = "kibaco-sync"
FROZEN = getattr(sys, "frozen", False)

# 同梱リソース（client_secret.json など）の場所
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

# 利用者ごとのデータの場所
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
DATA_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DIR = DATA_DIR / "profile"          # 専用 Edge プロファイル
STATE_FILE = DATA_DIR / "kibaco_cookies.json"
CONFIG_FILE = DATA_DIR / "config.json"
FILES_STATE = DATA_DIR / "files_state.json"
TOKEN_FILE = DATA_DIR / "google_token.json"
CAL_STATE = DATA_DIR / "gcal_state.json"
LOG_FILE = DATA_DIR / "sync.log"
LOCK_FILE = DATA_DIR / "sync.lock"


def client_secret_path() -> Path:
    """OAuth クライアント情報。利用者が置いたものを優先し、なければ同梱版を使う。"""
    own = DATA_DIR / "client_secret.json"
    return own if own.exists() else RESOURCE_DIR / "client_secret.json"


def launch_command(*args: str) -> list[str]:
    """このアプリ自身を起動するコマンド（タスクスケジューラ登録用）。"""
    if FROZEN:
        return [sys.executable, *args]
    # 開発時は pythonw で app.py を起動する
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pyw), str(Path(__file__).resolve().parent / "app.py"), *args]
