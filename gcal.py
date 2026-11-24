"""Google カレンダーへの課題同期。

普段の Google アカウントで OAuth 認証する。権限は「このアプリが作った
カレンダーだけ」を操作できる calendar.app.created に絞っている。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from paths import CAL_STATE, TOKEN_FILE, client_secret_path

SCOPES = ["https://www.googleapis.com/auth/calendar.app.created"]
JST = timezone(timedelta(hours=9))


def get_service(interactive: bool = False):
    """Calendar API クライアントを返す。interactive=True のときだけブラウザ認証する。"""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Google の連携が必要です。アプリの「Google と連携」を押してください。")
        secret = client_secret_path()
        if not secret.exists():
            raise RuntimeError(f"{secret} がありません。")
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
        creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_calendar_id(service, name: str) -> str:
    """専用カレンダーの ID を返す（なければ作成する）。"""
    if CAL_STATE.exists():
        cal_id = json.loads(CAL_STATE.read_text(encoding="utf-8")).get("calendar_id")
        if cal_id:
            try:
                service.calendars().get(calendarId=cal_id).execute()
                return cal_id
            except Exception:
                pass  # 手動で削除された場合は作り直す
    cal = service.calendars().insert(body={"summary": name, "timeZone": "Asia/Tokyo"}).execute()
    CAL_STATE.write_text(json.dumps({"calendar_id": cal["id"]}), encoding="utf-8")
    return cal["id"]


def build_event(a: dict, site_title: str, cfg: dict) -> dict:
    """課題 1 件からカレンダー予定の内容を作る。"""
    due = datetime.fromtimestamp(a["dueTime"]["epochSecond"], JST)
    start = due - timedelta(minutes=cfg.get("event_minutes", 30))
    site_url = f"https://kibaco.tmu.ac.jp/portal/site/{a['context']}"
    lines = [f"授業: {site_title}", f"締切: {due:%Y/%m/%d %H:%M}"]
    close = a.get("closeTime") or {}
    if close.get("epochSecond") and close["epochSecond"] != a["dueTime"]["epochSecond"]:
        lines.append(f"受付終了: {datetime.fromtimestamp(close['epochSecond'], JST):%Y/%m/%d %H:%M}")
    lines.append(site_url)
    return {
        "summary": f"【課題】{a['title'].strip()}（{site_title}）",
        "description": "\n".join(lines),
        "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Tokyo"},
        "end": {"dateTime": due.isoformat(), "timeZone": "Asia/Tokyo"},
        "source": {"title": "kibaco", "url": site_url},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in cfg.get("reminders_minutes", [])],
        },
        "extendedProperties": {"private": {"kibacoId": a["id"]}},
    }


def _same(old: dict, new: dict) -> bool:
    """更新が必要かを判定する（主要な項目だけ比較）。"""
    def ts(e, k):
        return datetime.fromisoformat(e[k]["dateTime"]).timestamp()
    return (
        old.get("summary") == new["summary"]
        and old.get("description") == new["description"]
        and ts(old, "start") == ts(new, "start")
        and ts(old, "end") == ts(new, "end")
    )


def sync_assignments(assignments: list[dict], site_titles: dict[str, str], cfg: dict) -> str:
    """課題一覧をカレンダーに反映する（追加・更新・消えた課題の削除）。"""
    service = get_service()
    cal_id = get_calendar_id(service, cfg.get("calendar_name", "kibaco課題"))

    # 既存の予定を kibacoId で引けるようにする
    existing: dict[str, dict] = {}
    token = None
    while True:
        res = service.events().list(calendarId=cal_id, pageToken=token, maxResults=2500,
                                    showDeleted=False).execute()
        for e in res.get("items", []):
            kid = e.get("extendedProperties", {}).get("private", {}).get("kibacoId")
            if kid:
                existing[kid] = e
        token = res.get("nextPageToken")
        if not token:
            break

    added = updated = deleted = 0
    seen = set()
    for a in assignments:
        seen.add(a["id"])
        body = build_event(a, site_titles.get(a["context"], a["context"]), cfg)
        old = existing.get(a["id"])
        if old is None:
            service.events().insert(calendarId=cal_id, body=body).execute()
            added += 1
        elif not _same(old, body):
            service.events().update(calendarId=cal_id, eventId=old["id"], body=body).execute()
            updated += 1

    # kibaco から消えた（取り下げられた）課題のうち、まだ締切前のものだけ削除する
    now = datetime.now(JST)
    for kid, e in existing.items():
        if kid in seen:
            continue
        if datetime.fromisoformat(e["end"]["dateTime"]) > now:
            service.events().delete(calendarId=cal_id, eventId=e["id"]).execute()
            deleted += 1
    return f"追加 {added} / 更新 {updated} / 削除 {deleted}"
