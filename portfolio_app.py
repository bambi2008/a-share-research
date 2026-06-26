#!/usr/bin/env python3
"""投资记录本 — 独立版"""
import tkinter as tk
from tkinter import ttk, messagebox
import json, os, sys
from datetime import datetime

_app_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
PF = os.path.join(_app_dir, 'portfolio.json')

def load():
    return json.load(open(PF,'r',encoding='utf-8')) if os.path.exists(PF) else {"cash":100000,"trades":[],"holdings":{}}

def save(d): json.dump(d, open(PF,'w',encoding='utf-8'), ensure_ascii=False, indent=2)

def buy(code, name, price, shares, date=None):
    d = load(); cost = price*shares; d["cash"]-=cost
    d["trades"].append({"type":"buy","code":code,"name":name,"price":price,"shares":shares,"cost":cost,"date":date or datetime.now().strftime('%Y-%m-%d')})
    h = d["holdings"].get(code, {"shares":0,"cost_basis":0,"name":name})
    h["shares"]+=shares; h["cost_basis"]+=cost; h["avg_cost"]=h["cost_basis"]/h["shares"]; d["holdings"][code]=h
    save(d); return True

def sell(code, price, shares, date=None):
    d = load(); h = d["holdings"].get(code)
    if not h or h["shares"]<shares: return False
    revenue = price*shares; d["cash"]+=revenue
    d["trades"].append({"type":"sell","code":code,"name":h["name"],"price":price,"shares":shares,"revenue":revenue,"date":date or datetime.now().strftime('%Y-%m-%d')})
    h["shares"]-=shares; h["cost_basis"]-=h["avg_cost"]*shares
    if h["shares"]<=0: del d["holdings"][code]
    else: d["holdings"][code]=h
    save(d); return True


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("投资记录本")
        self.root.geometry("700x500"); self.root.configure(bg="#0f1117")
        self._build(); self._refresh()

    def _build(self):
        hdr = tk.Frame(self.root, bg="#161923", height=40); hdr.pack(fill=tk.X)
        tk.Label(hdr, text="投资记录本", font=("微软雅黑",14,"bold"), fg="#e2e8f0", bg="#161923").pack(side=tk.LEFT, padx=16, pady=6)
        self.total_label = tk.Label(hdr, text="", font=("Consolas",12), fg="#22c55e", bg="#161923")
        self.total_label.pack(side=tk.RIGHT, padx=16, pady=6)

        self.tree = ttk.Treeview(self.root, columns=("code","name","shares","avg","price","mv","pnl","pnlpct"), show="headings", height=18)
        for c,t,w in [("code","代码",70),("name","名称",80),("shares","持仓",60),("avg","均价",65),("price","现价",65),("mv","市值",75),("pnl","盈亏",75),("pnlpct","盈亏%",65)]:
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self.tree.tag_configure("up", foreground="#22c55e"); self.tree.tag_configure("down", foreground="#ef4444")

        bar = tk.Frame(self.root, bg="#161923", height=40); bar.pack(fill=tk.X)
        for t, c in [("买入", "#22c55e"), ("卖出", "#ef4444"), ("刷新", "#3b82f6")]:
            tk.Button(bar, text=t, font=("微软雅黑",10), bg=c, fg="white", relief="flat", bd=0, padx=16, pady=6,
                      cursor="hand2", command=lambda x=t: self._trade(x)).pack(side=tk.LEFT, padx=6, pady=4)

    def _refresh(self):
        d = load(); self.tree.delete(*self.tree.get_children())
        total = d["cash"]
        for code, h in d.get("holdings",{}).items():
            price = h.get("current_price", 0)
            mv = price*h["shares"]; total += mv
            pnl = (price-h["avg_cost"])*h["shares"] if price else 0
            pct = (price/h["avg_cost"]-1)*100 if price and h["avg_cost"]>0 else 0
            tag = "up" if pnl>0 else "down" if pnl<0 else ""
            self.tree.insert("", tk.END, values=(code, h["name"], h["shares"], f'{h["avg_cost"]:.2f}',
                f'{price:.2f}' if price else '-', f'{mv:.0f}' if mv else '-',
                f'{pnl:+.0f}' if pnl else '-', f'{pct:+.1f}%' if pct else '-'), tags=(tag,))
        self.total_label.config(text=f"总资产 {total:,.0f}    现金 {d['cash']:,.0f}")

    def _trade(self, action):
        dlg = tk.Toplevel(self.root); dlg.title(action); dlg.geometry("340x360")
        dlg.resizable(False, False)
        dlg.configure(bg="#1a1d27"); dlg.transient(self.root); dlg.grab_set()
        tk.Label(dlg, text=action, font=("微软雅黑",13,"bold"), fg="#e2e8f0", bg="#1a1d27").pack(pady=12)
        fields = [("股票代码:","code"),("价格(元):","price"),("数量(股):","shares"),("日期(可不填):","date")]
        vars = {}
        for label, key in fields:
            tk.Label(dlg, text=label, fg="#94a3b8", bg="#1a1d27").pack()
            v = tk.StringVar(); vars[key] = v
            tk.Entry(dlg, textvariable=v, width=22, bg="#212433", fg="#e2e8f0", relief="flat", bd=1).pack(pady=2, ipady=3)
        def go():
            try:
                co=vars["code"].get().strip(); pr=float(vars["price"].get())
                sh=int(vars["shares"].get()); dt=vars["date"].get().strip() or None
                if action=="买入": buy(co, co, pr, sh, dt)
                else:
                    if not sell(co, pr, sh, dt): messagebox.showerror("错误","持仓不足"); return
                dlg.destroy(); self._refresh()
            except Exception as e: messagebox.showerror("错误", str(e))
        tk.Button(dlg, text="确认", font=("微软雅黑",11), bg="#3b82f6", fg="white", relief="flat", padx=20, pady=6,
                  command=go, cursor="hand2").pack(pady=14)

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    App().run()
