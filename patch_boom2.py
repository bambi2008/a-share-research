import ast
f=open("weekly_scan_gui.py","r",encoding="utf-8"); lines=f.readlines(); f.close()
# Fix 1: _research sort
for idx,l in enumerate(lines):
    if "if self.growth_var.get():" in l and idx > 200 and idx < 220:
        lines[idx] = "        if self.growth_var.get() or self.boom_var.get():\n"
        break
# Fix 2: _advice_worker mode flag
for idx,l in enumerate(lines):
    if "self.last_scan, self.growth_var.get(), chat," in l:
        lines[idx] = l.replace("self.growth_var.get()", "self.growth_var.get() or self.boom_var.get()")
        break
f=open("weekly_scan_gui.py","w",encoding="utf-8"); f.writelines(lines); f.close()
ast.parse(open("weekly_scan_gui.py","r",encoding="utf-8").read())
print("OK")
