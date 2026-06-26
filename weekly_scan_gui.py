#!/usr/bin/env python3
"""
A股投研助手 — 专业金融终端版
深色主题 / 黄金布局 / 信息分层 / 一眼看重点
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading, queue
from datetime import datetime
import scanner, backtest, research, llm_client


# ── 主题配色 ──
BG  = "#0f1117"       # 最深背景
CARD = "#1a1d27"       # 卡片
CARD2 = "#212433"      # 次级卡片
ACCENT = "#3b82f6"     # 蓝色强调
GREEN = "#22c55e"      # 涨
RED = "#ef4444"        # 跌
PURPLE = "#7c3aed"     # 深度分析 (更亮的紫色，白色字体清晰可读)
TEAL = "#14b8a6"       # 产业研报
TEXT = "#e2e8f0"       # 主文字
TEXT2 = "#94a3b8"      # 次级文字
BORDER = "#2d3143"     # 边框


class Terminal:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("A股投研助手")
        self.root.configure(bg=BG)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(1100, sw-40), min(760, sh-60)
        self.root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        self.root.minsize(900, 600)

        self.q = queue.Queue()
        self.busy, self.cancel_flag = False, False
        self.last_scan = None
        self.growth_var = tk.BooleanVar(value=False)

        self._build()
        self._poll()

    # ═══════════ 布局 ═══════════
    def _build(self):
        # ── 顶部标题栏 ──
        top = tk.Frame(self.root, bg="#161923", height=48)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="A股投研助手", font=("微软雅黑", 15, "bold"),
                 fg=TEXT, bg="#161923").pack(side=tk.LEFT, padx=20, pady=10)
        self.top_status = tk.Label(top, text="就绪", font=("微软雅黑", 9),
                                    fg=TEXT2, bg="#161923")
        self.top_status.pack(side=tk.RIGHT, padx=20, pady=10)

        # ── 主区域: 左右分栏 ──
        main = tk.Frame(self.root, bg=BG)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=(6, 4))

        # 左栏: 指数 + 按钮 + 摘要
        left = tk.Frame(main, bg=CARD, width=280, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        # 指数卡片
        idx_header = tk.Frame(left, bg=CARD, height=36)
        idx_header.pack(fill=tk.X, padx=14, pady=(14, 4))
        idx_header.pack_propagate(False)
        tk.Label(idx_header, text="大盘指数", font=("微软雅黑", 11, "bold"),
                 fg=TEXT, bg=CARD).pack(side=tk.LEFT)
        tk.Label(idx_header, text="实时", font=("微软雅黑", 8),
                 fg=GREEN, bg=CARD).pack(side=tk.RIGHT)

        self.idx_labels = {}
        for name, _ in scanner.INDICES:
            card = tk.Frame(left, bg=CARD2, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill=tk.X, padx=12, pady=3)
            tk.Label(card, text=name, font=("微软雅黑", 9), fg=TEXT2, bg=CARD2,
                     anchor="w").pack(fill=tk.X, padx=10, pady=(8, 0))
            val = tk.Label(card, text="--", font=("Consolas", 20, "bold"),
                           fg=TEXT, bg=CARD2, anchor="w")
            val.pack(fill=tk.X, padx=10, pady=(0, 2))
            sub = tk.Label(card, text="等待扫描", font=("微软雅黑", 8),
                           fg=TEXT2, bg=CARD2, anchor="w")
            sub.pack(fill=tk.X, padx=10, pady=(0, 8))
            self.idx_labels[name] = (val, sub)

        # 按钮组
        btns = tk.Frame(left, bg=CARD)
        btns.pack(fill=tk.X, padx=12, pady=(10, 4))
        self._btn(btns, "开始扫描", ACCENT, self._scan).pack(fill=tk.X, pady=2)
        self.research_btn = self._btn(btns, "深度分析", PURPLE, self._research, disabled=True)
        self.research_btn.pack(fill=tk.X, pady=2)
        self.ind_report_btn = self._btn(btns, "产业研报", TEAL, self._ind_report, disabled=True)
        self.ind_report_btn.pack(fill=tk.X, pady=2)
        self._btn(btns, "港股监控", "#6366f1", self._show_hk).pack(fill=tk.X, pady=2)

        # 成长股开关
        opts = tk.Frame(left, bg=CARD)
        opts.pack(fill=tk.X, padx=14, pady=(6, 4))
        tk.Checkbutton(opts, text="成长股模式 (放宽PE/ROE)", variable=self.growth_var,
                       font=("微软雅黑", 9), fg=TEXT2, bg=CARD, selectcolor=CARD,
                       activebackground=CARD, activeforeground=TEXT,
                       cursor="hand2").pack(side=tk.LEFT)
        tk.Label(opts, text="?", font=("微软雅黑", 9, "bold"), fg=TEXT2, bg=CARD,
                 cursor="hand2").pack(side=tk.RIGHT)

        # 摘要条
        sep = tk.Frame(left, bg=BORDER, height=1); sep.pack(fill=tk.X, padx=12, pady=4)
        self.summary = tk.Text(left, font=("微软雅黑", 9), bg=CARD, fg=TEXT2,
                               height=6, relief="flat", bd=0, padx=12, pady=6,
                               wrap=tk.WORD, state=tk.DISABLED)
        self.summary.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 8))

        # 底部进度
        self.prog = ttk.Progressbar(left, mode='indeterminate', length=100)
        self.prog.pack(fill=tk.X, padx=12, pady=(0, 8))

        # 右栏: 数据区 (表格/文本)
        right = tk.Frame(main, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.right = right
        self._show_welcome()

        # ── 底部栏 ──
        bar = tk.Frame(self.root, bg="#161923", height=28)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        for txt, cmd in [("历史回测", self._backtest), ("保存报告", self._save), ("设置", self._settings)]:
            tk.Button(bar, text=txt, font=("微软雅黑", 8), fg=TEXT2, bg="#161923",
                      bd=0, activebackground="#212433", activeforeground=TEXT,
                      cursor="hand2", command=cmd).pack(side=tk.RIGHT, padx=8, pady=2)

    def _btn(self, parent, text, color, cmd, disabled=False):
        b = tk.Button(parent, text=text, font=("微软雅黑", 10, "bold"),
                      bg=color, fg="white", activebackground=color, activeforeground="white",
                      relief="flat", bd=0, padx=14, pady=8, cursor="hand2",
                      command=cmd, state=tk.DISABLED if disabled else tk.NORMAL)
        return b

    def _show_welcome(self):
        for w in self.right.winfo_children(): w.destroy()
        f = tk.Frame(self.right, bg=CARD)
        f.pack(expand=True)
        tk.Label(f, text="A股投研助手", font=("微软雅黑", 24, "bold"),
                 fg=TEXT, bg=CARD).pack(pady=(0, 6))
        tk.Label(f, text="科技+新能源+新兴方向 · 每周扫描 · AI前瞻 · 港股监控",
                 font=("微软雅黑", 10), fg=TEXT2, bg=CARD).pack()
        tk.Label(f, text="\n点击左侧「开始扫描」按钮开始",
                 font=("微软雅黑", 11), fg=ACCENT, bg=CARD).pack(pady=20)

    def _show_table(self, columns, data, height=20):
        """在右栏显示表格"""
        for w in self.right.winfo_children(): w.destroy()
        tree = ttk.Treeview(self.right, columns=columns, show="headings", height=height)
        for c in columns:
            tree.heading(c, text=c, command=lambda _c=c: self._sort(tree, _c, False))
            tree.column(c, width=max(60, 800//len(columns)), anchor="center", minwidth=50)
        tree.tag_configure("up", foreground=GREEN)
        tree.tag_configure("down", foreground=RED)
        tree.tag_configure("warn", foreground="#f59e0b")
        for i, row in enumerate(data):
            tags = ()
            # 尝试解析涨跌
            for v in row:
                if isinstance(v, str) and v.startswith("+"): tags = ("up",); break
                if isinstance(v, str) and v.startswith("-") and "%" in v: tags = ("down",); break
            if not tags and i%2==0: pass
            tree.insert("", tk.END, values=row, tags=tags)
        vsb = ttk.Scrollbar(self.right, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.cur_tree = tree

    def _show_text(self, text, font=("微软雅黑", 10)):
        for w in self.right.winfo_children(): w.destroy()
        st = tk.Text(self.right, font=font, bg=CARD, fg=TEXT, relief="flat", bd=0,
                     padx=16, pady=12, wrap=tk.WORD)
        st.pack(fill=tk.BOTH, expand=True)
        st.insert(tk.END, text)
        st.config(state=tk.DISABLED)
        self.cur_text = st

    def _sort(self, tree, col, rev):
        data = [(tree.set(c, col), c) for c in tree.get_children("")]
        try: data.sort(key=lambda x: float(x[0].replace("+","").replace("%","").replace(",","")) if x[0].strip("-").replace(".","").isdigit() else x[0], reverse=rev)
        except: data.sort(reverse=rev)
        for i, (_, c) in enumerate(data): tree.move(c, "", i)
        tree.heading(col, command=lambda: self._sort(tree, col, not rev))

    def _status(self, text, color=TEXT2):
        self.top_status.config(text=text, fg=color)

    # ═══════════ 扫描 ═══════════
    def _scan(self):
        if self.busy: return
        self.busy = True; self.cancel_flag = False
        self.prog.start(8); self._status("扫描中…", ACCENT)
        scanner.GROWTH_MODE = self.growth_var.get()
        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, "🔍 扫描 A 股…")
        self.summary.config(state=tk.DISABLED)
        for k in self.idx_labels: self.idx_labels[k][0].config(text="--"); self.idx_labels[k][1].config(text="加载中")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            r = scanner.run_scan(
                progress_callback=lambda m: self.q.put(("prog", m)),
                cancel_check=lambda: self.cancel_flag)
            self.q.put(("scan_done", r))
        except scanner.ScanCancelled: self.q.put(("cancelled", None))
        except Exception as e: self.q.put(("err", str(e)))

    # ═══════════ 其他功能 ═══════════
    def _research(self):
        if self.busy or not self.last_scan: return
        if not llm_client.is_configured():
            messagebox.showinfo("提示", "请先点底部「设置」配置 AI 账号")
            return
        cands = self.last_scan.get("candidates_full") or []
        n = min(8, len(cands))
        if not messagebox.askyesno("确认", f"AI 将对候选前 {n} 只做深度分析\n约 1-2 分钟"): return
        self.busy = True; self.prog.start(8); self._status("AI 分析中…", PURPLE)
        self._show_welcome()
        threading.Thread(target=lambda: self._research_worker(cands, n), daemon=True).start()

    def _research_worker(self, cands, n):
        try:
            results = research.research_candidates(cands, top_n=n,
                progress_callback=lambda m: self.q.put(("prog", m)))
            report = research.build_research_report(results)
            self.q.put(("research_done", report))
        except Exception as e: self.q.put(("err", str(e)))

    def _ind_report(self):
        if self.busy or not self.last_scan: return
        if not llm_client.is_configured(): return messagebox.showinfo("提示", "请先配置 AI 账号")
        if not messagebox.askyesno("确认", "联网搜索产业动态+内外需分析\n约 1-2 分钟"): return
        self.busy = True; self.prog.start(8); self._status("产业研报生成中…", TEAL)
        self._show_welcome()
        threading.Thread(target=self._ind_worker, daemon=True).start()

    def _ind_worker(self):
        try:
            import industry_report
            def chat(messages, temperature=0.5, max_tokens=2500):
                return llm_client.chat(messages, temperature=temperature, max_tokens=max_tokens)
            report = industry_report.generate_research_report(
                self.last_scan, chat, progress_callback=lambda m: self.q.put(("prog", m)))
            self.q.put(("industry_done", report))
        except Exception as e: self.q.put(("err", str(e)))

    def _show_hk(self):
        if self.busy: return
        self.busy = True; self.prog.start(8); self._status("获取港股…", "#6366f1")
        threading.Thread(target=self._hk_worker, daemon=True).start()

    def _hk_worker(self):
        try:
            import hk_stocks
            results, err = hk_stocks.fetch_hk_watchlist()
            if err: self.q.put(("err", err)); return
            self.q.put(("hk_done", results))
        except Exception as e: self.q.put(("err", str(e)))

    def _backtest(self):
        self._status("回测功能请通过命令行使用 python backtest.py", TEXT2)

    def _save(self):
        if not self.last_scan: return
        p = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown","*.md")])
        if p:
            with open(p,'w',encoding='utf-8') as f: f.write(self.last_scan["report"])
            self._status(f"已保存: {p}", GREEN)

    def _settings(self):
        cfg = llm_client.load_config()
        dlg = tk.Toplevel(self.root); dlg.title("AI 账号设置"); dlg.geometry("420x300")
        dlg.configure(bg=CARD); dlg.transient(self.root); dlg.grab_set()
        tk.Label(dlg, text="AI 服务商", font=("微软雅黑", 10, "bold"), fg=TEXT, bg=CARD).pack(pady=(16, 4))
        pv = tk.StringVar(value="deepseek")
        cb = ttk.Combobox(dlg, textvariable=pv, values=list(llm_client.PRESETS.keys()), width=44); cb.pack()
        tk.Label(dlg, text="API Key", font=("微软雅黑", 10, "bold"), fg=TEXT, bg=CARD).pack(pady=(10, 4))
        kv = tk.StringVar(value=cfg.get("api_key", ""))
        tk.Entry(dlg, textvariable=kv, width=46, show="*", bg=CARD2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", bd=1).pack(ipady=4)
        tk.Label(dlg, text="Base URL", font=("微软雅黑", 10, "bold"), fg=TEXT, bg=CARD).pack(pady=(10, 4))
        uv = tk.StringVar(value=cfg.get("base_url", ""))
        tk.Entry(dlg, textvariable=uv, width=46, bg=CARD2, fg=TEXT, insertbackground=TEXT,
                 relief="flat", bd=1).pack(ipady=4)
        mv = tk.StringVar(value=cfg.get("model", ""))
        def on_preset(_):
            p = pv.get()
            if p in llm_client.PRESETS: uv.set(llm_client.PRESETS[p]["base_url"]); mv.set(llm_client.PRESETS[p]["model"])
        cb.bind("<<ComboboxSelected>>", on_preset)
        def test():
            llm_client.save_config(api_key=kv.get().strip(), base_url=uv.get().strip(), model=mv.get().strip())
            try:
                r = llm_client.chat([{"role":"user","content":"回复OK"}], max_tokens=10, timeout=20)
                messagebox.showinfo("成功", f"连接正常: {r[:30]}"); dlg.destroy()
            except Exception as e: messagebox.showerror("失败", str(e))
        tf = tk.Frame(dlg, bg=CARD); tf.pack(pady=14)
        tk.Button(tf, text="测试并保存", font=("微软雅黑", 10), bg=ACCENT, fg="white", bd=0,
                  padx=16, pady=6, cursor="hand2", command=test).pack(side=tk.LEFT, padx=6)
        tk.Button(tf, text="取消", font=("微软雅黑", 10), bg=CARD2, fg=TEXT, bd=0,
                  padx=16, pady=6, cursor="hand2", command=dlg.destroy).pack(side=tk.LEFT, padx=6)

    # ═══════════ 队列 ═══════════
    def _poll(self):
        try:
            while True:
                k, m = self.q.get_nowait()
                if k == "prog": self._status(m[:36], ACCENT)
                elif k == "scan_done":
                    self.busy = False; self.prog.stop(); self._status(f"✅ {m['candidate_count']}只候选", GREEN)
                    self.last_scan = m
                    # 启用分析按钮
                    self.research_btn.config(state=tk.NORMAL)
                    self.ind_report_btn.config(state=tk.NORMAL)
                    # 更新指数
                    if m.get("index_data"):
                        for name, info in m["index_data"].items():
                            if name not in self.idx_labels: continue
                            c = info.get("close"); ch = info.get("chg_pct")
                            if c and ch is not None:
                                self.idx_labels[name][0].config(text=f"{c:.0f}", fg=GREEN if ch>0 else RED)
                                self.idx_labels[name][1].config(text=f"{ch:+.2f}%", fg=GREEN if ch>0 else RED)
                            else:
                                self.idx_labels[name][0].config(text="--", fg=TEXT2)
                                self.idx_labels[name][1].config(text="获取失败", fg=TEXT2)
                    # 摘要
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    cands = m.get("candidates_full") or []
                    s = f"PE 3-40 | ROE>5% | 市值50-10000亿\n{m['candidate_count']}只候选 | {m['industry_count']}行业 | {m['total_stocks']}只覆盖"
                    conc = m.get("concentration", 0)
                    if conc >= 30: s += f"\n⚠️ 集中度 {m.get('top_industry','')} {conc:.0f}%"
                    self.summary.insert(tk.END, s)
                    self.summary.config(state=tk.DISABLED)
                    # 表格
                    if cands:
                        cols = ("代码","名称","PE","ROE%","扣非ROE%","价格","市值(亿)","行业","营收增%","利润增%")
                        rows = []
                        for c in cands[:40]:
                            pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
                            roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
                            droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
                            price = f"{c.get('price',0):.2f}" if c.get('price') else "-"
                            mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
                            rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
                            prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"
                            rows.append((c.get('code',''), c.get('name',''), pe, roe, droe, price, mv, c.get('industry',''), rev, prof))
                        self._show_table(cols, rows, height=22)
                elif k == "research_done":
                    self.busy = False; self.prog.stop(); self._status("✅ 深度分析完成", PURPLE)
                    self.research_btn.config(state=tk.NORMAL)
                    self._show_text(m, ("微软雅黑", 10))
                elif k == "industry_done":
                    self.busy = False; self.prog.stop(); self._status("✅ 产业研报完成", TEAL)
                    self.ind_report_btn.config(state=tk.NORMAL)
                    self._show_text(m, ("微软雅黑", 10))
                elif k == "hk_done":
                    self.busy = False; self.prog.stop(); self._status("✅ 港股数据已更新", "#6366f1")
                    cols = ("代码","名称","行业","最新价","涨跌幅")
                    rows = []
                    for r in m:
                        chg = r.get("chg_pct")
                        rows.append((r["code"], r["name"], r["sector"],
                            f"{r['price']:.2f}" if r["price"] else "-",
                            f"{chg:+.2f}%" if chg is not None else "-"))
                    self._show_table(cols, rows, height=16)
                elif k == "cancelled":
                    self.busy = False; self.prog.stop(); self._status("已取消", TEXT2)
                elif k == "err":
                    self.busy = False; self.prog.stop(); self._status(f"❌ {m[:30]}", RED)
                    self._show_text(f"😞 出错了\n\n{m}\n\n常见原因: 网络太慢 / API限流 → 重试一次")
        except queue.Empty: pass
        self.root.after(200, self._poll)

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    Terminal().run()
