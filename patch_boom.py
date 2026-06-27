import ast
f=open("weekly_scan_gui.py","r",encoding="utf-8"); lines=f.readlines(); f.close()
# 1
for idx,l in enumerate(lines):
    if l.strip()=="self.growth_var = tk.BooleanVar(value=False)":
        lines.insert(idx+1, "        self.boom_var = tk.BooleanVar(value=False)\n"); break
# 2
target=-1
for idx,l in enumerate(lines):
    if "成长股模式" in l:
        for j in range(idx,min(idx+8,len(lines))):
            if ".pack(side=tk.LEFT)" in lines[j]: target=j; break
        break
if target>0:
    lines.insert(target+1, '        tk.Checkbutton(opts, text="卫星", variable=self.boom_var).pack(side=tk.LEFT, padx=4)\n')
# 3
for idx,l in enumerate(lines):
    if "scanner.GROWTH_MODE = self.growth_var.get()" in l:
        lines.insert(idx+1, "        scanner.BOOM_MODE = self.boom_var.get()\n"); break
f=open("weekly_scan_gui.py","w",encoding="utf-8"); f.writelines(lines); f.close()
ast.parse(open("weekly_scan_gui.py","r",encoding="utf-8").read())
print("OK")
