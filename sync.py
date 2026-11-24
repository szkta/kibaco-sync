"""kibaco の課題を Google カレンダーへ、資料をローカルフォルダへ同期する処理本体。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from kibaco import BASE_URL, LoginRequired, ensure_login, get_json, open_context
from paths import FILES_STATE, LOCK_FILE, LOG_FILE


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass  # コンソールのない exe では print できないことがある
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def safe_name(name: str) -> str:
    """Windows で使えない文字を置き換える。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip().rstrip(".")
    return name[:120] or "_"


def target_sites(ctx, cfg: dict) -> dict[str, str]:
    """対象の授業サイト {siteId: タイトル} を返す。"""
    sites = get_json(ctx, "/direct/site.json?_limit=1000").get("site_collection", [])
    prefixes = cfg.get("site_prefixes") or [""]
    return {s["id"]: s["title"] for s in sites if any(s["id"].startswith(p) for p in prefixes)}


# ---------------- 資料のダウンロード ----------------

def site_dir(base: Path, site_id: str, title: str) -> Path:
    """授業ごとの保存先（年度フォルダ\\授業名）。"""
    year = site_id[:4] if site_id[:4].isdigit() else "その他"
    return base / year / safe_name(title)


def download(ctx, url: str, dest: Path, modified: str, state: dict) -> bool:
    """1 ファイルを保存する。更新されていたら古い版を残してから上書きする。"""
    prev = state.get(url)
    if prev and prev.get("modified") == modified and dest.exists():
        return False
    res = ctx.request.get(url, timeout=300_000)
    if res.status in (401, 403):
        raise LoginRequired(f"{url} のダウンロードが拒否されました")
    if not res.ok:
        log(f"  ! 取得失敗 {res.status}: {url}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # 手元で書き込みをしている可能性があるので古い版は消さずに残す
        backup = dest.with_name(f"{dest.stem} (旧{datetime.now():%Y%m%d%H%M}){dest.suffix}")
        dest.rename(backup)
    dest.write_bytes(res.body())
    state[url] = {"modified": modified, "path": str(dest)}
    return True


def sync_site_files(ctx, site_id: str, folder: Path, state: dict) -> int:
    """授業サイトの「リソース」を丸ごと保存する。"""
    try:
        items = get_json(ctx, f"/direct/content/site/{site_id}.json").get("content_collection", [])
    except RuntimeError:
        return 0  # リソースツールがない授業
    prefix = f"/access/content/group/{site_id}/"
    count = 0
    for it in items:
        if it.get("type") == "collection" or it.get("hidden") or not it.get("visible", True):
            continue
        path = unquote(urlparse(it["url"]).path)
        if not path.startswith(prefix):
            continue
        parts = [safe_name(p) for p in path[len(prefix):].split("/") if p]
        dest = folder.joinpath(*parts)
        if it.get("type") == "text/url" or it.get("webLinkUrl"):
            # Web リンクはショートカットとして保存する
            link = it.get("webLinkUrl") or it["url"]
            dest = dest.with_name(safe_name(it.get("title") or dest.name) + ".url")
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(f"[InternetShortcut]\nURL={link}\n", encoding="utf-8")
                count += 1
            continue
        if download(ctx, it["url"], dest, str(it.get("modifiedDate")), state):
            log(f"  + {dest}")
            count += 1
    return count


def sync_assignment_files(ctx, assignments: list[dict], sites: dict, base: Path, state: dict) -> int:
    """課題に添付された資料（課題文の PDF など）を保存する。"""
    count = 0
    for a in assignments:
        for att in a.get("attachments") or []:
            url = att.get("url") if isinstance(att, dict) else None
            if not url:
                continue
            if url.startswith("/"):
                url = BASE_URL + url
            name = att.get("name") or unquote(urlparse(url).path.rsplit("/", 1)[-1])
            dest = (site_dir(base, a["context"], sites[a["context"]]) / "_課題添付"
                    / safe_name(a["title"]) / safe_name(name))
            if download(ctx, url, dest, str(a.get("timeLastModified")), state):
                log(f"  + {dest}")
                count += 1
    return count


# ---------------- 実行 ----------------

def _acquire_lock() -> bool:
    """二重起動を防ぐ（3 時間以上前のロックは異常終了の残骸とみなす）。"""
    if LOCK_FILE.exists() and time.time() - LOCK_FILE.stat().st_mtime < 3 * 3600:
        return False
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def run_sync(cfg: dict, do_files: bool = True, do_cal: bool = True, notify_errors: bool = False) -> int:
    """同期を 1 回実行する。戻り値: 0=成功, 1=エラー, 2=要ログイン, 3=実行中"""
    if not _acquire_lock():
        log("別の同期が実行中のためスキップしました")
        return 3
    base = Path(cfg["download_dir"])
    state = json.loads(FILES_STATE.read_text(encoding="utf-8")) if FILES_STATE.exists() else {}
    try:
        with open_context() as ctx:
            user = ensure_login(ctx)
            log(f"kibaco にログイン中: {user}")
            sites = target_sites(ctx, cfg)
            log(f"対象の授業: {len(sites)} 件")

            all_assign = get_json(ctx, "/direct/assignment/my.json").get("assignment_collection", [])
            assignments = [a for a in all_assign if a.get("context") in sites and not a.get("draft")
                           and (a.get("dueTime") or {}).get("epochSecond")]

            if do_files and cfg.get("enable_files", True):
                total = 0
                for sid, title in sites.items():
                    total += sync_site_files(ctx, sid, site_dir(base, sid, title), state)
                    FILES_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
                total += sync_assignment_files(ctx, assignments, sites, base, state)
                FILES_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
                log(f"[資料] 新規・更新 {total} 件 → {base}")

            if do_cal and cfg.get("enable_calendar", True):
                from gcal import sync_assignments
                since = time.time() - cfg.get("past_days", 14) * 86400
                recent = [a for a in assignments if a["dueTime"]["epochSecond"] >= since]
                result = sync_assignments(recent, sites, cfg)
                log(f"[カレンダー] 対象の課題 {len(recent)} 件（{result}）")
        return 0
    except LoginRequired as e:
        log(f"要ログイン: {e}")
        if notify_errors:
            notify("kibaco 同期", "再ログインが必要です。kibaco同期アプリを開いてログインしてください。")
        return 2
    except Exception as e:
        log(f"エラー: {e!r}")
        if notify_errors:
            notify("kibaco 同期", f"エラーが発生しました: {e}")
        return 1
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def notify(title: str, msg: str) -> None:
    """Windows のトースト通知を出す（失敗しても無視）。"""
    text = f"{title}: {msg}".replace("'", "")[:200]
    # 未登録の AppId だと表示されないので PowerShell の AppId を借りる
    app_id = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
        f"$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode('{text}')) > $null;"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app_id}').Show("
        "[Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=20, capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass
