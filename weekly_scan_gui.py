#!/usr/bin/env python3
"""
A股科技+新能源 周度扫描 - Windows 桌面版 v4
引用 scanner.py 核心逻辑，支持超时 + 取消
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import queue
from datetime import datetime

import scanner


class ScanApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("A股科技+新能源 周度扫描 v4")
        self.root.geometry("900x720")
        self.root.minsize(700, 500)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"900x720+{(sw-900)//2}+{(sh-720)//2}")

        self.scan_queue = queue.Queue()
        self.scanning = False
        self.cancel_flag = False
        self.last_result = None

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        self.index_frame = ttk.LabelFrame(top_frame, text="大盘指数", padding=10)
        self.index_frame.pack(fill=tk.X, pady=(0, 8))

        self.index_vars = {}
        for name, _ in scanner.INDICES:
            var = tk.StringVar(value=f"{name}: 等待扫描...")
            self.index_vars[name] = var
            ttk.Label(self.index_frame, textvariable=var, font=("Consolas", 10)).pack(side=tk.LEFT, padx=15)

        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(fill=tk.X)

        self.scan_btn = ttk.Button(btn_frame, text="🔍 开始扫描", command=self._start_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.cancel_btn = ttk.Button(btn_frame, text="✖ 取消", command=self._cancel_scan, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=4)

        self.save_btn = ttk.Button(btn_frame, text="📄 另存为", command=self._save_report, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=4)

        self.progress_var = tk.StringVar(value="就绪")
        ttk.Label(btn_frame, textvariable=self.progress_var, font=("Consolas", 9)).pack(side=tk.LEFT, padx=20)

        self.progress_bar = ttk.Progressbar(btn_frame, mode='indeterminate', length=100)
        self.progress_bar.pack(side=tk.RIGHT, padx=10)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        report_frame = ttk.Frame(self.root, padding=10)
        report_frame.pack(fill=tk.BOTH, expand=True)

        self.report_text = scrolledtext.ScrolledText(
            report_frame, wrap=tk.NONE, font=("Consolas", 10),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        self.report_text.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="就绪 — 点击「开始扫描」")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(10, 2))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _start_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.cancel_flag = False
        self.scan_btn.config(state=tk.DISABLED, text="⏳ 扫描中...")
        self.cancel_btn.config(state=tk.NORMAL)
        self.save_btn.config(state=tk.DISABLED)
        self.progress_bar.start(10)
        self.progress_var.set("初始化...")
        self.report_text.delete(1.0, tk.END)
        self.status_var.set("正在扫描，请稍候...")
        for name in self.index_vars:
            self.index_vars[name].set(f"{name}: 加载中...")
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _cancel_scan(self):
        self.cancel_flag = True
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress_var.set("取消中...")
        self.status_var.set("正在取消扫描...")

    def _scan_thread(self):
        try:
            result = scanner.run_scan(
                progress_callback=lambda msg: self.scan_queue.put(("progress", msg)),
                cancel_check=lambda: self.cancel_flag,
            )
            self.scan_queue.put(("done", result))
        except scanner.ScanCancelled:
            self.scan_queue.put(("cancelled", None))
        except Exception as e:
            self.scan_queue.put(("error", str(e)))

    def _poll_queue(self):
        try:
            while True:
                msg_type, msg = self.scan_queue.get_nowait()

                if msg_type == "progress":
                    self.progress_var.set(msg)
                    self.status_var.set(msg)

                elif msg_type == "done":
                    self._finish()
                    self.save_btn.config(state=tk.NORMAL)
                    self.progress_var.set("完成")
                    self.last_result = msg
                    for name, info in msg["index_data"].items():
                        close = info["close"]
                        chg = info["chg_pct"]
                        if close:
                            self.index_vars[name].set(f"{name}: {close:.2f} ({chg:+.2f}%)")
                        else:
                            self.index_vars[name].set(f"{name}: 获取失败")
                    self.report_text.insert(tk.END, msg["report"])
                    conc = msg.get("concentration", 0)
                    conc_str = f" | 集中度 {msg['top_industry']} {conc:.0f}%" if conc >= 30 else ""
                    self.status_var.set(
                        f"扫描完成 {msg['scan_time']}  |  "
                        f"{msg['industry_count']}行业 {msg['total_stocks']}只  |  "
                        f"{msg['candidate_count']}只候选{conc_str}  |  {msg['report_path']}"
                    )

                elif msg_type == "cancelled":
                    self._finish()
                    self.progress_var.set("已取消")
                    self.status_var.set("扫描已取消")
                    self.report_text.insert(tk.END, "\n⏹ 扫描已被用户取消。\n")
                    for name in self.index_vars:
                        self.index_vars[name].set(f"{name}: -")

                elif msg_type == "error":
                    self._finish()
                    self.progress_var.set("扫描失败")
                    self.status_var.set(f"错误: {msg}")
                    self.report_text.insert(tk.END, f"\n❌ 扫描失败:\n{msg}\n")
                    messagebox.showerror("扫描失败", f"错误信息:\n{msg}")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _finish(self):
        self.scanning = False
        self.scan_btn.config(state=tk.NORMAL, text="🔍 开始扫描")
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress_bar.stop()

    def _save_report(self):
        if not self.last_result:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All", "*.*")],
            initialfile=f"week_{datetime.now().isocalendar()[1]}.md"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.last_result["report"])
            self.status_var.set(f"报告已保存: {path}")
            messagebox.showinfo("保存成功", f"报告已保存到:\n{path}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ScanApp().run()
