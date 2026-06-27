# A股投研助手 — Claude Code 接手文档

## 项目概述

个人投资者的 A 股投研 + 交易记录一体化桌面工具。68MB 独立 exe，双击即用。

**核心功能**:
- 32 行业 A 股扫描（价值/成长/爆发 三种模式）
- 个股深度分析（LLM 读财报+新闻 → 6-12 月前瞻）
- 产业研报（联网搜索 + 内外需 + 地缘风险）
- 投资建议（LLM 出买卖/仓位/止损止盈/6月预测/12-18月预测）
- 港股监控（15 只核心标的，新浪数据源）
- 多期回测（夏普/索提诺/卡尔玛/Alpha）
- 独立投资记录本（桌面 exe，买入卖出/盈亏追踪）

**核心技术栈**: Python 3.11 / tkinter / akshare / baostock / PyInstaller / DeepSeek API

## 快速上手

```bash
# 1. 克隆 + 安装依赖
git clone https://github.com/bambi2008/a-share-research.git
cd a-share-research
uv pip install akshare baostock pyinstaller

# 2. 运行 GUI（开发模式）
python weekly_scan_gui.py

# 3. 打包 exe
python -m PyInstaller --onefile --console --name "A股投研助手" \
  --collect-all akshare --collect-all baostock \
  --add-data "scanner.py;." --add-data "backtest.py;." \
  --add-data "research.py;." --add-data "llm_client.py;." \
  --add-data "position.py;." --add-data "industry_report.py;." \
  --add-data "hk_stocks.py;." --add-data "investment_advice.py;." \
  --add-data "portfolio.py;." --add-data "data_source.py;." \
  --distpath ./dist --workpath ./build --specpath ./build -y \
  weekly_scan_gui.py
```

## 文件结构

| 文件 | 用途 | 关键点 |
|------|------|--------|
| `weekly_scan_gui.py` | **主 GUI**（深色金融终端风格）| ⚠️ 极易被破坏，改动必须配合 PyInstaller 测试 |
| `scanner.py` | 核心扫描引擎 | TTM PE/扣非ROE/市值过滤/三种模式 |
| `backtest.py` | 多期滚动回测 | 夏普/索提诺/卡尔玛/Alpha/Beta |
| `research.py` | 个股深度研究 | 同花顺数据 + LLM 研判 |
| `industry_report.py` | 产业研报 | DuckDuckGo搜索 + LLM 综合 |
| `investment_advice.py` | 投资建议 | 结构化 prompt → LLM 出买卖建议 |
| `llm_client.py` | LLM 客户端 | OpenAI 兼容接口，config.json 持久化 |
| `data_source.py` | 多源容灾 | 新浪→baostock→本地缓存三级降级 |
| `hk_stocks.py` | 港股监控 | 15 只标的，新浪 `stock_hk_spot` |
| `portfolio.py` | 持仓模块 | holdings.json 读写 | ⚠️ frozen exe 中 import 会失败 |
| `portfolio_app.py` | **独立投资记录本** | 纯 tkinter+json，无外部依赖 |
| `industries.json` | 行业配置 | 32 个行业，可热编辑 |
| `config.json` | API 配置 | 用户自行在 GUI 填写 DeepSeek key |
| `data_cache/` | 本地缓存 | 3600s TTL |

## 三种扫描模式

| 模式 | GUI 勾选 | PE | ROE | 营收增长 | 行业 |
|------|---------|-----|-----|---------|------|
| 价值（核心） | 不勾任何 | 3-40 | >5% | - | 全部 32 个 |
| 成长 | 勾"成长股" | <200 | >0% | >20% | 全部 32 个 |
| **爆发（卫星）** | 勾"卫星" | 不限 | 不限 | **>30%** | **18 个爆发行业** |

## ⚠️ 已知陷阱

### 1. GUI 极其脆弱
`weekly_scan_gui.py` 任何改动都可能导致 exe 闪退。
- 只用 Python ast.parse 验证语法不够——必须实际打包并测试 exe 能否打开
- 上次稳定版是 git commit `dacb80f`（v13），可作为回滚锚点
- 不要在 GUI 文件中做大段代码替换，用增量修改

### 2. PyInstaller frozen import 问题
在 frozen exe 中，`import portfolio` 会失败。
- 解决方案：投资记录本独立为 `portfolio_app.exe`，纯 tkinter+json
- 修复 frozen import 的方法：在方法内用 `sys.executable` 动态添加路径

### 3. 数据源
- Windows 上东方财富 API 不兼容（Schannel TLS），已改为新浪 + 巨潮
- `stock_hk_spot_em`（东财）会连接失败，改用 `stock_hk_spot`（新浪）
- 指数 API（`stock_zh_index_daily`）不稳定，已从 GUI 删除

### 4. 扫描一致性
扣非 ROE 接口偶发失败 → 加了 fallback → 两次连续扫描 100% 重叠

### 5. 按钮绑定问题
emoji 字符可能导致 tkinter 按钮无响应，避免在按钮文本中使用 emoji

## 当前状态 (v15+)

### ✅ 稳定功能
- A 股扫描（价值/成长/爆发三模式）
- 深度分析（勾卫星时按营收增速排序）
- 投资建议（含 6 月/12-18 月预测，卫星止盈 40%+）
- 港股监控（新浪数据源）
- 独立投资记录本

### 🔧 待修
- 产业研报按钮在 GUI 中已连接，但 `industry_report.py` 的 DuckDuckGo 搜索在 frozen exe 中可能不可用

### 📋 下一步方向
1. 爆发模式 GUI 显示优化（当前复选框文字为英文 "satellite"）
2. 数据源健康面板（显示各数据源状态）
3. 自动止损提醒
4. 回测集成到 GUI（当前仅命令行可用）

## 部署

桌面两个 exe：
- `A股投研助手.exe` — 主程序
- `投资记录本.exe` — 独立记账

构建命令见上方。部署到桌面：
```bash
rm -f "/c/Users/ss/Desktop/A股投研助手.exe" && sleep 2
cp "dist/A股投研助手.exe" "/c/Users/ss/Desktop/"
```
