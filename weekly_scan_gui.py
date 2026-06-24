#!/usr/bin/env python3
"""
A股科技+新能源 周度扫描 - Windows 桌面版 v5
功能: 扫描 / 深度研究(LLM前瞻) / 回测 / API设置
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import queue
from datetime import datetime

import scanner
import backtest
import research
import llm_client


class ScanApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("A股科技+新能源 投研助手 v5")
        self.root.geometry("960x760")
        self.root.minsize(760, 540)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"960x760+{(sw-960)//2}+{(sh-760)//2}")

        self.q = queue.Queue()
        self.busy = False
        self.cancel_flag = False
        self.last_scan = None        # 上次扫描结果(含candidates)
        self.last_output = None       # 当前显示文本(用于另存)

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        # 指数
        self.index_frame = ttk.LabelFrame(top, text="大盘指数", padding=8)
        self.index_frame.pack(fill=tk.X, pady=(0, 8))
        self.index_vars = {}
        for name, _ in scanner.INDICES:
            var = tk.StringVar(value=f"{name}: 等待扫描...")
            self.index_vars[name] = var
            ttk.Label(self.index_frame, textvariable=var, font=("Consolas", 10)).pack(side=tk.LEFT, padx=15)

        # 按钮行
        btns = ttk.Frame(top)
        btns.pack(fill=tk.X)

        self.scan_btn = ttk.Button(btns, text="🔍 扫描候选", command=self._start_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.research_btn = ttk.Button(btns, text="🤖 深度研究", command=self._start_research, state=tk.DISABLED)
        self.research_btn.pack(side=tk.LEFT, padx=6)

        self.backtest_btn = ttk.Button(btns, text="📊 回测", command=self._open_backtest_dialog)
        self.backtest_btn.pack(side=tk.LEFT, padx=6)

        self.cancel_btn = ttk.Button(btns, text="✖ 取消", command=self._cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=6)

        self.save_btn = ttk.Button(btns, text="📄 另存", command=self._save, state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=6)

        self.settings_btn = ttk.Button(btns, text="⚙ API设置", command=self._open_settings)
        self.settings_btn.pack(side=tk.LEFT, padx=6)

        self.progress_var = tk.StringVar(value="就绪")
        ttk.Label(btns, textvariable=self.progress_var, font=("Consolas", 9)).pack(side=tk.LEFT, padx=15)
        self.progress_bar = ttk.Progressbar(btns, mode='indeterminate', length=90)
        self.progress_bar.pack(side=tk.RIGHT, padx=8)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10)

        body = ttk.Frame(self.root, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        self.text = scrolledtext.ScrolledText(
            body, wrap=tk.NONE, font=("Consolas", 10),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white"
        )
        self.text.pack(fill=tk.BOTH, expand=True)

        self.status_var = tk.StringVar(value="就绪 — 先「扫描候选」，再「深度研究」")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W, padding=(10, 2)).pack(fill=tk.X, side=tk.BOTTOM)

    # ── 通用忙碌状态 ──
    def _set_busy(self, on, label="处理中..."):
        self.busy = on
        if on:
            self.cancel_flag = False
            self.scan_btn.config(state=tk.DISABLED)
            self.research_btn.config(state=tk.DISABLED)
            self.backtest_btn.config(state=tk.DISABLED)
            self.save_btn.config(state=tk.DISABLED)
            self.cancel_btn.config(state=tk.NORMAL)
            self.progress_bar.start(10)
            self.progress_var.set(label)
        else:
            self.scan_btn.config(state=tk.NORMAL)
            self.backtest_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)
            self.progress_bar.stop()
            if self.last_scan:
                self.research_btn.config(state=tk.NORMAL)
            if self.last_output:
                self.save_btn.config(state=tk.NORMAL)

    def _cancel(self):
        self.cancel_flag = True
        self.cancel_btn.config(state=tk.DISABLED)
        self.progress_var.set("取消中...")

    # ── 扫描 ──
    def _start_scan(self):
        if self.busy:
            return
        self._set_busy(True, "扫描中...")
        self.text.delete(1.0, tk.END)
        self.status_var.set("正在扫描候选...")
        for name in self.index_vars:
            self.index_vars[name].set(f"{name}: 加载中...")
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        try:
            result = scanner.run_scan(
                progress_callback=lambda m: self.q.put(("progress", m)),
                cancel_check=lambda: self.cancel_flag,
            )
            self.q.put(("scan_done", result))
        except scanner.ScanCancelled:
            self.q.put(("cancelled", None))
        except Exception as e:
            self.q.put(("error", str(e)))

    # ── 深度研究 ──
    def _start_research(self):
        if self.busy or not self.last_scan:
            return
        if not llm_client.is_configured():
            messagebox.showwarning("未配置 API", "深度研究需要 LLM API key。\n请先点「⚙ API设置」配置。")
            self._open_settings()
            return
        cands = self.last_scan.get("candidates_full") or []
        if not cands:
            messagebox.showinfo("无候选", "请先扫描出候选标的。")
            return
        n = min(10, len(cands))
        if not messagebox.askyesno("确认深度研究",
            f"将对候选池前 {n} 只个股调用 LLM 做 6-12 月前瞻分析。\n"
            f"会产生 API 调用费用，预计 1-3 分钟。\n\n是否继续？"):
            return
        self._set_busy(True, "深度研究中...")
        self.text.delete(1.0, tk.END)
        self.status_var.set("正在做 LLM 前瞻分析...")
        threading.Thread(target=self._research_thread, args=(cands, n), daemon=True).start()

    def _research_thread(self, cands, n):
        try:
            results = research.research_candidates(
                cands, top_n=n,
                progress_callback=lambda m: self.q.put(("progress", m)),
            )
            report = research.build_research_report(results)
            self.q.put(("research_done", report))
        except Exception as e:
            self.q.put(("error", str(e)))

    # ── 回测对话框 ──
    def _open_backtest_dialog(self):
        if self.busy:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("回测设置")
        dlg.geometry("380x300")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="回测模式:").pack(pady=(15, 2))
        mode_var = tk.StringVar(value="多期滚动(推荐)")
        ttk.Combobox(dlg, textvariable=mode_var,
                     values=["多期滚动(推荐)", "单期"], width=22, state="readonly").pack()

        ttk.Label(dlg, text="报告期(单期填1个/多期逗号分隔):").pack(pady=(10, 2))
        rd_var = tk.StringVar(value="20240630,20240930,20241231,20250331")
        ttk.Entry(dlg, textvariable=rd_var, width=42).pack()

        ttk.Label(dlg, text="持有月数:").pack(pady=(10, 2))
        hold_var = tk.StringVar(value="6")
        ttk.Combobox(dlg, textvariable=hold_var, values=["3", "6", "9", "12"], width=18).pack()

        ttk.Label(dlg, text="选股数(TopROE):").pack(pady=(10, 2))
        top_var = tk.StringVar(value="15")
        ttk.Entry(dlg, textvariable=top_var, width=20).pack()

        def go():
            rd = rd_var.get().strip()
            try:
                months = int(hold_var.get())
                topn = int(top_var.get())
            except ValueError:
                messagebox.showerror("输入错误", "月数和选股数必须是整数")
                return
            multi = mode_var.get().startswith("多期")
            dlg.destroy()
            if multi:
                dates = [d.strip() for d in rd.split(",") if d.strip()]
                self._start_rolling(dates, months, topn)
            else:
                self._start_backtest(rd.split(",")[0].strip(), months, topn)

        ttk.Button(dlg, text="开始回测", command=go).pack(pady=14)

    def _start_rolling(self, dates, months, topn):
        self._set_busy(True, "多期回测中...")
        self.text.delete(1.0, tk.END)
        self.status_var.set(f"多期回测 {len(dates)}期 持有{months}月...")
        threading.Thread(target=self._rolling_thread, args=(dates, months, topn), daemon=True).start()

    def _rolling_thread(self, dates, months, topn):
        try:
            result = backtest.run_rolling_backtest(
                dates, hold_months=months, top_n=topn,
                progress_callback=lambda m: self.q.put(("progress", m)),
            )
            report = backtest.build_rolling_report(result)
            self.q.put(("backtest_done", report))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _start_backtest(self, rd, months, topn):
        self._set_busy(True, "回测中...")
        self.text.delete(1.0, tk.END)
        self.status_var.set(f"回测 {rd} 持有{months}月...")
        threading.Thread(target=self._backtest_thread, args=(rd, months, topn), daemon=True).start()

    def _backtest_thread(self, rd, months, topn):
        try:
            result = backtest.run_backtest(
                rd, hold_months=months, top_n=topn,
                progress_callback=lambda m: self.q.put(("progress", m)),
            )
            report = backtest.build_backtest_report(result)
            self.q.put(("backtest_done", report))
        except Exception as e:
            self.q.put(("error", str(e)))

    # ── 设置对话框 ──
    def _open_settings(self):
        cfg = llm_client.load_config()
        dlg = tk.Toplevel(self.root)
        dlg.title("LLM API 设置")
        dlg.geometry("480x340")
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text="快速预设:").pack(pady=(15, 2))
        preset_var = tk.StringVar(value="deepseek")
        preset_cb = ttk.Combobox(dlg, textvariable=preset_var,
                                  values=list(llm_client.PRESETS.keys()), width=40)
        preset_cb.pack()

        ttk.Label(dlg, text="API Key:").pack(pady=(10, 2))
        key_var = tk.StringVar(value=cfg.get("api_key", ""))
        ttk.Entry(dlg, textvariable=key_var, width=52, show="*").pack()

        ttk.Label(dlg, text="Base URL:").pack(pady=(10, 2))
        url_var = tk.StringVar(value=cfg.get("base_url", ""))
        ttk.Entry(dlg, textvariable=url_var, width=52).pack()

        ttk.Label(dlg, text="Model:").pack(pady=(10, 2))
        model_var = tk.StringVar(value=cfg.get("model", ""))
        ttk.Entry(dlg, textvariable=model_var, width=52).pack()

        def on_preset(_):
            p = preset_var.get()
            if p in llm_client.PRESETS:
                url_var.set(llm_client.PRESETS[p]["base_url"])
                model_var.set(llm_client.PRESETS[p]["model"])
        preset_cb.bind("<<ComboboxSelected>>", on_preset)

        def test_and_save():
            llm_client.save_config(
                api_key=key_var.get().strip(),
                base_url=url_var.get().strip(),
                model=model_var.get().strip(),
            )
            self.status_var.set("正在测试 API 连接...")
            try:
                reply = llm_client.chat(
                    [{"role": "user", "content": "回复'OK'两个字符确认连接"}],
                    max_tokens=10, timeout=30
                )
                messagebox.showinfo("测试成功", f"API 连接正常。\n模型回复: {reply[:50]}")
                dlg.destroy()
                if self.last_scan:
                    self.research_btn.config(state=tk.NORMAL)
            except Exception as e:
                messagebox.showerror("测试失败", f"API 调用失败:\n{e}")

        btnf = ttk.Frame(dlg)
        btnf.pack(pady=16)
        ttk.Button(btnf, text="测试并保存", command=test_and_save).pack(side=tk.LEFT, padx=6)
        ttk.Button(btnf, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=6)

    # ── 队列轮询 ──
    def _poll_queue(self):
        try:
            while True:
                kind, msg = self.q.get_nowait()
                if kind == "progress":
                    self.progress_var.set(msg[:30])
                    self.status_var.set(msg)
                elif kind == "scan_done":
                    self._set_busy(False)
                    self.progress_var.set("完成")
                    self.last_scan = msg
                    self.last_output = msg["report"]
                    self.save_btn.config(state=tk.NORMAL)
                    self.research_btn.config(state=tk.NORMAL)
                    for name, info in msg["index_data"].items():
                        c = info["close"]; ch = info["chg_pct"]
                        self.index_vars[name].set(f"{name}: {c:.2f} ({ch:+.2f}%)" if c else f"{name}: 失败")
                    self.text.insert(tk.END, msg["report"])
                    conc = msg.get("concentration", 0)
                    cs = f" | 集中度 {msg['top_industry']} {conc:.0f}%" if conc >= 30 else ""
                    self.status_var.set(
                        f"扫描完成 {msg['scan_time']} | {msg['candidate_count']}只候选{cs} | "
                        f"点「深度研究」做前瞻分析")
                elif kind == "research_done":
                    self._set_busy(False)
                    self.progress_var.set("研究完成")
                    self.last_output = msg
                    self.save_btn.config(state=tk.NORMAL)
                    self.text.insert(tk.END, msg)
                    self.status_var.set("深度研究完成 — 可「另存」为报告")
                elif kind == "backtest_done":
                    self._set_busy(False)
                    self.progress_var.set("回测完成")
                    self.last_output = msg
                    self.save_btn.config(state=tk.NORMAL)
                    self.text.insert(tk.END, msg)
                    self.status_var.set("回测完成")
                elif kind == "cancelled":
                    self._set_busy(False)
                    self.progress_var.set("已取消")
                    self.text.insert(tk.END, "\n⏹ 已取消。\n")
                    self.status_var.set("操作已取消")
                elif kind == "error":
                    self._set_busy(False)
                    self.progress_var.set("失败")
                    self.text.insert(tk.END, f"\n❌ 失败:\n{msg}\n")
                    self.status_var.set(f"错误: {msg}")
                    messagebox.showerror("失败", str(msg))
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _save(self):
        if not self.last_output:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All", "*.*")],
            initialfile=f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        )
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.last_output)
            messagebox.showinfo("保存成功", f"已保存到:\n{path}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ScanApp().run()
