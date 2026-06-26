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
import sys, os
_MEIPASS = getattr(sys, "_MEIPASS", "")
if _MEIPASS and _MEIPASS not in sys.path:
    sys.path.insert(0, _MEIPASS)
_exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
if _exe_dir not in sys.path:
    sys.path.insert(0, _exe_dir)


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
        self.boom_var = tk.BooleanVar(value=False)

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
        # ── 左侧滚动面板 ──
        left_outer = tk.Frame(main, bg=CARD, width=280, highlightbackground=BORDER, highlightthickness=1)
        left_outer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left_outer.pack_propagate(False)
        
        left_canvas = tk.Canvas(left_outer, bg=CARD, width=278, highlightthickness=0, bd=0)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        left_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        left = tk.Frame(left_canvas, bg=CARD)
        left.bind("<Configure>", lambda e: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.create_window((0,0), window=left, anchor="nw", width=264)
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
        b = tk.Button(parent, text=text, font=("微软雅黑", 9, "bold"),
                      bg=color, fg="white", activebackground=color, activeforeground="white",
                      relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
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
        scanner.BOOM_MODE = self.boom_var.get()
        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, "🔍 扫描 A 股…")
        self.summary.config(state=tk.DISABLED)
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
        cands_orig = self.last_scan.get("candidates_full") or []
        # 成长股模式：营收增长优先；价值模式：ROE优先
        tk.Checkbutton(opts, text="爆发模式(卫星)", variable=self.boom_var, font=("微软雅黑", 9), fg="#f59e0b", bg=CARD, selectcolor=CARD, cursor="hand2").pack(side=tk.LEFT, padx=6)
        if self.growth_var.get():
            cands = sorted(cands_orig, key=lambda x: x.get('rev_growth') or 0, reverse=True)
            mode_hint = "营收增长"
        else:
            cands = cands_orig  # already sorted by ROE
            mode_hint = "ROE"
        n = min(8, len(cands))
        if not messagebox.askyesno("确认", f"AI 将对 {mode_hint} 排名前 {n} 只做深度分析\n约 1-2 分钟"): return
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

    def _view_scan(self):
        """重新显示扫描结果（不重新扫描）"""
        if self.busy: return
        m = self.last_scan
        if not m: return
        cands = m.get("candidates_full") or []
        if not cands: return
        self.view_scan_btn.config(state=tk.DISABLED)
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

    def _hk_worker(self):
        try:
            import hk_stocks
            results, err = hk_stocks.fetch_hk_watchlist()
            if err: self.q.put(("err", err)); return
            self.q.put(("hk_done", results))
        except Exception as e: self.q.put(("err", str(e)))

    def _backtest(self):
        self._status("回测功能请通过命令行使用 python backtest.py", TEXT2)

    def _get_advice(self):
        if self.busy or not self.last_scan: return
        if not llm_client.is_configured():
            messagebox.showinfo("提示", "请先点底部「设置」配置 AI 账号"); return
        if not messagebox.askyesno("确认", "AI 将基于候选池给出具体买卖建议\n含标的/价格区间/仓位/止损止盈\n约 1 分钟"): return
        self.busy = True; self.prog.start(8); self._status("生成投资建议…", "#f59e0b")
        threading.Thread(target=self._advice_worker, daemon=True).start()

    def _advice_worker(self):
        try:
            import investment_advice
            def chat(messages, temperature=0.4, max_tokens=2000):
                return llm_client.chat(messages, temperature=temperature, max_tokens=max_tokens)
            report = investment_advice.generate_advice(
                self.last_scan, self.growth_var.get(), chat,
                progress_callback=lambda m: self.q.put(("prog", m)))
            self.q.put(("advice_done", report))
        except Exception as e: self.q.put(("err", str(e)))

    def _save(self):
        if not self.last_scan: return
        p = filedialog.asksaveasfilename(defaultextension=".md", filetypes=[("Markdown","*.md")])
        if p:
            with open(p,'w',encoding='utf-8') as f: f.write(self.last_scan["report"])
            self._status(f"已保存: {p}", GREEN)

    def _show_portfolio(self):
        """投资记录本 — 自包含版本"""
        try:
            # ── 数据加载（内联，不依赖portfolio.py导入） ──
            import json, os as _os, sys as _sys
            _app_dir = _os.path.dirname(_sys.executable) if getattr(_sys, 'frozen', False) else _os.path.dirname(_os.path.abspath(__file__))
            _pf = _os.path.join(_app_dir, 'portfolio.json')
            if _os.path.exists(_pf):
                data = json.load(open(_pf, 'r', encoding='utf-8'))
            else:
                data = {"cash": 100000, "trades": [], "holdings": {}}
            
            # ── 持仓表格 ──
            cols = ("代码","名称","持仓(股)","均价","现价","市值","盈亏","盈亏%")
            rows = []
            for code, h in data.get("holdings", {}).items():
                price = None
                if self.last_scan:
                    for c in self.last_scan.get("candidates_full") or []:
                        if c.get("code") == code: price = c.get("price"); break
                mv = price * h["shares"] if price else 0
                pnl = (price - h["avg_cost"]) * h["shares"] if price else 0
                pnl_pct = (price / h["avg_cost"] - 1) * 100 if price and h["avg_cost"] > 0 else 0
                rows.append((code, h["name"], str(h["shares"]),
                    f"{h['avg_cost']:.2f}", f"{price:.2f}" if price else "-",
                    f"{mv:.0f}" if mv else "-",
                    f"{pnl:+.0f}" if pnl else "-",
                    f"{pnl_pct:+.1f}%" if pnl_pct else "-"))
            
            self._show_table(cols, rows, height=14)
            total = data["cash"] + sum(r[5] for r in rows)
            self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
            self.summary.insert(tk.END, f"总资产: {total:,.0f}  现金: {data['cash']:,.0f}")
            self.summary.config(state=tk.DISABLED)
            self._status(f"总资产 {total:,.0f} | 现金 {data['cash']:,.0f}", TEXT)
        except Exception as e:
            self._status(f"投资记录错误: {e}", RED)
            messagebox.showerror("投资记录", str(e))
