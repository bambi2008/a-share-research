#!/usr/bin/env python3
"""
A股投研助手 - 小白友好版 v2
真表格显示候选池，列自动对齐
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading, queue
from datetime import datetime
import scanner, backtest, research, llm_client


class SimpleApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("A股投研助手")
        self.root.geometry("960x700")
        self.root.minsize(720, 500)
        self.root.configure(bg="#f5f6fa")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"960x700+{(sw-960)//2}+{(sh-700)//2}")

        self.q = queue.Queue()
        self.busy = False
        self.last_scan = None

        self.growth_var = tk.BooleanVar(value=False)

        self._build()
        self._poll()

    def _build(self):
        # ── 顶部 ──
        header = tk.Frame(self.root, bg="#1e3a5f", height=70)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="A股投研助手", font=("微软雅黑", 18, "bold"),
                 fg="white", bg="#1e3a5f").pack(side=tk.LEFT, padx=25, pady=18)
        tk.Label(header, text="科技+新能源 · 每周扫描", font=("微软雅黑", 10),
                 fg="#8ab4e0", bg="#1e3a5f").pack(side=tk.RIGHT, padx=25, pady=18)

        # ── 指数卡片 ──
        card = tk.Frame(self.root, bg="white", highlightbackground="#dde1e7", highlightthickness=1)
        card.pack(fill=tk.X, padx=18, pady=(12, 6))
        self.idx_frame = tk.Frame(card, bg="white")
        self.idx_frame.pack(pady=10, padx=14, fill=tk.X)
        self.idx_labels = {}
        for name, _ in scanner.INDICES:
            lbl = tk.Label(self.idx_frame, text=f"{name}\n等待扫描…", font=("微软雅黑", 11),
                           bg="#f0f4ff", fg="#1e3a5f", width=15, height=3, relief="groove", bd=1)
            lbl.pack(side=tk.LEFT, padx=8, expand=True)
            self.idx_labels[name] = lbl

        # ── 按钮 ──
        btn_row = tk.Frame(self.root, bg="#f5f6fa")
        btn_row.pack(fill=tk.X, padx=18, pady=6)
        self.scan_btn = tk.Button(btn_row, text="🔍  开始扫描\n找到科技+新能源的好公司",
                                  font=("微软雅黑", 12, "bold"), bg="#2563eb", fg="white",
                                  activebackground="#1d4ed8", relief="flat", bd=0,
                                  padx=24, pady=12, cursor="hand2", command=self._scan,
                                  width=20, height=2, wraplength=260)
        self.scan_btn.pack(side=tk.LEFT, padx=3)
        self.research_btn = tk.Button(btn_row, text="🤖  深度分析\nAI帮你读财报预测前景",
                                      font=("微软雅黑", 12, "bold"), bg="#7c3aed", fg="white",
                                      activebackground="#6d28d9", relief="flat", bd=0,
                                      padx=24, pady=12, cursor="hand2", command=self._research,
                                      width=20, height=2, wraplength=260, state=tk.DISABLED)
        self.research_btn.pack(side=tk.RIGHT, padx=3)
        # 产业研报按钮
        self.ind_report_btn = tk.Button(btn_row, text="📋  产业研报\nAI研判行业前景与风险",
                                         font=("微软雅黑", 11, "bold"), bg="#059669", fg="white",
                                         activebackground="#047857", relief="flat", bd=0,
                                         padx=16, pady=10, cursor="hand2", command=self._industry_report,
                                         width=18, height=2, wraplength=230, state=tk.DISABLED)
        self.ind_report_btn.pack(side=tk.RIGHT, padx=3)
        self.cancel_btn = tk.Button(btn_row, text="✖ 取消", font=("微软雅黑", 10),
                                    bg="#ef4444", fg="white", bd=0, padx=16, pady=8,
                                    cursor="hand2", command=self._cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.RIGHT, padx=8)
        # 成长股模式复选框
        self.growth_cb = tk.Checkbutton(btn_row, text="成长股", variable=self.growth_var,
            font=("微软雅黑", 9), bg="#f5f6fa", fg="#6b7280",
            activebackground="#f5f6fa", selectcolor="#f5f6fa",
            cursor="hand2")
        self.growth_cb.pack(side=tk.RIGHT, padx=8)
        self.prog_label = tk.Label(btn_row, text="👆 点蓝色按钮开始", font=("微软雅黑", 10),
                                    fg="#6b7280", bg="#f5f6fa")
        self.prog_label.pack(side=tk.LEFT, padx=20)
        self.prog_bar = ttk.Progressbar(btn_row, mode='indeterminate', length=80)
        self.prog_bar.pack(side=tk.RIGHT, padx=8)

        # ── 摘要 + 表格容器 ──
        self.main_area = tk.Frame(self.root, bg="white", highlightbackground="#dde1e7", highlightthickness=1)
        self.main_area.pack(fill=tk.BOTH, expand=True, padx=18, pady=(4, 8))

        # 摘要文本(筛选条件/行业统计)
        self.summary = tk.Text(self.main_area, font=("微软雅黑", 10), bg="white", fg="#374151",
                               height=3, relief="flat", bd=0, padx=12, pady=6, wrap=tk.WORD)
        self.summary.pack(fill=tk.X)
        self.summary.insert(tk.END, "欢迎！点击上方蓝色「开始扫描」按钮，我会帮你找到科技+新能源行业的好公司。\n\n扫描结果会以表格形式显示在这里。")
        self.summary.config(state=tk.DISABLED)

        # 表格框架(初始隐藏)
        self.tree_frame = tk.Frame(self.main_area, bg="white")
        self.tree_frame.pack(fill=tk.BOTH, expand=True)
        self.tree = None

        # 欢迎语(初始显示)
        self.welcome = tk.Label(self.tree_frame, text="📊", font=("微软雅黑", 40), bg="white", fg="#d1d5db")
        self.welcome.pack(expand=True)
        tk.Label(self.tree_frame, text="扫描结果会以表格形式显示在这里", font=("微软雅黑", 11),
                 bg="white", fg="#9ca3af").pack()

        # ── 底部 ──
        bar = tk.Frame(self.root, bg="#e5e7eb", height=30)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        tk.Button(bar, text="设置AI账号", font=("微软雅黑", 9), bg="#e5e7eb", bd=0,
                  command=self._settings, cursor="hand2").pack(side=tk.RIGHT, padx=12, pady=3)
        tk.Button(bar, text="保存报告", font=("微软雅黑", 9), bg="#e5e7eb", bd=0,
                  command=self._save, cursor="hand2").pack(side=tk.RIGHT, padx=8, pady=3)
        tk.Button(bar, text="历史回测(高级)", font=("微软雅黑", 9), bg="#e5e7eb", bd=0,
                  command=self._backtest_dialog, cursor="hand2").pack(side=tk.RIGHT, padx=8, pady=3)

    def _build_tree(self, candidates):
        """构建候选表格"""
        if self.tree:
            self.tree.destroy()
        if self.welcome:
            self.welcome.destroy()
            self.welcome = None
        # 移除tree_frame里的旧label
        for w in self.tree_frame.winfo_children():
            if isinstance(w, tk.Label):
                w.destroy()

        cols = ("代码","名称","PE","ROE%","扣非ROE%","价格","市值(亿)","行业","营收增%","利润增%")
        self.tree = ttk.Treeview(self.tree_frame, columns=cols, show="headings", height=18)

        widths = {"代码":70,"名称":90,"PE":55,"ROE%":55,"扣非ROE%":70,"价格":65,"市值(亿)":75,"行业":100,"营收增%":70,"利润增%":70}
        for c in cols:
            self.tree.heading(c, text=c, command=lambda _c=c: self._sort_tree(_c, False))
            self.tree.column(c, width=widths.get(c,65), anchor="center", minwidth=50)

        # 行颜色交替
        self.tree.tag_configure("odd", background="#f9fafb")
        self.tree.tag_configure("even", background="white")
        self.tree.tag_configure("warn", foreground="#dc2626")

        for i, c in enumerate(candidates[:30]):
            pe = f"{c.get('pe',0):.1f}" if c.get('pe') else "-"
            roe = f"{c.get('roe',0):.1f}" if c.get('roe') is not None else "-"
            droe = f"{c.get('deduct_roe',0):.1f}" if c.get('deduct_roe') is not None else "-"
            price = f"{c.get('price',0):.2f}" if c.get('price') else "-"
            mv = f"{c.get('mktcap',0):.0f}" if c.get('mktcap') else "-"
            rev = f"{c.get('rev_growth',0):.1f}" if c.get('rev_growth') is not None else "-"
            prof = f"{c.get('profit_growth',0):.1f}" if c.get('profit_growth') is not None else "-"

            # 周期顶部预警
            tags = ("odd",) if i%2==0 else ("even",)
            if c.get('profit_growth') and c['profit_growth'] > 500:
                tags = tags + ("warn",)

            self.tree.insert("", tk.END, values=(
                c.get('code',''), c.get('name',''), pe, roe, droe,
                price, mv, c.get('industry',''), rev, prof
            ), tags=tags)

        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def _sort_tree(self, col, reverse):
        """点击表头排序"""
        if not self.tree:
            return
        data = [(self.tree.set(child, col), child) for child in self.tree.get_children("")]
        try:
            data.sort(key=lambda x: float(x[0]) if x[0].replace('.','',1).replace('-','',1).isdigit() else x[0], reverse=reverse)
        except:
            data.sort(reverse=reverse)
        for idx, (_, child) in enumerate(data):
            self.tree.move(child, "", idx)
        self.tree.heading(col, command=lambda: self._sort_tree(col, not reverse))

    # ── 扫描 ──
    def _scan(self):
        if self.busy: return
        self.busy = True
        scanner.GROWTH_MODE = self.growth_var.get()  # 应用成长股模式
        self.cancel_flag = False
        self.scan_btn.config(state=tk.DISABLED, text="⏳  扫描中…")
        self.research_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.prog_bar.start(8)
        self.prog_label.config(text="正在获取数据…")

        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, "🔍 正在扫描 A股 科技+新能源板块…\n⏳ 请稍候，大约 2-3 分钟")
        self.summary.config(state=tk.DISABLED)

        if self.tree:
            self.tree.destroy(); self.tree = None
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        try:
            result = scanner.run_scan(
                progress_callback=lambda m: self.q.put(("prog", m)),
                cancel_check=lambda: self.cancel_flag,
            )
            self.q.put(("done", result))
        except scanner.ScanCancelled:
            self.q.put(("cancelled", None))
        except Exception as e:
            self.q.put(("err", str(e)))

    def _cancel(self):
        self.cancel_flag = True
        self.cancel_btn.config(state=tk.DISABLED)
        self.prog_label.config(text="取消中…")

    # ── 深度研究 ──
    def _research(self):
        if self.busy or not self.last_scan: return
        if not llm_client.is_configured():
            messagebox.showinfo("需要设置", "深度分析需要 AI 账号。\n点底部「设置AI账号」配置。")
            return
        cands = self.last_scan.get("candidates_full") or []
        n = min(8, len(cands))
        if not messagebox.askyesno("确认", f"AI 将对候选前 {n} 只做深度分析\n大约 1-2 分钟，会产生少量 API 费用"): return
        self.busy = True
        self.research_btn.config(state=tk.DISABLED, text="⏳ AI分析中…")
        self.prog_bar.start(8)
        self.prog_label.config(text="AI 正在分析…")
        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, "🤖 AI 正在逐只分析财报和新闻…\n")
        self.summary.config(state=tk.DISABLED)
        if self.tree:
            self.tree.destroy(); self.tree = None
        threading.Thread(target=self._research_thread, args=(cands, n), daemon=True).start()

    def _research_thread(self, cands, n):
        try:
            results = research.research_candidates(cands, top_n=n,
                progress_callback=lambda m: self.q.put(("prog", m)))
            report = research.build_research_report(results)
            self.q.put(("research_done", report))
        except Exception as e:
            self.q.put(("err", str(e)))

    # ── 产业研报 ──
    def _industry_report(self):
        if self.busy or not self.last_scan: return
        if not llm_client.is_configured():
            messagebox.showinfo("需要设置", "产业研报需要 AI 账号。\n点底部「设置AI账号」配置。")
            return
        cands = self.last_scan.get("candidates_full") or []
        if not cands:
            messagebox.showinfo("无数据", "请先扫描候选。")
            return
        if not messagebox.askyesno("确认", "将联网搜索最新产业动态+地缘风险，\nAI 综合研判行业前景和内外需。\n约 1-2 分钟，会产生少量 API 费用。"): return
        self.busy = True
        self.ind_report_btn.config(state=tk.DISABLED, text="⏳ 研报生成中…")
        self.prog_bar.start(8)
        self.prog_label.config(text="搜索产业动态+地缘风险…")
        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, "📋 正在生成产业研报…\n🔍 搜索最新产业新闻\n🌐 评估内外需与地缘风险\n🧠 AI 综合研判\n"); self.summary.config(state=tk.DISABLED)
        if self.tree: self.tree.destroy(); self.tree = None
        threading.Thread(target=self._ind_report_thread, args=(self.last_scan,), daemon=True).start()

    def _ind_report_thread(self, scan_result):
        try:
            import industry_report
            def chat_fn(messages, temperature=0.5, max_tokens=2500):
                return llm_client.chat(messages, temperature=temperature, max_tokens=max_tokens)
            report = industry_report.generate_research_report(
                scan_result, chat_fn,
                progress_callback=lambda m: self.q.put(("prog", m))
            )
            self.q.put(("industry_done", report))
        except Exception as e:
            self.q.put(("err", str(e)))

    # ── 回测 ──
    def _backtest_dialog(self):
        dlg = tk.Toplevel(self.root); dlg.title("历史回测"); dlg.geometry("380x210")
        dlg.transient(self.root); dlg.grab_set(); dlg.configure(bg="#f5f6fa")
        ttk.Label(dlg, text="验证策略在历史上的表现").pack(pady=(15,8))
        ttk.Label(dlg, text="报告期(逗号分隔):").pack()
        rd_var = tk.StringVar(value="20231231,20240331,20240630,20240930,20241231,20250331")
        ttk.Entry(dlg, textvariable=rd_var, width=46).pack(pady=4)
        f2 = tk.Frame(dlg, bg="#f5f6fa"); f2.pack(pady=8)
        ttk.Label(f2, text="持有月:").pack(side=tk.LEFT, padx=4)
        hv=tk.StringVar(value="6"); ttk.Combobox(f2,textvariable=hv,values=["3","6","9","12"],width=5).pack(side=tk.LEFT,padx=4)
        ttk.Label(f2, text="选股数:").pack(side=tk.LEFT, padx=4)
        tv=tk.StringVar(value="10"); ttk.Entry(f2,textvariable=tv,width=5).pack(side=tk.LEFT,padx=4)
        def go():
            dlg.destroy()
            self._run_backtest([d.strip() for d in rd_var.get().split(",") if d.strip()], int(hv.get()), int(tv.get()))
        ttk.Button(dlg, text="开始回测", command=go).pack(pady=10)

    def _run_backtest(self, dates, months, topn):
        self.busy=True; self.prog_bar.start(8); self.prog_label.config(text="回测中…")
        self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
        self.summary.insert(tk.END, f"📊 回测 {len(dates)} 期…\n"); self.summary.config(state=tk.DISABLED)
        if self.tree: self.tree.destroy(); self.tree=None
        def bt():
            try:
                r=backtest.run_rolling_backtest(dates,months,topn,progress_callback=lambda m:self.q.put(("prog",m)))
                self.q.put(("backtest_done", backtest.build_rolling_report(r)))
            except Exception as e: self.q.put(("err", str(e)))
        threading.Thread(target=bt, daemon=True).start()

    # ── 设置 ──
    def _settings(self):
        cfg = llm_client.load_config()
        dlg = tk.Toplevel(self.root); dlg.title("AI 账号设置"); dlg.geometry("440x320")
        dlg.transient(self.root); dlg.grab_set(); dlg.configure(bg="#f5f6fa")
        ttk.Label(dlg, text="AI服务商:").pack(pady=(12,2))
        pv=tk.StringVar(value="deepseek")
        cb=ttk.Combobox(dlg,textvariable=pv,values=list(llm_client.PRESETS.keys()),width=44); cb.pack()
        ttk.Label(dlg, text="API Key:").pack(pady=(8,2))
        kv=tk.StringVar(value=cfg.get("api_key","")); ttk.Entry(dlg,textvariable=kv,width=46,show="*").pack()
        ttk.Label(dlg, text="网址:").pack(pady=(8,2))
        uv=tk.StringVar(value=cfg.get("base_url","")); ttk.Entry(dlg,textvariable=uv,width=46).pack()
        ttk.Label(dlg, text="模型:").pack(pady=(8,2))
        mv=tk.StringVar(value=cfg.get("model","")); ttk.Entry(dlg,textvariable=mv,width=46).pack()
        def on_preset(_):
            p=pv.get()
            if p in llm_client.PRESETS: uv.set(llm_client.PRESETS[p]["base_url"]); mv.set(llm_client.PRESETS[p]["model"])
        cb.bind("<<ComboboxSelected>>", on_preset)
        def test():
            llm_client.save_config(api_key=kv.get().strip(), base_url=uv.get().strip(), model=mv.get().strip())
            try:
                r=llm_client.chat([{"role":"user","content":"回复OK"}],max_tokens=10,timeout=25)
                messagebox.showinfo("成功",f"连接正常！{r[:40]}"); dlg.destroy()
                if self.last_scan: self.research_btn.config(state=tk.NORMAL)
            except Exception as e: messagebox.showerror("失败",f"连接失败:\n{e}")
        tf=tk.Frame(dlg,bg="#f5f6fa"); tf.pack(pady=14)
        tk.Button(tf,text="测试并保存",font=("微软雅黑",11),bg="#2563eb",fg="white",bd=0,padx=18,pady=6,
                  command=test,cursor="hand2").pack(side=tk.LEFT,padx=6)
        tk.Button(tf,text="取消",command=dlg.destroy).pack(side=tk.LEFT,padx=6)

    # ── 保存 ──
    def _save(self):
        if not self.last_scan: return
        p=filedialog.asksaveasfilename(defaultextension=".md",filetypes=[("Markdown","*.md")],
            initialfile=f"report_{datetime.now().strftime('%Y%m%d')}.md")
        if p:
            with open(p,'w',encoding='utf-8') as f: f.write(self.last_scan["report"])
            messagebox.showinfo("已保存",f"保存到:\n{p}")

    # ── 队列 ──
    def _poll(self):
        try:
            while True:
                k, m = self.q.get_nowait()
                if k == "prog": self.prog_label.config(text=m[:40])
                elif k == "done":
                    self.busy = False; self.prog_bar.stop()
                    self.scan_btn.config(state=tk.NORMAL, text="🔍  开始扫描\n找到科技+新能源的好公司")
                    self.cancel_btn.config(state=tk.DISABLED)
                    self.last_scan = m
                    self.research_btn.config(state=tk.NORMAL, text="🤖  深度分析\nAI帮你读财报预测前景")
                    self.ind_report_btn.config(state=tk.NORMAL, text="📋  产业研报\nAI研判行业前景与风险")
                    # 更新指数
                    if m.get("index_data"):
                        for name, info in m["index_data"].items():
                            try:
                                c=info.get("close"); ch=info.get("chg_pct")
                                if c and ch is not None: txt=f"{name}\n{c:.0f} ({ch:+.1f}%)"
                                else: txt=f"{name}\n获取失败"
                                if name in self.idx_labels: self.idx_labels[name].config(text=txt)
                            except: pass
                    # 摘要
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    cands = m.get("candidates_full") or []
                    summary_text = f"筛选条件: PE 3-40 | ROE > 5% | 流通市值 50-10000亿\n"
                    summary_text += f"找到 {m.get('candidate_count',0)} 只候选 | {m.get('industry_count',0)} 个行业 | {m.get('total_stocks',0)} 只覆盖\n"
                    conc = m.get("concentration", 0)
                    if conc >= 30:
                        summary_text += f"⚠️ 行业集中: {m.get('top_industry','')} 占 {conc:.0f}%\n"
                    summary_text += "提示: 利润增% > 500% 的用 🔴 红字标注(可能处于周期顶部)"
                    self.summary.insert(tk.END, summary_text)
                    self.summary.config(state=tk.DISABLED)
                    # 构建表格
                    self._build_tree(cands)
                    self.prog_label.config(text=f"✅ 找到 {m['candidate_count']} 只候选，显示前30只")
                elif k == "research_done":
                    self.busy=False; self.prog_bar.stop()
                    self.research_btn.config(state=tk.NORMAL, text="🤖  深度分析\nAI帮你读财报预测前景")
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    self.summary.insert(tk.END, "🤖 AI 深度分析报告\n⚠️ AI 生成内容可能存在幻觉，请自行核实\n")
                    self.summary.config(state=tk.DISABLED)
                    if self.tree: self.tree.destroy(); self.tree=None
                    # 在tree_frame里用text显示研究结果
                    rt = scrolledtext.ScrolledText(self.tree_frame, font=("微软雅黑", 10), bg="white", wrap=tk.WORD)
                    rt.pack(fill=tk.BOTH, expand=True)
                    rt.insert(tk.END, m)
                    self.text_widget = rt
                    self.prog_label.config(text="✅ AI分析完成")
                elif k == "industry_done":
                    self.busy=False; self.prog_bar.stop()
                    self.ind_report_btn.config(state=tk.NORMAL, text="📋  产业研报\nAI研判行业前景与风险")
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    self.summary.insert(tk.END, "📋 产业深度研报\n🌐 含内外需分析与地缘风险评估\n"); self.summary.config(state=tk.DISABLED)
                    if self.tree: self.tree.destroy(); self.tree=None
                    rt = scrolledtext.ScrolledText(self.tree_frame, font=("SimSun", 10), bg="white", wrap=tk.NONE)
                    rt.pack(fill=tk.BOTH, expand=True)
                    rt.insert(tk.END, m)
                    self.text_widget = rt
                    self.prog_label.config(text="✅ 产业研报完成")
                elif k == "backtest_done":
                    self.busy=False; self.prog_bar.stop()
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    self.summary.insert(tk.END, "📊 历史回测结果\n"); self.summary.config(state=tk.DISABLED)
                    if self.tree: self.tree.destroy(); self.tree=None
                    rt = scrolledtext.ScrolledText(self.tree_frame, font=("SimSun", 10), bg="white", wrap=tk.NONE)
                    rt.pack(fill=tk.BOTH, expand=True)
                    rt.insert(tk.END, m)
                    self.text_widget = rt
                    self.prog_label.config(text="✅ 回测完成")
                elif k == "cancelled":
                    self.busy=False; self.prog_bar.stop()
                    self.scan_btn.config(state=tk.NORMAL, text="🔍  开始扫描\n找到科技+新能源的好公司")
                    self.cancel_btn.config(state=tk.DISABLED)
                    self.prog_label.config(text="已取消")
                elif k == "err":
                    self.busy=False; self.prog_bar.stop()
                    self.scan_btn.config(state=tk.NORMAL, text="🔍  开始扫描\n找到科技+新能源的好公司")
                    self.cancel_btn.config(state=tk.DISABLED)
                    self.prog_label.config(text="❌ 出错，请重试")
                    self.summary.config(state=tk.NORMAL); self.summary.delete(1.0, tk.END)
                    self.summary.insert(tk.END, f"😞 出错: {m}\n\n常见原因: 网络太慢/API限流 → 重试一次")
                    self.summary.config(state=tk.DISABLED)
        except queue.Empty: pass
        self.root.after(200, self._poll)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    SimpleApp().run()
