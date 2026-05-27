"""JobsDB HK Scraper - desktop GUI launcher (Tkinter)."""

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import scraper


class GuiPipe:
    """File-like object that ships each line to a callback."""

    def __init__(self, on_line):
        self.on_line = on_line
        self.buf = ""

    def write(self, s):
        if not s:
            return
        self.buf += s
        while "\n" in self.buf or "\r" in self.buf:
            nl = self.buf.find("\n")
            cr = self.buf.find("\r")
            if nl == -1:
                idx, sep = cr, "\r"
            elif cr == -1:
                idx, sep = nl, "\n"
            else:
                idx, sep = (nl, "\n") if nl < cr else (cr, "\r")
            line = self.buf[:idx]
            self.buf = self.buf[idx + 1:]
            if line.strip():
                self.on_line(line.rstrip(), overwrite=(sep == "\r"))

    def flush(self):
        pass


class Args:
    pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("JobsDB HK 爬蟲")
        root.geometry("820x640")
        root.minsize(720, 560)

        self.stop_event = threading.Event()
        self.worker = None
        self.log_queue = queue.Queue()
        self.last_output_path = None

        self._build_form(root)
        self._build_buttons(root)
        self._build_log(root)

        self.root.after(100, self._drain_log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI building ----------
    def _build_form(self, root):
        f = ttk.LabelFrame(root, text="爬蟲設定", padding=12)
        f.pack(fill="x", padx=12, pady=(12, 6))

        for i in range(2):
            f.columnconfigure(i * 2 + 1, weight=1)

        ttk.Label(f, text="關鍵字 Keyword:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.keyword = tk.StringVar(value="Accountant")
        ttk.Entry(f, textvariable=self.keyword).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4)

        ttk.Label(f, text="最多頁數 (0 = 全部):").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        self.max_pages = tk.IntVar(value=0)
        ttk.Spinbox(f, from_=0, to=999, textvariable=self.max_pages, width=10).grid(row=1, column=1, sticky="w", padx=4)

        self.full_jd = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f,
            text="抓取完整 JD（包括 Responsibilities / Requirements 自動分段）",
            variable=self.full_jd,
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=4)

        ttk.Label(f, text="每次 request 間隔 (秒):").grid(row=2, column=0, sticky="e", padx=4, pady=4)
        self.delay = tk.DoubleVar(value=1.5)
        ttk.Spinbox(f, from_=0.5, to=10, increment=0.5, textvariable=self.delay, width=10).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(f, text="定時開始（HH:MM 或 YYYY-MM-DD HH:MM，留空 = 即刻）:").grid(row=3, column=0, sticky="e", padx=4, pady=4)
        self.at = tk.StringVar(value="")
        ttk.Entry(f, textvariable=self.at).grid(row=3, column=1, columnspan=3, sticky="ew", padx=4)

        ttk.Label(f, text="輸出 CSV 路徑（留空 = 自動命名）:").grid(row=4, column=0, sticky="e", padx=4, pady=4)
        self.output = tk.StringVar(value="")
        ttk.Entry(f, textvariable=self.output).grid(row=4, column=1, columnspan=2, sticky="ew", padx=4)
        ttk.Button(f, text="選擇...", command=self._pick_output, width=10).grid(row=4, column=3, sticky="w", padx=4)

    def _build_buttons(self, root):
        b = ttk.Frame(root, padding=(12, 0))
        b.pack(fill="x")

        self.start_btn = ttk.Button(b, text="▶ 開始", command=self._start, width=12)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(b, text="■ 停止", command=self._stop, width=12, state="disabled")
        self.stop_btn.pack(side="left", padx=8)

        self.open_btn = ttk.Button(b, text="📂 打開輸出檔案夾", command=self._open_folder, width=18)
        self.open_btn.pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="準備好")
        ttk.Label(b, textvariable=self.status_var, foreground="gray").pack(side="left", padx=12)

    def _build_log(self, root):
        lf = ttk.LabelFrame(root, text="日誌 Log", padding=8)
        lf.pack(fill="both", expand=True, padx=12, pady=12)

        wrap = ttk.Frame(lf)
        wrap.pack(fill="both", expand=True)

        self.log = tk.Text(wrap, height=18, wrap="word", state="disabled", font=("Consolas", 10))
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)

    # ---------- helpers ----------
    def _pick_output(self):
        path = filedialog.asksaveasfilename(
            title="儲存 CSV 到",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self.output.set(path)

    def _open_folder(self):
        target = self.last_output_path
        if target and Path(target).exists():
            folder = str(Path(target).parent)
        else:
            folder = str(Path.cwd())
        try:
            os.startfile(folder)  # Windows
        except AttributeError:
            webbrowser.open(folder)

    def _enqueue(self, msg, overwrite=False):
        self.log_queue.put((msg, overwrite))

    def _drain_log(self):
        try:
            while True:
                msg, overwrite = self.log_queue.get_nowait()
                self.log.config(state="normal")
                if overwrite:
                    last_line_start = self.log.index("end-2c linestart")
                    self.log.delete(last_line_start, "end-1c")
                    self.log.insert("end", msg)
                else:
                    if self.log.index("end-1c") != "1.0":
                        self.log.insert("end", "\n")
                    self.log.insert("end", msg)
                self.log.see("end")
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # ---------- run / stop ----------
    def _start(self):
        if self.worker and self.worker.is_alive():
            return

        args = Args()
        args.keyword = self.keyword.get().strip() or "Accountant"
        try:
            args.max_pages = max(0, int(self.max_pages.get()))
        except (tk.TclError, ValueError):
            args.max_pages = 0
        args.full_jd = bool(self.full_jd.get())
        try:
            args.delay = max(0.0, float(self.delay.get()))
        except (tk.TclError, ValueError):
            args.delay = 1.5
        args.output = self.output.get().strip() or None

        at_text = self.at.get().strip()
        if at_text:
            try:
                args.at = scraper.parse_at(at_text)
            except Exception as e:
                messagebox.showerror("時間格式錯誤", str(e))
                return
        else:
            args.at = None

        self._clear_log()
        self._enqueue(f"關鍵字: {args.keyword}")
        self._enqueue(f"最多頁數: {'全部' if args.max_pages == 0 else args.max_pages}")
        self._enqueue(f"完整 JD: {'是' if args.full_jd else '否'}")
        self._enqueue(f"Delay: {args.delay} 秒")
        if args.at:
            self._enqueue(f"預定 {args.at:%Y-%m-%d %H:%M:%S} 開始")
        self._enqueue("-" * 60)

        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("執行中…")

        self.worker = threading.Thread(target=self._run, args=(args,), daemon=True)
        self.worker.start()

    def _stop(self):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self._enqueue(">>> 停止訊號已發送，等緊收尾…")
            self.status_var.set("停止中…")

    def _run(self, args):
        old_stdout = sys.stdout
        sys.stdout = GuiPipe(self._enqueue)
        try:
            if args.at:
                scraper.wait_until(args.at, stop_event=self.stop_event)
                if self.stop_event.is_set():
                    self._enqueue("已取消（未開始爬）")
                    return
            output_path = scraper.scrape(args, stop_event=self.stop_event)
            if output_path:
                self.last_output_path = str(output_path)
        except Exception as e:
            self._enqueue(f"✗ 錯誤: {e}")
        finally:
            sys.stdout = old_stdout
            self.root.after(0, self._done)

    def _done(self):
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("完成 — 可以再跑")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel("仲喺度跑緊", "確定要關閉?\n（已爬到嘅 job 已經寫入 CSV）"):
                return
            self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        from tkinter import font as tkfont
        default = tkfont.nametofont("TkDefaultFont")
        default.configure(size=10)
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
