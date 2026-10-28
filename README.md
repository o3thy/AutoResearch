# AutoResearch

版本：v0.1

以 ResearchRabbit、Zotero 和 Obsidian 串联文献发现、PDF 归档与阅读整理的项目。用户可以逐步运行命令，也可以让支持项目内技能的 AI agent 按工作流操作。

```text
研究问题 / 种子论文
  → ResearchRabbit：检索、引文扩展、保存网页证据
  → Zotero：核验题录、获取 PDF、归档到指定集合
  → Obsidian：全文归档、精读笔记、跨论文知识与检索
```

## 功能与项目结构

| 阶段 | 模块说明 | 输入与输出 |
| --- | --- | --- |
| 1. 文献发现 | [rr/rr.md](rr/rr.md) | 关键词、标题或 DOI → 相关论文 JSON、分页证据与覆盖状态 |
| 2. 文献归档 | [zotero/zotero.md](zotero/zotero.md) | 论文 JSON → Zotero 条目、PDF 附件、批次 manifest 和失败清单 |
| 3. 阅读整理 | [obsidian/obsidian.md](obsidian/obsidian.md) | 已归档文献 manifest → 阅读交接清单；由 agent 使用技能建立全文、精读笔记和知识 |

```text
AutoResearch/
  rr/                   ResearchRabbit 适配器、技能、结果协议与测试
  zotero/               Zotero 下载、归档、批次恢复与测试
  obsidian/             全文、精读、知识整理技能及交接工具
  schemas/              共用论文数据结构
  scripts/              共用 Schema 校验工具
  AGENTS.md             项目内 agent 工作约定
  requirements-dev.txt  开发与测试依赖
  THIRD_PARTY_NOTICES.md 上游来源及许可说明
```

每个模块包含自己的使用说明、技能、工具和测试。`artifacts/`、下载目录、本机授权信息与 Vault 配置由本机运行产生，不作为通用示例随仓库分发。

## 搭建环境

