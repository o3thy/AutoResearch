# 第三阶段：Obsidian 归档、精读与知识整理

## 概述

本模块将第二阶段已归档的 Zotero 文献交给全文归档、中文精读、跨论文知识整理和后续检索流程。它整合了 [Zotero-Analytical-Workflow-Skills](https://github.com/cheneternity/Zotero-Analytical-Workflow-Skills) 的 7 个技能、模板和工具，并提供项目内交接入口。

源码以本机已测试的提交 `6b3202cfb74b9221c3b8048b1dab99e0a294a496` 为基础，保留两处 Zotero SQLite 兼容性修正。原说明见 [UPSTREAM_README.md](UPSTREAM_README.md)，来源与文件哈希见 [UPSTREAM.json](UPSTREAM.json)。

## 环境与前置条件

从项目根目录 `AutoResearch` 执行以下命令。需要 Python 3.11+、可访问的 Zotero 数据和已选择的 Vault；共享环境配置见[项目总览](../README.md)。

```powershell
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py doctor
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py fetch --key ABCD1234
```

`fetch` 的 key 是 Zotero 父条目键；它以 SQLite 只读方式读取身份和附件信息。在 `config.toml` 中填写所选 Vault 与 Zotero 数据目录。`--config` 可选择其他配置，支持 `--vault-root` 的命令可显式选择 Vault。

MinerU CLI 为可选转换后端，需要单独安装并配置；也可根据实际环境使用其他可用的全文转换能力。`convert` 只调用上游 MinerU runner，不会自动切换为 Poppler。

## 使用方法

### 从第二阶段准备阅读交接

```powershell
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py prepare "<第二阶段返回的 manifest.json 完整路径>" --limit 1 --output obsidian/artifacts/my-handoff.json
```

随后可在当前项目中提出：

```text
按第三阶段的项目内技能处理 obsidian/artifacts/my-handoff.json 中的论文。
先检查已有全文和笔记，仅补齐缺失环节；按当前 Vault 模板精读并核验关键结论，
再判断是否更新知识库，最后运行链接与知识库校验，并追加日志。
```

阅读分析由智能体依照技能完成；单篇与批次分别由 `research-vault-ingest-orchestrator` 和 `zotero-collection-manager` 调度。

### 初始化、转换与校验

```powershell
# 显式初始化选定的 Vault；已有文件保持不变
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py init --vault-root "E:/ResearchVault"

# 配置可用的 MinerU CLI 后，将一篇 PDF 转换到新的输出目录
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py convert --input "E:/Papers/paper.pdf" --output "E:/ResearchVault/_staging/run-1"

# 只读校验笔记、全文链接和知识库
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py validate
```

## 输出与交接

`prepare` 仅处理 manifest 中已归档的论文：核对父条目 DOI、指定附件、存储文件和 SHA-256，按 `zotero_key` 复用已有笔记路径。下载或归档未完成的条目列入 `pending_zotero`；身份冲突、PDF 缺失或哈希变化列入 `blocked`。输出必须使用新文件名。

交接清单中的 `ready_for_agent` 表示可以交给阅读技能，并不表示已转换全文或完成精读。实际产物写入选定 Vault：`03fulltext/` 保存全文，`02vault/` 保存单篇笔记，`01knowledge/` 保存跨论文知识，`模板/` 保存模板。结论应保留到笔记、原文或 PDF 的来源链。

## 目录结构

| 位置 | 内容 |
| --- | --- |
| `scripts/obsidian_workflow.py`、`handoff.py`、`cli.py` | 第三阶段入口、交接与工具调度 |
| `skills/` | 上游 7 个项目内技能 |
| `tools/` | 只读 Zotero 提取、Vault 初始化、MinerU 调度和链接校验 |
| `templates/` | 精读模板、六类知识模板及说明 |
| `tests/` | 上游可移植性测试和项目交接回归测试 |
| `config.example.toml`、`config.toml` | 配置示例与不纳入版本控制的本机配置 |
| `artifacts/` | 本机交接清单与验证记录 |
| [docs/integration.md](docs/integration.md) | 来源、交接规则及验证范围 |

## 验证与参考

```powershell
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py --help
.\.venv\Scripts\python.exe -m unittest discover -s obsidian/tests -t . -v
```

项目来源和交接规则见[第三阶段整合说明](docs/integration.md)，上游说明见 [UPSTREAM_README.md](UPSTREAM_README.md)。
