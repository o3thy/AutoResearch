# Zotero 下载与手动补录

本模块将 RR 保存的 JSON 列表转成 Zotero 中的独立文献条目及 PDF 附件。
目标是用户指定的文献集合（Zotero 左侧文件夹），每篇论文拥有自己的题录和 PDF。
适用于 Zotero 10+ 本地个人库，不需要 zotero.org 云端 API key，也不操作鼠标。

## 安装与授权

```powershell
.\.venv\Scripts\python.exe -m pip install -r zotero/requirements.txt
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py doctor
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py collections
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py authorize --timeout 600
```

Zotero 应保持运行，本地 API 应可用。`authorize` 会请求 Zotero 显示写入授权弹窗，
由用户手动选择“允许”“始终允许”或“拒绝”。程序不会自动点击。
单次授权被一次写入消耗；需要逐次弹窗时，将 `--prompt-writes` 放在子命令前。
选择“始终允许”后可复用授权，授权数据仅放在忽略版本控制的 `zotero/.local/` 中，不打印 key。

使用已存在的集合名称或 key。新建集合须明确执行：

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py create-collection "我的文献集合"
```

## 自动下载

处理前可生成独立的清单，按原列表顺序去重并取前 30 篇：

```powershell
.\.venv\Scripts\python.exe zotero/scripts/prepare_zotero_batch.py rr/artifacts/my-search.json --output zotero/artifacts/my-first30.json --limit 30 --resolve-dois
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py download zotero/artifacts/my-first30.json --collection "我的文献集合"
```

`--resolve-dois` 是显式启用的 Crossref 缺失 DOI 核验：仅接受规范化后完全一致的题名，
并要求作者、期刊或出版年份佐证；短题名要求作者和期刊同时匹配。
多个 DOI 均符合时不自动选择。查询地址、候选、核验依据和选中的元数据保存到新清单，
原 RR 文件不修改。未找到确切匹配不等于论文没有 DOI，仍进入失败清单等待补录。
可以传入多个 JSON 合并，顺序按输入文件及其列表顺序；种子仍需显式 `--include-seed`。

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py download rr/artifacts/my-list.json --collection "我的文献集合"
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py download rr/artifacts/my-list.json --collection "<集合 key>" --download-dir "D:\PaperDownload"
```

支持 RR 的 `related_papers`、其他流程的 `papers` 或直接数组。默认不下载 `seed_papers`，
需要时加 `--include-seed`。同一 DOI 只处理一次。缺失/无效 DOI 进入 CSV，不自动猜配。
`--limit N` 用于小批量试跑；`--download-only` 可先准备 PDF 和失败清单，暂不写入 Zotero。

获取顺序：DOI 原站 → 页面标注的 PDF/全文入口 → Crossref 出版社全文链接。
若 Crossref 登记的链接路径为 `/pdf` 或 `.pdf`，即使其内容类型标为
`unspecified`，也会优先尝试该出版社 PDF 直链。返回内容仍需通过完整 PDF 和身份校验。
人工核实的官方入口可记录为某篇 manifest 记录的 `publisher_pdf_links`：
`[{"url": "https://publisher.example/paper.pdf", "evidence_url": "https://publisher.example/article"}]`。
必须保留发现该链接的页面依据；这不授权使用非原站副本或绕过验证。
可选 `--email YOUR_EMAIL` 使用 Unpaywall 开放获取入口；默认只选出版社位置，
加入 `--allow-repositories` 才允许作者稿/仓库版本。不会绕过登录、验证码或付费限制。
网络中断最多做一次短暂重试，候选地址数量有上限；无法确认身份的 PDF 不归档。

成功文件先保存本地，再作为 stored attachment 复制进 Zotero storage。
程序核对父条目 key、附件路径及 SHA-256，成功后才将状态设为 `attached`。
失败项尚不创建 Zotero 题录；补录时会创建或复用对应文献。

## 本地文件

未指定目录时，所有下载和 CSV 位于本项目 `zotero/download/`：

