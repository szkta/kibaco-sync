"""Windows タスクスケジューラへの自動同期の登録・解除。"""
from __future__ import annotations

import subprocess

from paths import launch_command

TASK_NAME = "kibaco同期"


def _ps(script: str) -> subprocess.CompletedProcess:
    # PowerShell 5.1 でも日本語が化けないよう、出力を UTF-8 にしてから実行する
    full = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", full],
                          capture_output=True, text=True, encoding="utf-8",
                          creationflags=subprocess.CREATE_NO_WINDOW)


def _q(s: str) -> str:
    """PowerShell の単一引用符文字列にする。"""
    return "'" + s.replace("'", "''") + "'"


def register(interval_minutes: int) -> None:
    """ログオン時と、指定した間隔ごとに同期するタスクを登録する（既存は上書き）。"""
    cmd = launch_command("--sync")
    exe, args = cmd[0], " ".join(f'"{a}"' for a in cmd[1:])
    script = f"""
$a = New-ScheduledTaskAction -Execute {_q(exe)} -Argument {_q(args)}
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes {int(interval_minutes)})
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
     -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName {_q(TASK_NAME)} -Action $a -Trigger @($t1,$t2) -Settings $s `
     -Description 'kibaco の課題と資料を同期' -Force | Out-Null
"""
    r = _ps(script)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "タスクの登録に失敗しました")


def unregister() -> None:
    _ps(f"Unregister-ScheduledTask -TaskName {_q(TASK_NAME)} -Confirm:$false -ErrorAction SilentlyContinue")


def next_run() -> str | None:
    """次回の実行予定時刻（未登録なら None）。"""
    r = _ps(f"$i = Get-ScheduledTaskInfo -TaskName {_q(TASK_NAME)} -ErrorAction Stop; "
            "$i.NextRunTime.ToString('yyyy/MM/dd HH:mm')")
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None