以下示例面向 Windows PowerShell，命令均从项目根目录执行。完整工作流需要 Python 3.11 或更高版本；请先安装 [Python](https://www.python.org/downloads/)。

### 1. 获取项目并安装依赖

仓库完成发布后，可使用以下命令获取项目：

```powershell
git clone https://github.com/o3thy/AutoResearch.git AutoResearch
cd AutoResearch

python --version  # 确认版本为 3.11 或更高
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r zotero/requirements.txt

# 如需运行完整测试与 Schema 校验
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

RR 模块和第三阶段的上游工具主要使用 Python 标准库；Zotero 模块需要 `pypdf`。

### 2. 准备 ResearchRabbit 和浏览器

注册并登录 [ResearchRabbit](https://www.researchrabbit.ai/)。项目内的实时网页适配器使用 BrowserAct CLI；先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后安装 BrowserAct：

```powershell
uv tool install browser-act-cli --python 3.12
browser-act --version
browser-act --format json browser list
```

如果没有可用的 BrowserAct 浏览器配置，可创建一个本地 Chrome 配置：

```powershell
browser-act --format json browser create --type chrome --name researchrabbit --desc "ResearchRabbit literature search"
browser-act --format json browser list
```

复制列表中的浏览器 ID，在项目中打开网站并完成手动登录：

```powershell
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py open --browser-id "<浏览器 ID>"
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py doctor
```

在打开的浏览器中登录后再执行 `doctor`。浏览器 ID 与会话名称不同；使用 `--session NAME` 时，打开、检查和检索都应使用同一名称。为兼容已有会话，默认 BrowserAct 会话标识仍为 `rr-zotero-obsidian`；浏览器命令可能因版本变化，请以 `browser-act --help` 为准。详细说明见 [RR 模块](rr/rr.md)。

### 3. 准备 Zotero

安装并启动 [Zotero Desktop](https://www.zotero.org/download/)，确保本地 API 可用。本项目的写入流程面向支持本地写入 API 的 Zotero 10。检查连接并查看已有集合：

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py doctor
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py collections
```

如需保存条目和附件，运行以下命令并在 Zotero 的授权弹窗中手动操作：

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py authorize --timeout 600
```

后续命令必须指定集合名称或集合 key。授权信息保存在本机 `zotero/.local/`；请勿将它提交到公开仓库。具体授权、下载和手动补录步骤见 [Zotero 模块](zotero/zotero.md)。

### 4. 准备 Vault 和全文转换环境

安装 [Obsidian](https://obsidian.md/download) 以便浏览和编辑笔记；Vault 本质上是普通 Markdown 文件目录。已有 Vault 可以复用，新 Vault 可使用下方初始化命令创建。

复制并编辑本机配置，填入自己的路径；命令不会覆盖已有配置：

```powershell
if (-not (Test-Path -LiteralPath 'obsidian/config.toml')) {
    Copy-Item -LiteralPath 'obsidian/config.example.toml' -Destination 'obsidian/config.toml'
}
```

配置文件中的字段如下；路径仅为示例，请按本机环境修改：

```toml
[paths]
vault_root = "C:/ResearchVault"
zotero_data_dir = "C:/Users/your-user/Zotero"
mineru_executable = ""
archive_root = "C:/ResearchVault/_staging/mineru"
```

如要新建或补齐选定 Vault 的目录与缺失模板，先将 `vault_root` 设置为同一目标，再显式运行：

```powershell
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py init --vault-root "C:/ResearchVault"
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py doctor
```

`init` 只创建缺失目录、模板和配置，不自动迁移旧 Vault；已有配置不会被它改写。`obsidian/config.toml` 不纳入版本控制。可通过 `--config` 选择其他配置，或在支持的命令中使用 `--vault-root` 指定目标。

MinerU CLI 是可选的 PDF 转换后端，需单独安装并在配置中指定可执行文件。`convert` 命令仅调度 MinerU，不会自动切换为 Poppler。可用的其他转换工具及使用方式由实际环境和全文归档技能决定。[Obsidian 模块](obsidian/obsidian.md)说明了转换和验证边界。

## 从检索到阅读

下面演示阶段间的输入输出。命令中的 DOI、集合、文件名和路径都可替换；每次检索、批次和交接使用新输出路径，避免覆盖既有证据。

### 1. 检索并扩展种子

登录 ResearchRabbit 后，用 DOI 扩展参考文献：

```powershell
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py --output rr/artifacts/refs.json --evidence-dir rr/artifacts/refs expand "10.1016/j.ast.2025.111515" --relation references
```

`--relation` 也可设置为 `similar` 或 `citations`。检查输出的 `status`、覆盖率和未核验题录；`partial` 表示采集不完整，网站返回的参考文献不保证等于出版社完整书目。

### 2. 核验 DOI 并归档至 Zotero

先为检索结果生成批次。`--resolve-dois` 仅接受满足匹配和佐证条件的结果，歧义项仍留待处理：

```powershell
.\.venv\Scripts\python.exe zotero/scripts/prepare_zotero_batch.py rr/artifacts/refs.json --output zotero/artifacts/batch.json --limit 10 --resolve-dois
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py download zotero/artifacts/batch.json --collection "<已有 Zotero 集合名称或 key>"
```

输出会报告本批次 `manifest`、失败 CSV 和状态。PDF 获取受出版方权限和可用来源影响；失败项可以按 [Zotero 模块](zotero/zotero.md)说明重试或手动补录。

### 3. 交给阅读技能

将上一步返回的 manifest 路径填入：

```powershell
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py prepare "<manifest.json 的完整路径>" --limit 1 --output obsidian/artifacts/handoff.json
```

交接时重新核对父条目、指定 PDF 附件和文件哈希；未归档项不会进入待阅读队列。`ready_for_agent` 表示可交给 agent，并不表示全文转换或精读已完成。随后可让 agent 根据第三阶段技能检查既有状态、补齐全文和笔记、判断是否更新知识库并运行校验。

## 与 AI agent 协作

在支持项目指令的 agent 中打开项目根目录，让它读取 [AGENTS.md](AGENTS.md) 和对应模块的技能；若当前工具不会自动读取项目指令，可在请求中明确指定。可以从单个种子或小批次开始，例如：

```text
请读取本项目 AGENTS.md，按 RR → Zotero → Obsidian 的流程处理我指定的论文。
先在 ResearchRabbit 扩展参考文献，报告覆盖状态；将确认的论文归档到我指定的 Zotero 集合；
再对成功归档的条目检查身份、已有全文和笔记，并按当前 Vault 模板精读。
请报告每个阶段实际完成、失败和待处理的内容，并给出结果文件位置。
```

ResearchRabbit 登录和 Zotero 授权由用户在各自界面完成。项目 CLI 提供网页采集、归档和交接工具；论文精读与跨论文知识整理由具备相应能力的 agent 按技能执行，具体完成情况需以实际运行与校验结果为准。

## 检查与参考

```powershell
.\.venv\Scripts\python.exe rr/scripts/researchrabbit.py --help
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py --help
.\.venv\Scripts\python.exe obsidian/scripts/obsidian_workflow.py --help
.\.venv\Scripts\python.exe -m unittest discover -s . -v
```

各模块的实时验证、失败处理和局限分别见 [RR](rr/rr.md)、[Zotero](zotero/zotero.md) 和 [Obsidian](obsidian/obsidian.md) 文档。上游项目来源及许可范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证与上游来源

本项目中由项目贡献者拥有授权权利的原创内容按 [MIT License](LICENSE) 发布。第三方材料保留各自的许可及版权要求；第三阶段上游快照未提供独立许可证；项目维护者已获得口头再分发授权。MIT 许可证不自动覆盖该第三方源码，其他使用者的权利范围以权利人的授权为准。详情见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
