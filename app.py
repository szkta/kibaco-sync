"""kibaco 同期アプリ（設定画面）。

  kibaco同期.exe          → 設定画面を開く
  kibaco同期.exe --sync   → 画面を出さずに 1 回同期する（タスクスケジューラ用）
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import config
from paths import LOG_FILE, TOKEN_FILE, client_secret_path

INTERVALS = [  # (表示名, 分)
    ("30分ごと", 30), ("1時間ごと", 60), ("2時間ごと", 120), ("3時間ごと", 180),
    ("6時間ごと", 360), ("12時間ごと", 720), ("1日1回", 1440),
]


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = config.load()
        self.jobs: queue.Queue = queue.Queue()
        self.busy = False
        root.title("kibaco 同期")
        root.resizable(False, False)
        self._build()
        self._load_into_form()
        self._refresh_google()
        self._refresh_next_run()
        self._refresh_log()
        self.root.after(200, self._poll)
        self._run_bg(self._check_kibaco)

    # ---------- 画面の組み立て ----------
    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        f = ttk.Frame(self.root, padding=12)
        f.grid()

        acc = ttk.LabelFrame(f, text="アカウント", padding=8)
        acc.grid(row=0, column=0, sticky="ew", **pad)
        ttk.Label(acc, text="kibaco:").grid(row=0, column=0, sticky="w")
        self.kibaco_status = ttk.Label(acc, text="確認中…", width=34)
        self.kibaco_status.grid(row=0, column=1, sticky="w")
        self.btn_login = ttk.Button(acc, text="kibaco にログイン", command=self.on_login)
        self.btn_login.grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Label(acc, text="Google:").grid(row=1, column=0, sticky="w")
        self.google_status = ttk.Label(acc, text="", width=34)
        self.google_status.grid(row=1, column=1, sticky="w")
        self.btn_google = ttk.Button(acc, text="Google と連携", command=self.on_google)
        self.btn_google.grid(row=1, column=2, sticky="ew", padx=4, pady=2)

        st = ttk.LabelFrame(f, text="同期の設定", padding=8)
        st.grid(row=1, column=0, sticky="ew", **pad)
        self.v_files = tk.BooleanVar()
        ttk.Checkbutton(st, text="授業資料をダウンロードする", variable=self.v_files).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(st, text="保存先:").grid(row=1, column=0, sticky="w")
        self.v_dir = tk.StringVar()
        ttk.Entry(st, textvariable=self.v_dir, width=44).grid(row=1, column=1, sticky="w")
        ttk.Button(st, text="参照…", command=self.on_browse).grid(row=1, column=2, padx=4)
        self.v_cal = tk.BooleanVar()
        ttk.Checkbutton(st, text="課題の締切を Google カレンダーに登録する", variable=self.v_cal).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(st, text="対象年度:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.v_years = tk.StringVar()
        ttk.Entry(st, textvariable=self.v_years, width=20).grid(row=3, column=1, sticky="w", pady=(6, 0))
        ttk.Label(st, text="（カンマ区切り 例: 2025, 2026）", foreground="gray").grid(
            row=4, column=1, sticky="w")

        au = ttk.LabelFrame(f, text="自動同期", padding=8)
        au.grid(row=2, column=0, sticky="ew", **pad)
        self.v_auto = tk.BooleanVar()
        ttk.Checkbutton(au, text="自動で同期する（ログオン時と一定間隔）", variable=self.v_auto).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(au, text="更新頻度:").grid(row=1, column=0, sticky="w")
        self.v_interval = tk.StringVar()
        ttk.Combobox(au, textvariable=self.v_interval, values=[n for n, _ in INTERVALS],
                     state="readonly", width=12).grid(row=1, column=1, sticky="w")
        self.next_run = ttk.Label(au, text="", foreground="gray")
        self.next_run.grid(row=2, column=0, columnspan=2, sticky="w")

        bt = ttk.Frame(f)
        bt.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Button(bt, text="設定を保存", command=self.on_save).pack(side="left")
        self.btn_sync = ttk.Button(bt, text="今すぐ同期", command=self.on_sync)
        self.btn_sync.pack(side="left", padx=6)
        ttk.Button(bt, text="保存先を開く", command=self.on_open_dir).pack(side="left")

        lg = ttk.LabelFrame(f, text="ログ", padding=4)
        lg.grid(row=4, column=0, sticky="ew", **pad)
        self.log = tk.Text(lg, height=10, width=78, state="disabled", font=("Yu Gothic UI", 9))
        self.log.pack(side="left")
        sb = ttk.Scrollbar(lg, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

    def _load_into_form(self) -> None:
        c = self.cfg
        self.v_files.set(c["enable_files"])
        self.v_dir.set(c["download_dir"])
        self.v_cal.set(c["enable_calendar"])
        self.v_years.set(", ".join(c["site_prefixes"]))
        self.v_auto.set(c["auto_sync"])
        name = next((n for n, m in INTERVALS if m == c["interval_minutes"]), None)
        if name is None:  # 一覧にない値は直書きの分数として表示する
            name = f"{c['interval_minutes']}分ごと"
        self.v_interval.set(name)

    def _form_to_cfg(self) -> dict:
        c = dict(self.cfg)
        c["enable_files"] = self.v_files.get()
        c["download_dir"] = self.v_dir.get().strip()
        c["enable_calendar"] = self.v_cal.get()
        c["site_prefixes"] = [y.strip() for y in self.v_years.get().replace("、", ",").split(",") if y.strip()]
        c["auto_sync"] = self.v_auto.get()
        c["interval_minutes"] = dict(INTERVALS).get(self.v_interval.get(), c["interval_minutes"])
        return c

    # ---------- バックグラウンド処理 ----------
    def _run_bg(self, fn, *args) -> None:
        """重い処理は別スレッドで動かし、結果は self.jobs 経由で画面に反映する。"""
        def worker():
            try:
                fn(*args)
            except Exception as e:
                self.jobs.put(lambda: messagebox.showerror("エラー", str(e)))
            finally:
                self.jobs.put(self._end_busy)
        self._set_busy(True)
        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.btn_login, self.btn_google, self.btn_sync):
            b.configure(state=state)

    def _end_busy(self) -> None:
        self._set_busy(False)
        self._refresh_log()

    def _poll(self) -> None:
        while not self.jobs.empty():
            self.jobs.get()()
        if self.busy:
            self._refresh_log()
        self.root.after(1000 if self.busy else 200, self._poll)

    # ---------- 状態表示 ----------
    def _check_kibaco(self) -> None:
        from kibaco import current_user, open_context
        try:
            with open_context() as ctx:
                user = current_user(ctx)
        except Exception as e:
            user, err = None, e
        else:
            err = None
        if user:
            text = f"ログイン中（{user}）"
        elif err:
            text = f"確認できませんでした: {err}"[:60]
        else:
            text = "未ログイン"
        self.jobs.put(lambda: self.kibaco_status.configure(text=text))

    def _refresh_google(self) -> None:
        if TOKEN_FILE.exists():
            self.google_status.configure(text="連携済み")
            self.btn_google.configure(text="連携を解除")
        else:
            self.google_status.configure(text="未連携")
            self.btn_google.configure(text="Google と連携")

    def _refresh_next_run(self) -> None:
        def work():
            from scheduler import next_run
            nr = next_run()
            text = f"次回の自動同期: {nr}" if nr else "自動同期は登録されていません"
            self.jobs.put(lambda: self.next_run.configure(text=text))
        threading.Thread(target=work, daemon=True).start()

    def _refresh_log(self) -> None:
        if not LOG_FILE.exists():
            return
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(lines))
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- ボタン ----------
    def on_login(self) -> None:
        def work():
            from kibaco import login_interactive
            self.jobs.put(lambda: self.kibaco_status.configure(text="Edge でログインしてください…"))
            user = login_interactive()
            text = f"ログイン中（{user}）" if user else "ログインできませんでした"
            self.jobs.put(lambda: self.kibaco_status.configure(text=text))
        self._run_bg(work)

    def on_google(self) -> None:
        if TOKEN_FILE.exists():
            if messagebox.askyesno("確認", "Google との連携を解除しますか？\n（カレンダーの予定は消えません）"):
                TOKEN_FILE.unlink(missing_ok=True)
                self._refresh_google()
            return
        if not client_secret_path().exists():
            messagebox.showerror("エラー", "このアプリには Google 連携用の情報が含まれていません。")
            return

        def work():
            from gcal import get_calendar_id, get_service
            service = get_service(interactive=True)
            get_calendar_id(service, self.cfg.get("calendar_name", "kibaco課題"))
            self.jobs.put(self._refresh_google)
            self.jobs.put(lambda: messagebox.showinfo(
                "完了", "Google と連携しました。\nカレンダー「kibaco課題」に課題が登録されます。"))
        self._run_bg(work)

    def on_browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self.v_dir.get() or str(Path.home()))
        if d:
            self.v_dir.set(str(Path(d)))

    def on_save(self) -> bool:
        c = self._form_to_cfg()
        if c["enable_files"] and not c["download_dir"]:
            messagebox.showerror("エラー", "保存先を指定してください。")
            return False
        if not c["site_prefixes"]:
            messagebox.showerror("エラー", "対象年度を入力してください。")
            return False
        config.save(c)
        self.cfg = c
        from scheduler import register, unregister
        try:
            if c["auto_sync"]:
                register(c["interval_minutes"])
            else:
                unregister()
        except Exception as e:
            messagebox.showerror("エラー", f"自動同期の登録に失敗しました:\n{e}")
            return False
        self._refresh_next_run()
        messagebox.showinfo("保存", "設定を保存しました。")
        return True

    def on_sync(self) -> None:
        c = self._form_to_cfg()
        config.save(c)
        self.cfg = c

        def work():
            from sync import log, run_sync
            log("---- 手動同期 ----")
            code = run_sync(c)
            if code == 2:
                self.jobs.put(lambda: messagebox.showwarning(
                    "要ログイン", "kibaco のログインが切れています。「kibaco にログイン」を押してください。"))
        self._run_bg(work)

    def on_open_dir(self) -> None:
        d = Path(self.v_dir.get())
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(d)


def _startup_trace(msg: str) -> None:
    """起動直後の診断用ログ（%TEMP%\\kibaco-sync-startup.log）。"""
    import tempfile
    from datetime import datetime
    try:
        with open(Path(tempfile.gettempdir()) / "kibaco-sync-startup.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def main() -> None:
    _startup_trace(f"start argv={sys.argv} cwd={os.getcwd()} LOCALAPPDATA={os.environ.get('LOCALAPPDATA')}")
    if "--sync" in sys.argv:
        from sync import log, run_sync
        log("---- 自動同期 ----")
        sys.exit(run_sync(config.load(), notify_errors=True))
    if "--apply-settings" in sys.argv:
        # 保存済みの設定どおりに自動同期タスクを登録し直す（更新・移行用）
        from scheduler import register, unregister
        c = config.load()
        register(c["interval_minutes"]) if c["auto_sync"] else unregister()
        return
    try:
        # 高 DPI の画面で文字がぼやけないようにする
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        _startup_trace(f"exit {e.code}")
        raise
    except BaseException:
        import traceback
        _startup_trace("crash\n" + traceback.format_exc())
        raise
