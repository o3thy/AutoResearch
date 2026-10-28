# 第一阶段：ResearchRabbit 检索与追踪

## 概述

本模块负责按关键词、标题或 DOI 检索论文，核对种子后扩展相似文献、参考文献和后续引用，并保存分页采集证据。支持从已保存的网页证据离线回放。

## 环境与前置条件

从项目根目录 `AutoResearch` 执行以下命令。模块代码使用 Python 标准库；实时检索需要 BrowserAct CLI、可用浏览器连接和已登录的 ResearchRabbit 会话。环境配置见[项目总览](../README.md)。

```powershell
browser-act --format json browser list
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py open --browser-id <浏览器列表中的ID>
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py doctor
```

用户在浏览器中完成登录。实时浏览会改变当前搜索页面，同一会话不要并行运行多个网页测试。

## 使用方法

### 检索与扩展

```powershell
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py --output rr/artifacts/my-search.json --evidence-dir rr/artifacts/my-search search "spacecraft pose control"
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py --output rr/artifacts/my-refs.json --evidence-dir rr/artifacts/my-refs expand "10.1016/j.ast.2025.111515" --relation references
```

`--relation` 可取 `similar`、`references` 或 `citations`。标题搜索返回候选集合；需要精确匹配时可通过 `--title "精确标题"` 指定。无法确定种子时返回 `ambiguous_seed`，不会自动选择其他论文。

全局参数写在子命令前，例如 `--session NAME` 复用浏览器会话，`--max-pages N` 限制页数。每次运行使用新的输出文件和证据目录，程序拒绝覆盖已有结果。

### 离线回放

```powershell
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py --output rr/artifacts/replay-new.json replay rr/artifacts/my-capture/page-001.json rr/artifacts/my-capture/page-002.json --relation similar
```

先用实时检索保存证据，再将示例路径替换为实际采集的页面文件。

## 输出与交接

输出 JSON 记录查询、种子、文献列表、分页证据、去重结果及覆盖情况。`status=ok` 表示网站报告范围已完整采集；`partial` 表示采集不完整，`empty` 表示确认无结果。退出码分别为 0（完成或明确为空）、2（部分完成）、1（失败）。

RR 缺失的 DOI、完整作者和摘要保留为空，网站显示年份按原值记录。`metadata_status=unverified` 的题录仍需核验；网站参考文献列表覆盖完整也不代表等于出版社的全部参考文献。

将结果 JSON 交给[第二阶段 Zotero 模块](../zotero/zotero.md)准备批次和获取全文。统一论文字段位于项目根目录的 `schemas/paper.schema.json`。

## 目录结构

| 位置 | 内容 |
| --- | --- |
| `browser.py`、`extract.py`、`workflow.py`、`cli.py` | 浏览器适配、解析、采集流程和命令实现 |
| `scripts/researchrabbit.py` | 命令行入口 |
| `skills/rr-researchrabbit/` | 项目内技能及参考说明 |
| `schemas/rr-result.schema.json` | 检索结果协议 |
| `tests/` | RR 回归测试 |
| `artifacts/` | 原始证据、结果及历史调试记录 |

## 验证与参考

```powershell
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py --help
.\.venv\Scripts\python.exe -m unittest discover -s rr/tests -t . -v
```

详细网页操作、离线回放及状态说明见[浏览器工作流](skills/rr-researchrabbit/references/browser-workflow.md)。
