"""kibaco（東京都立大学 Sakai）へのアクセス共通処理。

ログイン状態は専用の Edge プロファイルと Cookie の保存ファイルに残し、
以降の実行ではそれを使って Sakai の /direct API を呼ぶ。
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager

from playwright.sync_api import BrowserContext, sync_playwright

from paths import PROFILE_DIR, STATE_FILE

BASE_URL = "https://kibaco.tmu.ac.jp"
# kibaco 本体の SSO 入口（kibaco-d はダッシュボードという別アプリなので使わない）
LOGIN_URL = f"{BASE_URL}/portal/login"


class LoginRequired(Exception):
    """kibaco のセッションが切れていて再ログインが必要なとき。"""


def save_state(ctx: BrowserContext) -> None:
    """セッション Cookie も含めて保存する（ブラウザを閉じると消えるため）。"""
    STATE_FILE.write_text(json.dumps(ctx.cookies(), ensure_ascii=False), encoding="utf-8")


@contextmanager
def open_context(headless: bool = True):
    """専用プロファイルで Edge を起動し、保存済み Cookie を戻したコンテキストを返す。"""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="msedge",  # Windows 標準の Edge を使う（ブラウザの同梱は不要）
            headless=headless,
            accept_downloads=True,
        )
        if STATE_FILE.exists():
            try:
                ctx.add_cookies(json.loads(STATE_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        try:
            yield ctx
        finally:
            try:
                if current_user(ctx):
                    save_state(ctx)
            except Exception:
                pass
            ctx.close()


def current_user(ctx: BrowserContext) -> str | None:
    """ログイン中のユーザー ID を返す（未ログインなら None）。"""
    res = ctx.request.get(f"{BASE_URL}/direct/session/current.json")
    if not res.ok:
        return None
    try:
        data = res.json()
    except Exception:
        return None
    return data.get("userEid") or data.get("userId")


def ensure_login(ctx: BrowserContext) -> str:
    """セッションを確認し、切れていれば SSO の自動再ログインを試みる。"""
    user = current_user(ctx)
    if user:
        return user
    # IdP 側のセッションが残っていればリダイレクトだけでログインできる
    page = ctx.new_page()
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_url(f"{BASE_URL}/portal**", timeout=30_000)
    except Exception:
        pass
    finally:
        page.close()
    user = current_user(ctx)
    if not user:
        raise LoginRequired("kibaco に再ログインが必要です。アプリの「kibaco にログイン」を押してください。")
    return user


def login_interactive(timeout_sec: int = 600) -> str | None:
    """Edge の画面を開いて利用者にログインしてもらう。成功したらユーザー ID を返す。"""
    with open_context(headless=False) as ctx:
        user = current_user(ctx)
        if user:
            return user
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URL)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            # URL ではなく API でログイン済みかを判定する
            try:
                user = current_user(ctx)
            except Exception:
                return None  # ウィンドウが閉じられた
            if user:
                save_state(ctx)
                return user
            time.sleep(3)
    return None


def get_json(ctx: BrowserContext, path: str) -> dict:
    """/direct API を呼んで JSON を返す。"""
    res = ctx.request.get(f"{BASE_URL}{path}", timeout=60_000)
    if res.status in (401, 403):
        raise LoginRequired(f"{path} へのアクセスが拒否されました（{res.status}）")
    if not res.ok:
        raise RuntimeError(f"{path} の取得に失敗しました（{res.status}）")
    return json.loads(res.text())