```text
zotero/download/
  YYYYMMDDHHmm下载失败列表.csv
  download.md
  runs/<run-id>/
    manifest.json
    rr-<record-id>.pdf
  <用户手动下载的 PDF>
```

CSV 使用 UTF-8 BOM，可直接用 Excel 打开，字段为：
`id,title,doi,state,reason,suggested_filename,zotero_item_key,local_pdf`。
命名按北京时间（UTC+8）的实际创建时刻精确到分钟，例如
`202610151115下载失败列表.csv`。同一分钟的新批次若遇同名文件，清单放在
该批次独立的 `runs/<run-id>/` 内，不覆盖旧表。已有清单内容更新时不改名。
完整规范见 [download.md](../download/download.md)。
它包含尚需处理的失败项；已经下载但等待写入的文件记录在 manifest 中，不当作下载失败。
若 `state=attachment_failed` 且 `local_pdf` 已存在，应使用 `attach` 重试归档，不需要重新下载。

`manifest.json` 保存输入来源、DOI、题名、PDF 来源 URL、尝试结果、文件校验值、
Zotero 集合/父条目/附件 key 和当前状态。每篇处理后原子更新，便于继续执行。
运行目录有独立 ID，不覆盖用户文件；用户手动下载的原始 PDF 也会保留。

## 等待与补录

自动流程出现失败时，先查看 CSV 并等待用户完成手动下载。最简单的方法是将 PDF
存到默认 `zotero/download/`，使用 CSV 的 `suggested_filename` 命名。
也可保留原始文件名，由程序检查首页/元数据中的题名；存在歧义时用明确映射。

用户确认文件已准备好后：

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py ingest "<manifest.json 的完整路径>"
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py ingest "<manifest.json 的完整路径>" --pdf-dir "D:\ManualPDF"
```

默认扫描原批次的下载目录（未指定时即项目默认目录），只扫描该目录直接包含的 PDF。
匹配优先级为明确映射、建议文件名/精确题名文件名、PDF 本身的题名证据。
仅凭文件名不足以通过身份校验。扫描件没有可提取身份时，需用户明确提供映射。

映射 CSV 示例：

```csv
doi,file
10.1613/jair.1.12440,reward-machines.pdf
```

缺 DOI 时用失败 CSV 的 `id`：

```csv
id,file
<失败 CSV 中的 id>,manual-paper.pdf
```

```powershell
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py ingest "<manifest.json>" --pdf-dir "D:\ManualPDF" --mapping "D:\ManualPDF\mapping.csv"
```

未匹配、多个候选或文件无效时，原因留在 `manual_import` 报告中。
重复运行会复用父条目并比较附件哈希，不会再次添加相同 PDF。
同一批次的命令应顺序执行；已绑定的 manifest 不允许切换数据库或集合。

## 继续执行

```powershell
# 仅重试下载失败项；缺 DOI 和已成功项会跳过
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py retry "<manifest.json>"
# 原 CSV 正被 Excel 占用时，输出到新文件，不强行关闭程序或覆盖旧表
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py retry "<manifest.json>" --failed-csv "zotero/download/202610151115下载失败列表.csv"
# 只重试已在该批次中的指定 DOI，可多次传入 --doi
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py retry "<manifest.json>" --doi "10.1000/example"
# 将已经取得的 PDF 写入先前指定的集合
.\.venv\Scripts\python.exe zotero/scripts/zotero_workflow.py attach "<manifest.json>"
```

结果 JSON 返回 `manifest`、`failed_csv`、`counts` 和目标集合。
退出码：0 完成；2 尚有失败/待处理项；3 需要 Zotero 写入授权；1 执行错误。
自动完成后仍有失败是正常的部分完成状态，不会标成全部成功。
重试前状态、原因和来源尝试保存在各记录的 `attempt_history`，不会覆盖旧证据。
遇到已识别的浏览器验证页面会明确记录，不会自动执行验证脚本。
