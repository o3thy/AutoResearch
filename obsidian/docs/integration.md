# 第三阶段整合记录

日期：2026-10-28，Asia/Shanghai。

## 项目来源

- 上游：https://github.com/cheneternity/Zotero-Analytical-Workflow-Skills 。
- 基线：此前在本机验证的上游源码快照。
- 源提交：`6b3202cfb74b9221c3b8048b1dab99e0a294a496`。本次固定此版本，不用未经本机验证的新版本替换。
- 完整复制 39 个受版本控制的源码文件；`README.md`、`INSTALL.md` 在模块内分别保存为 `UPSTREAM_README.md`、`UPSTREAM_INSTALL.md`。
- 保留本机修正：附件查询取 `items.key`，并同步修正 SQLite 测试表。原始差异见 [local-tested-fixes.patch](local-tested-fixes.patch)。
- 来源文件哈希记录于 [../UPSTREAM.json](../UPSTREAM.json)。没有复制原仓库 `.git`、私人文献、PDF、全局技能的本机配置附录或旧研究项目的专用批处理脚本。

该源码快照没有独立 LICENSE 文件。本模块保留上游出处与材料，不将其宣称为 MIT 授权；RR 部分已有的 MIT 声明仅适用于其对应来源。

## 7 个技能

| 技能 | 职责 |
| --- | --- |
| `zotero-data-fetcher` | 核对父条目与 PDF 身份，读取题录、批注及原文证据 |
| `zotero-fulltext-archiver` | 归档全文 Markdown、图片及与笔记的身份链 |
| `zotero-analytical-writer` | 按模板创建中文精读笔记，区分原文与研究者判断 |
| `research-vault-knowledge-maintainer` | 维护跨论文主题、概念、方法、关系、争议和综合 |
| `research-vault-literature-retrieval` | 笔记优先检索，再定向核验全文/PDF |
| `research-vault-ingest-orchestrator` | 指定单篇的增量处理与状态控制 |
| `zotero-collection-manager` | 指定集合的小批量调度与断点续处理 |

这些技能作为项目文件使用，没有安装、替换或改写全局技能。
解释其中的 `repository`、`tools/`、`templates/` 时，根目录是本模块 `obsidian/`。
本项目新增 CLI 的命令则从整个 `AutoResearch` 根目录运行。

## 第二阶段交接

输入是第二阶段的实际 manifest。仅 `state=attached` 的条目可申请进入阅读队列，且必须重新验证父条目 DOI、原指定附件键、存储 PDF 和原哈希。
后续论文继续使用同一 `zotero_key` 和 `pdf_key`；不凭相似标题猜测附件，不把下载失败状态跳过为阅读完成。
本机输出仍使用已有 Vault 配置。切换 Vault 要显式指定，初始化也要显式执行。

身份与哈希交接成功只表示论文可以进入阅读流程，不代表完成全文归档、精读或知识更新。未完成归档的条目继续留在第二阶段处理。

## 验证与边界

通过第三阶段 `doctor` 检查当前 Vault、模板、Zotero 数据库与转换工具。MinerU 未配置时，转换步骤保持待处理状态。
回归测试使用临时 Vault、SQLite 固定样例和模拟转换后端；模拟测试不当作真实论文精读成功。7 个技能的规范源码包含在本模块。
