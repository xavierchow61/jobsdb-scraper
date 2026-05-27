"""JobsDB Scraper GUI - double-click launcher."""

import argparse
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import scraper

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"


class QueueWriter:
    """File-like object that pushes whole lines to a queue."""

    def __init__(self, q):
        self.q = q
        self._buf = ""

    def write(self, s):
        if not s:
            return
        self._buf += s.replace("\r", "\n")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.q.put(line)

    def flush(self):
        if self._buf:
            self.q.put(self._buf)
            self._buf = ""


class App:
    def __init__(self, root):
        self.root = root
        root.title("HK Job Scraper")
        root.geometry("820x780")
        root.minsize(720, 640)

        self.log_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.last_output_path = None

        self._build_ui()
        self._load_config()
        self._drain_log()

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        row = 0
        ttk.Label(frm, text="網站 Source:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.source_var = tk.StringVar(value="jobsdb")
        source_frm = ttk.Frame(frm)
        source_frm.grid(row=row, column=1, sticky="w", padx=6, pady=4)
        ttk.Radiobutton(
            source_frm, text="JobsDB",
            variable=self.source_var, value="jobsdb",
            command=self._on_source_change,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            source_frm, text="CTgoodjobs",
            variable=self.source_var, value="ctgoodjobs",
            command=self._on_source_change,
        ).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            source_frm, text="cpjobs",
            variable=self.source_var, value="cpjobs",
            command=self._on_source_change,
        ).pack(side="left")

        row += 1
        ttk.Label(frm, text="關鍵字 Keyword:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.keyword_var = tk.StringVar(value="Accountant")
        ttk.Entry(frm, textvariable=self.keyword_var, width=42).grid(
            row=row, column=1, sticky="we", padx=6, pady=4
        )

        row += 1
        ttk.Label(frm, text="地點 Location (空白=全港):").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.location_var = tk.StringVar(value="")
        self.location_combo = ttk.Combobox(
            frm, textvariable=self.location_var, width=40
        )
        self.location_combo.grid(row=row, column=1, sticky="we", padx=6, pady=4)
        self._refresh_location_values()

        row += 1
        ttk.Label(frm, text="最多頁數 Max pages (0 = 全部):").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.maxpages_var = tk.StringVar(value="0")
        ttk.Entry(frm, textvariable=self.maxpages_var, width=10).grid(
            row=row, column=1, sticky="w", padx=6, pady=4
        )

        row += 1
        self.fulljd_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm,
            text="抓完整 JD（含 Responsibilities / Requirements / Benefits / How to apply）",
            variable=self.fulljd_var,
        ).grid(row=row, column=1, sticky="w", padx=6, pady=4)

        row += 1
        ttk.Label(frm, text="每個 request 延遲秒數:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.delay_var = tk.StringVar(value="1.5")
        ttk.Entry(frm, textvariable=self.delay_var, width=10).grid(
            row=row, column=1, sticky="w", padx=6, pady=4
        )

        row += 1
        ttk.Label(
            frm,
            text="定時啟動 (空白=即刻；HH:MM 或 YYYY-MM-DD HH:MM):",
        ).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        self.at_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.at_var, width=24).grid(
            row=row, column=1, sticky="w", padx=6, pady=4
        )

        row += 1
        ttk.Label(frm, text="輸出資料夾 (per-run CSV):").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        out_frm = ttk.Frame(frm)
        out_frm.grid(row=row, column=1, sticky="we", padx=6, pady=4)
        self.outdir_var = tk.StringVar(value=str(APP_DIR))
        ttk.Entry(out_frm, textvariable=self.outdir_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(out_frm, text="瀏覽…", command=self._choose_dir, width=8).pack(
            side="left", padx=4
        )

        # ----- Database -----
        row += 1
        ttk.Separator(frm, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="we", pady=(8, 4)
        )

        row += 1
        ttk.Label(frm, text="Master Excel 資料庫:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        mas_frm = ttk.Frame(frm)
        mas_frm.grid(row=row, column=1, sticky="we", padx=6, pady=4)
        self.master_var = tk.StringVar(value=str(APP_DIR / "jobs_master.xlsx"))
        ttk.Entry(mas_frm, textvariable=self.master_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(mas_frm, text="瀏覽…", command=self._choose_master, width=8).pack(
            side="left", padx=4
        )

        row += 1
        self.master_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm,
            text="啟用 Master Excel 資料庫（去重 + 累積所有 sources）",
            variable=self.master_enabled_var,
        ).grid(row=row, column=1, sticky="w", padx=6, pady=2)

        # ----- CV matching -----
        row += 1
        ttk.Separator(frm, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="we", pady=(8, 4)
        )

        row += 1
        ttk.Label(frm, text="CV 檔案 (PDF / TXT):").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        cv_frm = ttk.Frame(frm)
        cv_frm.grid(row=row, column=1, sticky="we", padx=6, pady=4)
        self.cv_var = tk.StringVar(value="")
        ttk.Entry(cv_frm, textvariable=self.cv_var).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(cv_frm, text="瀏覽…", command=self._choose_cv, width=8).pack(
            side="left", padx=4
        )

        # CV keyword editor
        row += 1
        ttk.Label(frm, text="CV 關鍵字 (一行一個, 可加可減):").grid(
            row=row, column=0, sticky="nw", padx=6, pady=4
        )
        kw_frm = ttk.Frame(frm)
        kw_frm.grid(row=row, column=1, sticky="we", padx=6, pady=4)

        kw_btn_frm = ttk.Frame(kw_frm)
        kw_btn_frm.pack(side="top", fill="x")
        ttk.Button(
            kw_btn_frm, text="從 CV 重新讀取",
            command=self._load_cv_keywords, width=18,
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            kw_btn_frm, text="儲存 (覆蓋下次匹配)",
            command=self._save_cv_keywords, width=22,
        ).pack(side="left", padx=4)
        ttk.Label(
            kw_btn_frm, text="年資:", foreground="#888",
        ).pack(side="left", padx=(8, 2))
        self.cv_years_var = tk.StringVar(value="")
        ttk.Entry(
            kw_btn_frm, textvariable=self.cv_years_var, width=4,
        ).pack(side="left")
        self.cv_stats_lbl = ttk.Label(
            kw_btn_frm, text="", foreground="#888",
        )
        self.cv_stats_lbl.pack(side="left", padx=8)

        kw_text_frm = ttk.Frame(kw_frm)
        kw_text_frm.pack(side="top", fill="both", expand=True, pady=(4, 0))
        self.cv_kw_text = tk.Text(
            kw_text_frm, height=6, wrap="word", font=("Consolas", 9),
        )
        kw_scroll = ttk.Scrollbar(
            kw_text_frm, orient="vertical", command=self.cv_kw_text.yview,
        )
        self.cv_kw_text.configure(yscrollcommand=kw_scroll.set)
        self.cv_kw_text.pack(side="left", fill="both", expand=True)
        kw_scroll.pack(side="right", fill="y")

        row += 1
        thr_frm = ttk.Frame(frm)
        thr_frm.grid(row=row, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(thr_frm, text="Telegram match 門檻 (0-100, 0=全部):").pack(side="left")
        self.match_threshold_var = tk.StringVar(value="0")
        ttk.Entry(thr_frm, textvariable=self.match_threshold_var, width=6).pack(
            side="left", padx=4
        )
        ttk.Label(
            thr_frm,
            text="(只 push 分數高於門檻嘅 job；Master/CSV 仍記錄全部)",
            foreground="#888",
        ).pack(side="left")

        # ----- Telegram -----
        row += 1
        ttk.Separator(frm, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="we", pady=(8, 4)
        )

        row += 1
        ttk.Label(frm, text="Telegram Bot Token:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.tg_token_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.tg_token_var, show="•").grid(
            row=row, column=1, sticky="we", padx=6, pady=4
        )

        row += 1
        ttk.Label(frm, text="Telegram Chat ID:").grid(
            row=row, column=0, sticky="w", padx=6, pady=4
        )
        self.tg_chat_var = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.tg_chat_var, width=24).grid(
            row=row, column=1, sticky="w", padx=6, pady=4
        )

        row += 1
        tg_opt_frm = ttk.Frame(frm)
        tg_opt_frm.grid(row=row, column=1, sticky="w", padx=6, pady=2)
        self.tg_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tg_opt_frm, text="開啟 Telegram 即時通知（只發新 job）",
            variable=self.tg_enabled_var,
        ).pack(side="left", padx=(0, 16))
        ttk.Label(tg_opt_frm, text="最多發送條數 (0=無限):").pack(side="left")
        self.tg_max_var = tk.StringVar(value="0")
        ttk.Entry(tg_opt_frm, textvariable=self.tg_max_var, width=6).pack(
            side="left", padx=4
        )

        # ----- Buttons -----
        row += 1
        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=row, column=0, columnspan=2, sticky="we", padx=6, pady=10)
        self.start_btn = ttk.Button(btn_frm, text="開始 Start", command=self._start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(
            btn_frm, text="停止 Stop", command=self._stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=4)
        self.open_btn = ttk.Button(
            btn_frm, text="打開輸出資料夾", command=self._open_outdir
        )
        self.open_btn.pack(side="left", padx=4)
        self.open_csv_btn = ttk.Button(
            btn_frm, text="打開 CSV", command=self._open_last_csv, state="disabled"
        )
        self.open_csv_btn.pack(side="left", padx=4)
        self.open_master_btn = ttk.Button(
            btn_frm, text="打開 Master Excel", command=self._open_master,
        )
        self.open_master_btn.pack(side="left", padx=4)
        self.test_tg_btn = ttk.Button(
            btn_frm, text="Test Telegram", command=self._test_telegram,
        )
        self.test_tg_btn.pack(side="left", padx=4)

        # ----- Log -----
        row += 1
        ttk.Label(frm, text="進度 Log:").grid(
            row=row, column=0, sticky="nw", padx=6, pady=4
        )
        log_frm = ttk.Frame(frm)
        log_frm.grid(row=row, column=1, sticky="nsew", padx=6, pady=4)
        self.log_text = tk.Text(
            log_frm,
            wrap="word",
            bg="#1e1e1e",
            fg="#e0e0e0",
            insertbackground="#e0e0e0",
            font=("Consolas", 10),
        )
        scroll = ttk.Scrollbar(
            log_frm, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(row, weight=1)

    # ----- config persistence -----

    def _load_config(self):
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  could not read config.json: {e}")
            return
        for key, var in [
            ("source", self.source_var),
            ("keyword", self.keyword_var),
            ("location", self.location_var),
            ("max_pages", self.maxpages_var),
            ("delay", self.delay_var),
            ("outdir", self.outdir_var),
            ("master", self.master_var),
            ("tg_token", self.tg_token_var),
            ("tg_chat", self.tg_chat_var),
            ("tg_max", self.tg_max_var),
            ("cv", self.cv_var),
            ("match_threshold", self.match_threshold_var),
        ]:
            if key in data:
                var.set(str(data[key]))
        for key, var in [
            ("full_jd", self.fulljd_var),
            ("master_enabled", self.master_enabled_var),
            ("tg_enabled", self.tg_enabled_var),
        ]:
            if key in data:
                var.set(bool(data[key]))
        self._refresh_location_values()

    def _save_config(self):
        data = {
            "source": self.source_var.get(),
            "keyword": self.keyword_var.get(),
            "location": self.location_var.get(),
            "max_pages": self.maxpages_var.get(),
            "full_jd": self.fulljd_var.get(),
            "delay": self.delay_var.get(),
            "outdir": self.outdir_var.get(),
            "master": self.master_var.get(),
            "master_enabled": self.master_enabled_var.get(),
            "tg_token": self.tg_token_var.get(),
            "tg_chat": self.tg_chat_var.get(),
            "tg_enabled": self.tg_enabled_var.get(),
            "tg_max": self.tg_max_var.get(),
            "cv": self.cv_var.get(),
            "match_threshold": self.match_threshold_var.get(),
        }
        try:
            CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"  could not save config.json: {e}")

    # ----- combobox helpers -----

    def _refresh_location_values(self):
        src = self.source_var.get()
        if src == "ctgoodjobs":
            self.location_combo.configure(values=scraper.CT_LOCATIONS)
        elif src == "cpjobs":
            self.location_combo.configure(values=scraper.CP_LOCATIONS)
            if self.location_var.get() and self.location_var.get() not in scraper.CP_LOCATIONS:
                self.location_var.set("")
        else:
            self.location_combo.configure(values=[])

    def _on_source_change(self):
        self._refresh_location_values()

    # ----- file pickers -----

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.outdir_var.get())
        if d:
            self.outdir_var.set(d)

    def _choose_cv(self):
        path = filedialog.askopenfilename(
            title="揀 CV 檔案",
            filetypes=[
                ("PDF / Text", "*.pdf *.txt"),
                ("PDF", "*.pdf"),
                ("Text", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.cv_var.set(path)
            self._load_cv_keywords()

    def _load_cv_keywords(self):
        """Read the CV (or saved profile.json) and show keywords in the editor."""
        path = self.cv_var.get().strip()
        if not path:
            messagebox.showinfo("提示", "未揀 CV 檔。先撳「瀏覽…」。")
            return
        try:
            import cv_match
        except ImportError:
            messagebox.showwarning("錯誤", "cv_match 未裝。")
            return
        # Always re-extract from CV (ignore saved profile) when this button hit
        profile = cv_match.load_cv(path, use_saved_profile=False)
        if profile is None:
            messagebox.showwarning("錯誤", f"讀唔到 CV: {path}")
            return
        # If a saved profile exists, merge — keep user's extras
        saved = cv_match.load_profile_json(cv_match.profile_json_path(path))
        if saved:
            extras = saved.keywords - profile.keywords
            profile.keywords |= extras
        self._populate_cv_editor(profile)

    def _populate_cv_editor(self, profile):
        self.cv_kw_text.delete("1.0", "end")
        self.cv_kw_text.insert("1.0", "\n".join(sorted(profile.keywords)))
        self.cv_years_var.set(str(profile.years or ""))
        self.cv_stats_lbl.config(
            text=f"{len(profile.keywords)} keywords, "
                 f"{profile.raw_chars or '?'} chars"
        )

    def _save_cv_keywords(self):
        """Write the current keywords textbox to <cv>.profile.json."""
        path = self.cv_var.get().strip()
        if not path:
            messagebox.showinfo("提示", "未揀 CV 檔。")
            return
        try:
            import cv_match
        except ImportError:
            messagebox.showwarning("錯誤", "cv_match 未裝。")
            return
        text = self.cv_kw_text.get("1.0", "end").strip()
        # Split on newline or comma; lowercase + dedupe
        raw = re.split(r"[,\n]+", text)
        kws = sorted({k.strip().lower() for k in raw if k.strip()})
        try:
            years = int((self.cv_years_var.get() or "").strip()) if self.cv_years_var.get().strip() else None
        except ValueError:
            years = None
        profile = cv_match.CVProfile(
            keywords=set(kws),
            years=years,
            raw_chars=0,
            source_path=path,
        )
        try:
            written = cv_match.save_profile(profile)
        except Exception as e:
            messagebox.showwarning("儲存失敗", str(e))
            return
        self.cv_stats_lbl.config(
            text=f"✓ 儲存 {len(kws)} keywords → {written.name}"
        )

    def _choose_master(self):
        path = filedialog.asksaveasfilename(
            initialfile=Path(self.master_var.get()).name or "jobs_master.xlsx",
            initialdir=Path(self.master_var.get()).parent if self.master_var.get() else APP_DIR,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("All files", "*.*")],
            confirmoverwrite=False,
        )
        if path:
            self.master_var.set(path)

    def _open_outdir(self):
        d = Path(self.outdir_var.get())
        if d.is_dir():
            os.startfile(d)
        else:
            messagebox.showwarning("提示", f"資料夾不存在: {d}")

    def _open_last_csv(self):
        if self.last_output_path and Path(self.last_output_path).exists():
            os.startfile(self.last_output_path)
        else:
            messagebox.showinfo("提示", "未有 CSV 可開")

    def _open_master(self):
        path = Path(self.master_var.get())
        if path.exists():
            os.startfile(path)
        else:
            messagebox.showinfo("提示", f"Master Excel 仲未存在: {path.name}")

    def _test_telegram(self):
        token = self.tg_token_var.get().strip()
        chat = self.tg_chat_var.get().strip()
        if not token or not chat:
            messagebox.showwarning(
                "缺少設定", "請先填好 Bot Token 同 Chat ID"
            )
            return
        ok, err = scraper.telegram_test_ping(token, chat)
        if ok:
            messagebox.showinfo(
                "Telegram OK",
                "測試訊息已發到你嘅 Telegram，去 chat 度睇下"
            )
        else:
            messagebox.showerror("Telegram 失敗", err or "Unknown error")

    # ----- log plumbing -----

    def _log(self, msg):
        self.log_queue.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    if self.last_output_path:
                        self.open_csv_btn.config(state="normal")
                else:
                    self.log_text.insert("end", msg + "\n")
                    self.log_text.see("end")
        except queue.Empty:
            pass
        self.root.after(150, self._drain_log)

    # ----- start / stop -----

    def _start(self):
        keyword = self.keyword_var.get().strip()
        if not keyword:
            messagebox.showwarning("缺少關鍵字", "請輸入 Keyword")
            return
        try:
            max_pages = int(self.maxpages_var.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("輸入錯誤", "Max pages 要係整數")
            return
        try:
            delay = float(self.delay_var.get().strip() or "1.5")
        except ValueError:
            messagebox.showwarning("輸入錯誤", "Delay 要係數字")
            return
        try:
            tg_max = int(self.tg_max_var.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("輸入錯誤", "Telegram max 要係整數")
            return

        at_str = self.at_var.get().strip()
        at_dt = None
        if at_str:
            try:
                at_dt = scraper.parse_at(at_str)
            except (ValueError, argparse.ArgumentTypeError) as e:
                messagebox.showwarning("時間格式錯誤", str(e))
                return

        outdir = Path(self.outdir_var.get())
        if not outdir.exists():
            try:
                outdir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showwarning("資料夾錯誤", str(e))
                return

        tg_enabled = self.tg_enabled_var.get()
        tg_token = self.tg_token_var.get().strip()
        tg_chat = self.tg_chat_var.get().strip()
        if tg_enabled and (not tg_token or not tg_chat):
            messagebox.showwarning(
                "Telegram 設定缺失",
                "開咗 Telegram 但 Bot Token 或 Chat ID 係空。"
            )
            return

        master_enabled = self.master_enabled_var.get()
        master_path = self.master_var.get().strip() if master_enabled else ""

        self._save_config()

        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.open_csv_btn.config(state="disabled")
        self.log_text.delete("1.0", "end")
        self.last_output_path = None

        cv_path = self.cv_var.get().strip()
        try:
            match_threshold = float(self.match_threshold_var.get().strip() or "0")
        except ValueError:
            match_threshold = 0.0

        opts = {
            "source": self.source_var.get(),
            "keyword": keyword,
            "location": self.location_var.get().strip(),
            "max_pages": max_pages,
            "full_jd": self.fulljd_var.get(),
            "delay": delay,
            "at": at_dt,
            "outdir": outdir,
            "master": master_path,
            "tg_enabled": tg_enabled,
            "tg_token": tg_token,
            "tg_chat": tg_chat,
            "tg_max": tg_max,
            "cv": cv_path,
            "match_threshold": match_threshold,
        }
        self.worker = threading.Thread(
            target=self._run, args=(opts,), daemon=True
        )
        self.worker.start()

    def _stop(self):
        self.stop_event.set()
        self._log(">>> Stop requested. Waiting for current request to finish...")

    def _run(self, opts):
        writer = QueueWriter(self.log_queue)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                if opts["at"]:
                    target = opts["at"]
                    print(f"Scheduled run at {target:%Y-%m-%d %H:%M:%S}")
                    while not self.stop_event.is_set():
                        remaining = (target - datetime.now()).total_seconds()
                        if remaining <= 0:
                            break
                        hrs, rem = divmod(int(remaining), 3600)
                        mins, secs = divmod(rem, 60)
                        print(
                            f"  waiting... "
                            f"{hrs:02d}:{mins:02d}:{secs:02d} left"
                        )
                        self.stop_event.wait(min(remaining, 30))
                    if self.stop_event.is_set():
                        print("Stopped before scheduled start.")
                        return

                source = opts.get("source", "jobsdb")
                output_path = (
                    Path(opts["outdir"])
                    / f"{source}_{opts['keyword'].replace(' ', '_')}_"
                    f"{datetime.now():%Y%m%d_%H%M%S}.csv"
                )
                ns = argparse.Namespace(
                    source=source,
                    keyword=opts["keyword"],
                    location=opts.get("location", ""),
                    max_pages=opts["max_pages"],
                    full_jd=opts["full_jd"],
                    delay=opts["delay"],
                    output=str(output_path),
                    csv=True,
                    master=opts.get("master") or "",
                    telegram_enabled=bool(opts.get("tg_enabled")),
                    telegram_token=opts.get("tg_token", ""),
                    telegram_chat_id=opts.get("tg_chat", ""),
                    telegram_max=int(opts.get("tg_max", 0) or 0),
                    telegram_delay=1.5,
                    cv=opts.get("cv", ""),
                    match_threshold=float(opts.get("match_threshold", 0) or 0),
                    at=None,
                )
                result_path = scraper.scrape(ns, stop_event=self.stop_event)
                if result_path:
                    self.last_output_path = str(result_path)
        except Exception as e:
            self.log_queue.put(f"ERROR: {e}")
        finally:
            writer.flush()
            self.log_queue.put("__DONE__")


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
