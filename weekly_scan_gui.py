#!/usr/bin/env python3
"""
A股投研助手 — 专业金融终端版
深色主题 / 黄金布局 / 信息分层 / 一眼看重点
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading, queue, sys, os
from datetime import datetime

# ── frozen exe 路径修复 ──
if getattr(sys, 'frozen', False):
    _exe_dir = os.path.dirname(sys.executable)
    if _exe_dir not in sys.path:
        sys.path.insert(0, _exe_dir)

import scanner, backtest, research, llm_client
import investment_advice, industry_report, enrich_report  # PyInstaller显式导入
import portfolio, portfolio_config, hk_stocks
import insider_check, macro_context, dividend_screen, tech_analysis, concept_stocks, strategy_scan


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
        left = tk.Frame(main, bg=CARD, width=280, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        # 按钮组
        btns = tk.Frame(left, bg=CARD)
        btns.pack(fill=tk.X, padx=12, pady=(10, 4))
        self.scan_btn = self._btn(btns, "开始扫描", ACCENT, self._scan)
        self.scan_btn.pack(fill=tk.X, pady=2)
        self.research_btn = self._btn(btns, "深度分析", PURPLE, self._research, disabled=True)
        self.research_btn.pack(fill=tk.X, pady=2)
        self.ind_report_btn = self._btn(btns, "产业研报", TEAL, self._ind_report, disabled=True)
        self.ind_report_btn.pack(fill=tk.X, pady=2)
        self.view_scan_btn = self._btn(btns, "查看扫描结果", "#475569", self._view_scan, disabled=True)
        self.view_scan_btn.pack(fill=tk.X, pady=2)
        self._btn(btns, "港股监控", "#6366f1", self._show_hk).pack(fill=tk.X, pady=2)
        self.advice_btn = self._btn(btns, "投资建议", "#f59e0b", self._get_advice, disabled=True)
        self.advice_btn.pack(fill=tk.X, pady=2)
        self.risk_btn = self._btn(btns, "三仓风控", "#10b981", self._show_risk, disabled=True)
        self.risk_btn.pack(fill=tk.X, pady=2)
        self._btn(btns, "我的投资", "#ec4899", self._show_portfolio).pack(fill=tk.X, pady=2)

        # 成长股开关
        opts = tk.Frame(left, bg=CARD)
        opts.pack(fill=tk.X, padx=14, pady=(6, 4))
        tk.Checkbutton(opts, text="成长股模式 (放宽PE/ROE)", variable=self.growth_var,
                       font=("微软雅黑", 9), fg=TEXT2, bg=CARD, selectcolor=CARD,
                       activebackground=CARD, activeforeground=TEXT,
                       cursor="hand2").pack(side=tk.LEFT)
        tk.Checkbutton(opts, text="卫星", variable=self.boom_var).pack(side=tk.LEFT, padx=4)
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

    def _show_report(self, text, accent_color=ACCENT):
        """富文本报告面板 — 用 Text widget + tags 彩色渲染"""
        for w in self.right.winfo_children(): w.destroy()

        st = tk.Text(self.right, font=("微软雅黑", 10), bg=CARD, fg=TEXT,
                     relief="flat", bd=0, padx=16, pady=12, wrap=tk.WORD,
                     state=tk.NORMAL, cursor="arrow")
        vsb = ttk.Scrollbar(self.right, orient="vertical", command=st.yview)
        st.configure(yscrollcommand=vsb.set)
        st.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ── 定义 tags ──
        st.tag_configure("h1", font=("微软雅黑", 15, "bold"), foreground=accent_color,
                          spacing1=12, spacing3=4)
        st.tag_configure("h1_line", background=accent_color,
                          foreground=accent_color, font=("微软雅黑", 1),
                          spacing1=0, spacing3=6)
        st.tag_configure("h2", font=("微软雅黑", 12, "bold"), foreground=ACCENT,
                          spacing1=10, spacing3=3)
        st.tag_configure("section_ch", font=("微软雅黑", 11, "bold"), foreground=ACCENT,
                          spacing1=12, spacing3=4)
        st.tag_configure("sep", foreground=BORDER, font=("微软雅黑", 2),
                          spacing1=4, spacing3=4)
        st.tag_configure("positive", foreground=GREEN)
        st.tag_configure("negative", foreground=RED)
        st.tag_configure("dim", foreground=TEXT2, font=("微软雅黑", 9))
        st.tag_configure("table_hdr", font=("微软雅黑", 9, "bold"),
                          foreground=TEXT, background=CARD2)
        st.tag_configure("table_row0", foreground=TEXT2, background=CARD)
        st.tag_configure("table_row1", foreground=TEXT2, background="#1e2130")
        st.tag_configure("mono", font=("Consolas", 9))
        st.tag_configure("warn", foreground="#f59e0b")

        # ── 逐行解析插入 ──
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # === 标题块 ===
            if line.startswith("===") and len(line.strip("=")) <= 3:
                j = i + 1
                while j < len(lines) and lines[j].startswith("===") and len(lines[j].strip("=")) <= 3:
                    j += 1
                titles = [l.strip() for l in lines[i:j] if not l.startswith("===") and l.strip()]
                if titles:
                    st.insert(tk.END, titles[0] + "\n", "h1")
                # 下划线模拟
                st.insert(tk.END, "─" * 60 + "\n", "h1_line")
                i = j
                continue

            # --- 分隔线
            if line.startswith("---") and len(line.strip("-")) <= 3:
                st.insert(tk.END, "─" * 50 + "\n", "sep")
                i += 1
                continue

            # ==== 分隔（投资建议特有）
            if line.startswith("====") or (line.startswith("==") and len(line.strip("=")) <= 3):
                st.insert(tk.END, "─" * 50 + "\n", "sep")
                i += 1
                continue

            # ## 小标题
            if line.startswith("## "):
                st.insert(tk.END, line[3:].strip() + "\n", "h2")
                i += 1
                continue

            # 【一、】中文标题
            if line.strip().startswith("【"):
                st.insert(tk.END, line.strip() + "\n", "section_ch")
                i += 1
                continue

            # 说明/引用
            if line.strip().startswith("> ") or line.strip().startswith("说明:") or line.strip().startswith("*本"):
                st.insert(tk.END, line.strip() + "\n", "dim")
                i += 1
                continue

            # 空行
            if not line.strip():
                st.insert(tk.END, "\n")
                i += 1
                continue

            # 表格行 | ... |
            if line.startswith("|") and line.count("|") >= 3:
                if all(c in "|-: " for c in line):
                    i += 1; continue
                st.insert(tk.END, line + "\n", "mono")
                i += 1
                continue

            # 普通文本
            self._insert_colored(st, line.strip() + "\n")
            i += 1

        st.config(state=tk.DISABLED)
        self.cur_text = st

    def _insert_colored(self, st, txt):
        """插入文本，对数词着色"""
        import re
        parts = re.split(r'(\+[0-9,.]+%|\-[0-9,.]+%|\+[0-9,.]+|\-[0-9,.]+)', txt)
        for p in parts:
            if re.match(r'\+[0-9,.]+%?$', p):
                st.insert(tk.END, p, "positive")
            elif re.match(r'\-[0-9,.]+%?$', p):
                st.insert(tk.END, p, "negative")
            else:
                st.insert(tk.END, p)

    def _render_mini_table(self, parent, rows):
        """(保留接口兼容，Text 模式下用 mono tag 替代)"""
        pass

    def _show_text(self, text, font=("微软雅黑", 10)):
        """简单文本（错误信息等）"""
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
        self.summary.insert(tk.END, "扫描 A 股...")
        self.summary.config(state=tk.DISABLED)
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try:
            r = scanner.run_scan(
                progress_callback=lambda m: self.q.put(("prog", m)),
                cancel_check=lambda: self.cancel_flag)
            # 扫描完成后，在GUI层补做策略分池
            self.q.put(("prog", "策略分池..."))
            try:
                import json, os
                cands = r.get("candidates_full", [])

                # 加载分红缓存
                dividend_data = {}
                exe_dir = os.path.dirname(sys.executable) if getattr(sys,'frozen',False) else "."
                cache_path = os.path.join(exe_dir, ".dividend_cache.json")
                try:
                    dividend_data = json.load(open(cache_path, "r", encoding="utf-8"))
                except: pass

                # 为每个候选注入分红数据（简单内联，不import dividend_screen）
                for c in cands:
                    code = c.get("code", "")
                    price = c.get("price")
                    dd = dividend_data.get(code)
                    if dd and price and price > 0:
                        avg_div = dd.get("avg_div", 0) or 0
                        if avg_div > 0:
                            c["div_yield"] = round(avg_div / price * 100, 2)
                            c["div_count"] = dd.get("div_count", 0)

                # === 内联四策略筛选 ===
                sr = {"value": [], "dividend": [], "insider": [], "turnaround": []}

                for c in cands:
                    pe = c.get("pe")
                    roe = c.get("roe")
                    mv = c.get("mktcap")
                    if pe is None or roe is None: continue

                    # V 价值: PE 3-40, ROE>5, MC>50亿
                    if 3 <= pe <= 40 and roe >= 5 and (mv is None or mv >= 50):
                        sr["value"].append(c)

                    # D 红利: PE<30, ROE>5, 股息率>1.5%或分红>=3次
                    if pe <= 30 and roe >= 5:
                        dy = c.get("div_yield")
                        dc = c.get("div_count") or 0
                        if (dy is not None and dy >= 1.5) or dc >= 3:
                            sr["dividend"].append(c)

                    # T 反转: PE<15, ROE 5-15%, 利润增速>0
                    pg = c.get("profit_growth")
                    if pe <= 15 and 5 <= roe <= 15 and pg is not None and pg > 0:
                        sr["turnaround"].append(c)

                # 排序+截断
                sr["value"].sort(key=lambda x: x.get("roe") or 0, reverse=True)
                sr["value"] = sr["value"][:15]
                sr["dividend"].sort(key=lambda x: x.get("div_yield") or 0, reverse=True)
                sr["dividend"] = sr["dividend"][:10]
                sr["turnaround"].sort(key=lambda x: x.get("profit_growth") or 0, reverse=True)
                sr["turnaround"] = sr["turnaround"][:10]

                r["strategy_results"] = sr
                parts = []
                for k in ("value","dividend","insider","turnaround"):
                    n = len(sr.get(k, []))
                    if n: parts.append(f"{k}x{n}")
                self.q.put(("prog", f"策略: {' '.join(parts) if parts else '全部为空'}"))
            except Exception as e:
                import traceback
                self.q.put(("prog", f"策略分池失败: {e}"))
                # 写桌面错误文件
                try:
                    with open(os.path.join(os.path.dirname(sys.executable) if getattr(sys,'frozen',False) else ".", "_strategy_error2.txt"), "w") as f:
                        f.write(f"GUI策略分池错误: {e}\n\n")
                        traceback.print_exc(file=f)
                except: pass
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
        if self.growth_var.get() or self.boom_var.get():
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

    def _show_filtered_table(self):
        """根据策略筛选重新显示表格"""
        m = self.last_scan
        if not m: return
        cands = m.get("candidates_full") or []
        sr = m.get("strategy_results", {})
        fkey = self._strategy_filter.get() if hasattr(self, '_strategy_filter') else "all"
        if fkey != "all" and sr.get(fkey):
            display_cands = [c for c in cands if c.get("strategy") == fkey]
        else:
            display_cands = cands[:40]
        cols = ("代码","名称","PE","ROE%","扣非ROE%","价格","市值(亿)","行业","概念","分红%","高管","趋势","营收增%","利润增%")
        rows = []
        for c in display_cands[:40]:
            pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
            roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
            droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
            price = f"{c.get('price',0):.2f}" if c.get('price') else "-"
            mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
            rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
            prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"
            concepts_str = "/".join(c.get('concepts', [])) if c.get('concepts') else "-"
            div_str = f"{c.get('div_yield'):.1f}%" if c.get('div_yield') else "-"
            insider_str = {"red":"!卖","yellow":"?卖"}.get(c.get('insider_flag'), "-")
            trend = c.get('trend', '')
            trend_str = {"up":"↑","down":"↓","flat":"→"}.get(trend, "-")
            rsi = c.get('rsi14')
            if rsi is not None:
                trend_str += f" {rsi:.0f}"
            rows.append((c.get('code',''), c.get('name',''), pe, roe, droe, price, mv, c.get('industry',''), concepts_str, div_str, insider_str, trend_str, rev, prof))
        self._show_table(cols, rows, height=22)

    def _view_scan(self):
        """重新显示扫描结果（不重新扫描）"""
        if self.busy: return
        m = self.last_scan
        if not m: return
        cands = m.get("candidates_full") or []
        if not cands: return
        self.view_scan_btn.config(state=tk.DISABLED)
        cols = ("代码","名称","PE","ROE%","扣非ROE%","价格","市值(亿)","行业","概念","分红%","高管","趋势","营收增%","利润增%")
        rows = []
        for c in cands[:40]:
            pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
            roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
            droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
            price = f"{c.get('price',0):.2f}" if c.get('price') else "-"
            mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
            rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
            prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"
            concepts_str = "/".join(c.get('concepts', [])) if c.get('concepts') else "-"
            div_str = f"{c.get('div_yield'):.1f}%" if c.get('div_yield') else "-"
            insider_str = {"red":"!卖","yellow":"?卖"}.get(c.get('insider_flag'), "-")
            trend = c.get('trend', '')
            trend_str = {"up":"↑","down":"↓","flat":"→"}.get(trend, "-")
            rsi = c.get('rsi14')
            if rsi is not None:
                trend_str += f" {rsi:.0f}"
            rows.append((c.get('code',''), c.get('name',''), pe, roe, droe, price, mv, c.get('industry',''), concepts_str, div_str, insider_str, trend_str, rev, prof))
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

    def _show_risk(self):
        """三仓风控: 敞口面板 + 动量排名 + 卫星凸性候选。"""
        if self.busy or not self.last_scan: return
        self.busy = True; self.prog.start(8); self._status("生成三仓风控…", "#10b981")
        self._show_welcome()
        threading.Thread(target=self._risk_worker, daemon=True).start()

    def _risk_worker(self):
        try:
            import enrich_report, portfolio
            cands = self.last_scan.get("candidates_full") or []
            pm = {c["code"]: c["price"] for c in cands if c.get("price")}
            # 维护移动止损基准
            try: portfolio.update_highs(pm)
            except Exception: pass
            text = enrich_report.build_extension(cands, pm)
            self.q.put(("risk_done", text))
        except Exception as e:
            self.q.put(("err", str(e)))

    def _get_advice(self):
        if self.busy or not self.last_scan: return
        if not llm_client.is_configured():
            messagebox.showinfo("提示", "请先点底部「设置」配置 AI 账号"); return
        if not messagebox.askyesno("确认", "AI 将基于候选池给出具体买卖建议\n含标的/价格区间/仓位/止损止盈\n约 1 分钟"): return
        self.busy = True; self.prog.start(8); self._status("生成投资建议…", "#f59e0b")
        threading.Thread(target=self._advice_worker, daemon=True).start()

    def _advice_worker(self):
        try:
            import investment_advice, portfolio
            def chat(messages, temperature=0.4, max_tokens=2000):
                return llm_client.chat(messages, temperature=temperature, max_tokens=max_tokens)
            # 用扫描到的现价估算账户总资产，供硬规则把仓位上限换算成可买金额
            pm = {c["code"]: c["price"] for c in (self.last_scan.get("candidates_full") or [])
                  if c.get("price")}
            equity = portfolio.total_equity(pm)
            report = investment_advice.generate_advice(
                self.last_scan, self.growth_var.get() or self.boom_var.get(), chat,
                boom_mode=self.boom_var.get(), equity=equity,
                macro_data=self.last_scan.get("macro_data"),
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
        """显示投资记录本"""
        try:
            import portfolio
        except ImportError as e:
            messagebox.showerror("错误", f"投资模块加载失败: {e}")
            return
        data = portfolio.load()
        # 用扫描结果里的价格（如果有的话）
        pm = {}
        name_map = {}
        if self.last_scan:
            for c in self.last_scan.get("candidates_full") or []:
                if c.get("price"):
                    pm[c["code"]] = c["price"]
                if c.get("name"):
                    name_map[c["code"]] = c["name"]
        status = portfolio.get_portfolio_status(pm)

        # 构建表格
        cols = ("代码","名称","持仓(股)","均价","现价","市值","盈亏","盈亏%")
        rows = []
        for h in status["holdings"]:
            pnl_str = f"{h['pnl']:+.0f}" if h['pnl'] else "-"
            pnl_pct_str = f"{h['pnl_pct']:+.1f}%" if h['pnl_pct'] else "-"
            rows.append((
                h["code"], h["name"], str(h["shares"]),
                f"{h['avg_cost']:.2f}", f"{h['price']:.2f}" if h['price'] else "-",
                f"{h['market_value']:.0f}" if h['market_value'] else "-",
                pnl_str, pnl_pct_str
            ))

        # 显示表格 + 总览
        self._show_table(cols, rows, height=14)
        total = status["total_value"]
        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, f"总资产: {total:,.0f}  现金: {data['cash']:,.0f}")
        self.summary.config(state=tk.DISABLED)
        self._status(f"投资记录 | 总资产 {total:,.0f} | 现金 {data['cash']:,.0f}", TEXT)

        # 弹出操作对话框
        dlg = tk.Toplevel(self.root); dlg.title("记录交易"); dlg.geometry("340x300")
        dlg.configure(bg=CARD); dlg.transient(self.root); dlg.grab_set()
        tk.Label(dlg, text="记录买卖", font=("微软雅黑", 12, "bold"), fg=TEXT, bg=CARD).pack(pady=(14,8))
        tk.Label(dlg, text="股票代码:", fg=TEXT2, bg=CARD).pack()
        code_var = tk.StringVar()
        tk.Entry(dlg, textvariable=code_var, width=20, bg=CARD2, fg=TEXT, relief="flat", bd=1).pack(pady=2, ipady=3)
        tk.Label(dlg, text="价格(元):", fg=TEXT2, bg=CARD).pack()
        price_var = tk.StringVar()
        tk.Entry(dlg, textvariable=price_var, width=20, bg=CARD2, fg=TEXT, relief="flat", bd=1).pack(pady=2, ipady=3)
        tk.Label(dlg, text="数量(股):", fg=TEXT2, bg=CARD).pack()
        shares_var = tk.StringVar()
        tk.Entry(dlg, textvariable=shares_var, width=20, bg=CARD2, fg=TEXT, relief="flat", bd=1).pack(pady=2, ipady=3)
        tk.Label(dlg, text="日期(可选,如2026-06-25):", fg=TEXT2, bg=CARD).pack()
        date_var = tk.StringVar()
        tk.Entry(dlg, textvariable=date_var, width=20, bg=CARD2, fg=TEXT, relief="flat", bd=1).pack(pady=2, ipady=3)

        def do_buy():
            try:
                code=code_var.get().strip(); price=float(price_var.get()); shares=int(shares_var.get())
                d=date_var.get().strip() or None
                nm = name_map.get(code, code)
                t=portfolio.buy(code, nm, price, shares, d)
                messagebox.showinfo("买入成功", f"{code} {nm} {shares}股 @ {price}")
                dlg.destroy(); self._show_portfolio()
            except Exception as e: messagebox.showerror("错误", str(e))
        def do_sell():
            try:
                code=code_var.get().strip(); price=float(price_var.get()); shares=int(shares_var.get())
                d=date_var.get().strip() or None
                t=portfolio.sell(code, price, shares, d)
                if t: messagebox.showinfo("卖出成功", f"{code} {shares}股 @ {price}"); dlg.destroy(); self._show_portfolio()
                else: messagebox.showerror("错误", "持仓不足")
            except Exception as e: messagebox.showerror("错误", str(e))

        f=tk.Frame(dlg, bg=CARD); f.pack(pady=12)
        tk.Button(f,text="买入",font=("微软雅黑",11),bg=GREEN,fg="white",bd=0,padx=16,pady=6,command=do_buy,cursor="hand2").pack(side=tk.LEFT,padx=6)
        tk.Button(f,text="卖出",font=("微软雅黑",11),bg=RED,fg="white",bd=0,padx=16,pady=6,command=do_sell,cursor="hand2").pack(side=tk.LEFT,padx=6)

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
                    self.busy = False; self.prog.stop(); self._status(f"{m['candidate_count']}只候选", GREEN)
                    self.last_scan = m
                    # 启用分析按钮 + 查看扫描结果
                    self.research_btn.config(state=tk.NORMAL)
                    self.ind_report_btn.config(state=tk.NORMAL)
                    self.view_scan_btn.config(state=tk.DISABLED)
                    self.advice_btn.config(state=tk.NORMAL)
                    self.risk_btn.config(state=tk.NORMAL)
                    # 摘要
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    cands = m.get("candidates_full") or []
                    # 添加宏观摘要
                    macro = m.get("macro_data", {})
                    macro_summary = macro.get("summary", "")
                    s = f"PE 3-40 | ROE>5% | 市值50-10000亿\n{m['candidate_count']}只候选 | {m['industry_count']}行业 | {m['total_stocks']}只覆盖"
                    if macro_summary:
                        s += f"\n宏观: {macro_summary}"
                    conc = m.get("concentration", 0)
                    if conc >= 30: s += f"\n[!] 集中度 {m.get('top_industry','')} {conc:.0f}%"
                    # 变化追踪
                    delta = m.get("delta")
                    if delta and delta.get("delta_summary"):
                        s += f"\nvs上次: {delta['delta_summary']}"
                    # 策略分池
                    sr = m.get("strategy_results", {})
                    if sr:
                        parts = []
                        icons = {"value": "V", "dividend": "D", "insider": "I", "turnaround": "T"}
                        for k in ("value", "dividend", "insider", "turnaround"):
                            if sr.get(k):
                                parts.append(f"{icons.get(k,k)}{len(sr[k])}")
                        s += f"\n策略: {' '.join(parts)}"
                    # 数据源指示
                    ds = m.get("data_sources", {})
                    if ds:
                        s += f"\n数据: 行情{ds.get('price','?')} | 指数{ds.get('index','?')} | 季报{ds.get('quarterly','?')}"
                    self.summary.insert(tk.END, s)
                    self.summary.config(state=tk.DISABLED)
                    # 策略筛选按钮
                    if sr:
                        sf = tk.Frame(self.right, bg=CARD)
                        sf.pack(fill=tk.X, padx=6, pady=(4,0))
                        self._strategy_filter = tk.StringVar(value="all")
                        for k, icon, color in [("all","全部","#475569"),("value","V价值",ACCENT),("dividend","D红利","#22c55e"),("insider","I高管","#f59e0b"),("turnaround","T反转","#ef4444")]:
                            if k == "all" or sr.get(k):
                                tk.Radiobutton(sf, text=icon, variable=self._strategy_filter, value=k,
                                    font=("微软雅黑",8,"bold"), fg=TEXT2, bg=CARD, selectcolor=CARD,
                                    activebackground=CARD, activeforeground=color,
                                    cursor="hand2", indicatoron=False, padx=8, pady=2,
                                    command=lambda: self._show_filtered_table()).pack(side=tk.LEFT)
                    # 表格
                    if cands:
                        # 应用策略筛选
                        fkey = self._strategy_filter.get() if hasattr(self, '_strategy_filter') else "all"
                        if fkey != "all" and sr.get(fkey):
                            display_cands = [c for c in cands if c.get("strategy") == fkey]
                        else:
                            display_cands = cands[:40]
                        cols = ("代码","名称","PE","ROE%","扣非ROE%","价格","市值(亿)","行业","概念","分红%","高管","趋势","营收增%","利润增%")
                        rows = []
                        for c in display_cands[:40]:
                            pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
                            roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
                            droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
                            price = f"{c.get('price',0):.2f}" if c.get('price') else "-"
                            mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
                            rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
                            prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"
                            concepts_str = "/".join(c.get('concepts', [])) if c.get('concepts') else "-"
                            div_str = f"{c.get('div_yield'):.1f}%" if c.get('div_yield') else "-"
                            insider_str = {"red":"!卖","yellow":"?卖"}.get(c.get('insider_flag'), "-")
                            trend = c.get('trend', '')
                            trend_str = {"up":"↑","down":"↓","flat":"→"}.get(trend, "-")
                            rsi = c.get('rsi14')
                            if rsi is not None:
                                trend_str += f" {rsi:.0f}"
                            rows.append((c.get('code',''), c.get('name',''), pe, roe, droe, price, mv, c.get('industry',''), concepts_str, div_str, insider_str, trend_str, rev, prof))
                        self._show_table(cols, rows, height=22)
                elif k == "research_done":
                    self.busy = False; self.prog.stop(); self._status("深度分析完成", PURPLE)
                    self.research_btn.config(state=tk.NORMAL)
                    self.view_scan_btn.config(state=tk.NORMAL)
                    self._show_report(m, PURPLE)
                elif k == "industry_done":
                    self.busy = False; self.prog.stop(); self._status("产业研报完成", TEAL)
                    self.ind_report_btn.config(state=tk.NORMAL)
                    self.view_scan_btn.config(state=tk.NORMAL)
                    self._show_report(m, TEAL)
                elif k == "advice_done":
                    self.busy = False; self.prog.stop(); self._status("投资建议已生成", "#f59e0b")
                    self.advice_btn.config(state=tk.NORMAL)
                    self.view_scan_btn.config(state=tk.NORMAL)
                    self._show_report(m, "#f59e0b")
                elif k == "risk_done":
                    self.busy = False; self.prog.stop(); self._status("三仓风控已生成", "#10b981")
                    self.risk_btn.config(state=tk.NORMAL)
                    self.view_scan_btn.config(state=tk.NORMAL)
                    self._show_report(m, "#10b981")
                elif k == "hk_done":
                    self.busy = False; self.prog.stop(); self._status("港股数据已更新", "#6366f1")
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
                    self.busy = False; self.prog.stop(); self._status(f"错误: {m[:30]}", RED)
                    self._show_text(f"出错了\n\n{m}\n\n常见原因: 网络太慢 / API限流 -> 重试一次")
        except queue.Empty: pass
        self.root.after(200, self._poll)

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    Terminal().run()
