# 第二阶段：Zotero 题录与全文

## 概述

本模块将文献列表整理为批次，核对 DOI，获取 PDF 并保存到用户指定的 Zotero 集合。下载失败的条目进入清单，可在用户手动下载后继续补录；已有条目和附件会进行重复检查。

## 环境与前置条件

从项目根目录 `AutoResearch` 执行以下命令。需要运行中的 Zotero Desktop、可用的本地 API 和 `zotero/requirements.txt` 中的依赖。共享 Python 环境配置见[项目总览](../README.md)。

```powershell
.\.venv\Scripts\python.exe -m pip install -r zotero/requirements.txt
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py doctor
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py collections
```

目标集合由用户明确指定。需要 Zotero 写入授权时，由用户在 Zotero 弹窗中手动处理；本机授权数据位于 `zotero/.local/`。

## 使用方法

### 准备批次与下载

```powershell
.\.venv\Scripts\python.exe zotero/scripts/prepare_zotero_batch.py rr/artifacts/my-search.json --output zotero/artifacts/my-first30.json --limit 30 --resolve-dois
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py download zotero/artifacts/my-first30.json --collection "指定集合名称"
```

`--resolve-dois` 显式启用缺失 DOI 的核验；存在歧义的候选不会自动选定。也可直接将 RR 输出交给 `download`，缺少或无效 DOI 的条目会进入失败清单。

### 授权、重试和手动补录

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py authorize --timeout 600
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py retry "<manifest.json 的完整路径>"
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py ingest "<manifest.json 的完整路径>"
```

手动补录使用同一批次的 manifest 匹配用户提供的 PDF。完整参数、下载目录、失败列表和手动映射方法见[下载与手动补录说明](docs/zotero-workflow.md)。

## 输出与交接

每篇成功归档的论文对应一个 Zotero 父条目及其 PDF 附件。默认下载目录为 `zotero/download/`，其中保存 PDF、失败 CSV 和可续传的批次 manifest；批次输入和核验报告保存在 `artifacts/`。

将 manifest 交给[第三阶段 Obsidian 模块](../obsidian/obsidian.md)：第三阶段会重新核对已归档条目的父条目键、指定 PDF 附件和哈希。下载失败或附件失败的条目留在本模块重试。

## 目录结构

| 位置 | 内容 |
| --- | --- |
| `batch.py`、`client.py`、`download.py`、`pdf.py`、`workflow.py`、`cli.py` | 批次、连接、下载、PDF 核验和归档实现 |
| `scripts/` | 工作流入口、批次准备及归档核验脚本 |
| `skills/rr-zotero-download/` | 项目内技能 |
| `schemas/zotero-manifest.schema.json` | 下载与归档清单协议 |
| `tests/` | 回归测试 |
| `artifacts/`、`download/` | 批次记录、PDF、失败列表和 manifest |
| `.local/`、`requirements.txt` | 本机授权文件和模块依赖 |
| [docs/zotero-workflow.md](docs/zotero-workflow.md) | 详细使用说明 |

## 验证与参考

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py --help
.\.venv\Scripts\python.exe -m unittest discover -s zotero/tests -t . -v
```

下载、附件回读、手动补录和重复保护的使用细节见[下载与手动补录说明](docs/zotero-workflow.md)。
