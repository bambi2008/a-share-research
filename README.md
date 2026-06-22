# A股科技+新能源 周度扫描

每周自动扫描科技 + 新能源板块，输出完整投研周报。提供 **命令行** 和 **Windows 桌面 GUI** 两种用法。

## 版本

| 版本 | 文件 | 说明 |
|------|------|------|
| **v4** | `scanner.py` + `weekly_scan_gui.py` | 推荐。TTM PE / 超时取消 / 行业集中度 |
| v3 | `weekly_scan_v3.py` | CLI，单季×4 PE |
| v2 | `weekly_scan_v2.py` | 关键词匹配 |
| v1 | `weekly_scan.py` | 东方财富源（Windows TLS 不可用） |

## 快速开始

### 桌面版（推荐）

```bash
pip install akshare pandas
python weekly_scan_gui.py
```

或直接运行打包好的 `dist/A股周度扫描.exe`（无需 Python 环境）。

### 命令行版

```bash
python scanner.py
```

## 架构

```
scanner.py            # 核心扫描逻辑（数据获取/筛选/报告生成）
├── weekly_scan_gui.py   # tkinter 桌面界面（引用 scanner）
└── (CLI)                # scanner.py 直接运行
```

## v4 功能

- **大盘指数**: 上证/创业板/科创50 周涨跌
- **行业扫描**: 19 个科技+新能源行业，约 1576 只股票
- **质量筛选**: PE 3-40 | ROE > 5%
- **TTM PE**: 滚动四季 EPS 计算，规避单季×4 对周期股的失真
- **行业集中度提示**: 候选池单一行业占比 ≥30% 时警告
- **方法论局限说明**: 报告内置 PE/ROE/周期股/市值/回测 风险提示
- **超时 + 取消**: 单请求 90s 超时；GUI 提供取消按钮，避免无限卡死

## 数据源

| 数据 | 来源 | 函数 |
|------|------|------|
| 季报(ROE/增长/行业) | 巨潮资讯 | `stock_yjbb_em` |
| 实时行情 | 新浪 | `stock_zh_a_spot` |
| 大盘指数 | 新浪 | `stock_zh_index_daily` |

> 不使用东方财富 API —— Windows Schannel TLS 与其 CDN 不兼容。

## TTM PE 算法

```
TTM EPS = 最新累计 EPS + 上年年报 EPS − 上年同期累计 EPS
PE = 现价 / TTM EPS
```

相比单季×4，能正确反映周期股全年盈利能力。例：存储芯片股在景气高点单季暴利，
单季×4 会大幅低估 PE（看起来很便宜），TTM 则还原真实估值。

## 打包为 .exe

```bash
pip install pyinstaller
python -m PyInstaller --onefile --noconsole \
  --name "A股周度扫描" \
  --collect-all akshare \
  --add-data "scanner.py;." \
  weekly_scan_gui.py
```

产物约 68 MB（含 Python + pandas + akshare + Tcl/Tk 运行时）。

## 已知限制

- PE 为 TTM 估算，未剔除非经常性损益
- 无市值过滤（无非东财数据源）
- 无持仓体检功能
- 无策略回测
