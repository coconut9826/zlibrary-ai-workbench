# Z-Library AI Workbench 架构与验收标准

## 产品边界

本项目是本地优先的电子书工作台。GitHub 仓库只保存源代码、测试和文档；账号、书籍、转换文件、模型输入输出、AudioSmith 项目和 Ollama 数据都留在用户电脑上。

上游 `zlibrary_tor.py` 继续负责经过验证的 Tor、Z-Library E-API、账号、配额、下载缓存和安全边界。新增功能通过独立的 `zlibrary_workbench` 包组合，不削弱上游对凭据、下载配额、域名和重试的限制。

## 入口

| 入口 | 用途 | 默认网络边界 |
|---|---|---|
| MCP stdio | Codex、Claude Desktop、Cline、Cherry Studio 等 MCP 客户端 | 本机子进程，无监听端口 |
| REST API | 支持 HTTP 工具调用的 AI 与自动化程序 | `127.0.0.1`，禁止默认监听公网 |
| JSON CLI | 脚本、诊断、批处理和服务端的稳定底层接口 | 本机进程 |

MCP 和 REST 返回同一套结构化数据，下载、转换、总结和有声书任务都使用可跟踪的任务状态。

## 核心模块

```text
AI 客户端 / 自动化
        │
  MCP / REST / CLI
        │
  Workbench Service
   ├── ZLibraryAdapter ── Tor E-API / 多账号 / 下载
   ├── LibraryStore ───── SQLite / 文件目录 / 分类 / 命名
   ├── ConversionService ─ PDF → EPUB / 质量报告
   ├── OllamaClient ───── 分类 / 摘要 / Markdown / Mermaid
   └── AudioSmithClient ─ 127.0.0.1:3901 / M4B
```

## 本地数据布局

默认书库根目录可由用户修改，初始建议为 `~/Books/ZLibraryWorkbench`：

```text
library-root/
├── originals/          # 原始下载，不做覆盖式改写
├── converted/          # EPUB 等转换版本
├── audiobooks/         # AudioSmith 导出的 M4B/WAV
├── reports/            # Markdown 总结、Mermaid 导图和 JSON 元数据
├── covers/             # 提取或生成的封面
└── .workbench/
    ├── library.sqlite3
    ├── jobs/
    └── conversion-reports/
```

书库根目录、下载目录和各输出目录均可单独设置。任何由 AI 客户端提交的输出路径都必须在允许的根目录内，除非用户显式启用外部目录。

## 自动命名

默认模板：

```text
{title} - {author} ({year}) [{language}] [{format}]
```

支持占位符：`title`、`author`、`year`、`language`、`format`、`publisher`、`isbn`、`id`。缺失字段自动省略相邻的空括号/空分隔符；文件名会移除路径分隔符、控制字符和 macOS/Windows 不兼容字符，并处理同名冲突。

命名规则只影响发布到书库的文件名，不修改下载缓存的 sidecar 身份与哈希关系。

## PDF 转 EPUB

转换提供两种明确模式：

1. `reflow`：提取文字块和图片，按页面坐标排序，生成可调字号的 EPUB。适合文本型 PDF。
2. `visual`：把每页渲染为高分辨率图片嵌入 EPUB，最大程度保留版面、字体、表格和图片。文件较大，文字不可重排。

`auto` 模式先评估每页文字密度、图片覆盖率和版面复杂度，再为整本书选择 `reflow` 或 `visual`。每次转换输出 JSON 质量报告，至少包含：页数、成功页数、提取字符数、原始图片数、写入图片数、空白页、模式、警告和输出文件哈希。

高准确度的验收定义不是“所有 PDF 零误差”，而是：

- `visual` 模式逐页保留可见内容，页数一致且没有空白丢页；
- `reflow` 模式保留正文顺序与可提取图片，并报告无法可靠识别的页面；
- 扫描件或复杂排版在 `auto` 模式下优先视觉保真；
- 永不覆盖原始 PDF；
- 转换失败不发布半成品 EPUB。

## AudioSmith

AudioSmith 仅连接 `http://127.0.0.1:3901`，不提供公网转发。标准流程：

1. `/health` 检查本地服务；
2. 以 EPUB/TXT/Markdown/DOCX 调用创建有声书项目；
3. 设置旁白、模型、语言、`m4b`、`acx` 响度和书籍元数据；
4. 后台渲染并保存 `job_id`；
5. 查询任务进度；
6. 导出到书库的 `audiobooks/`。

AudioSmith 未运行、模型未下载、许可未接受或任务繁忙时，返回明确状态，不自动修改 AudioSmith 设置，也不下载模型。

## Ollama

默认地址 `http://127.0.0.1:11434`。所有需要大模型的功能首先尝试 Ollama：

- 图书主题和分类；
- 元数据补全建议；
- 分章节摘要和全书综合摘要；
- 关键观点、人物/概念、引用位置；
- Markdown 总结报告；
- Mermaid `mindmap` 导图报告。

大文档采用分块 Map-Reduce：先逐块产生带来源页码/章节的结构化摘要，再合并为最终报告。模型输出必须与书籍记录、模型名、提示词版本和生成时间一起保存。没有用户配置时，不自动回退到云端模型。

## 七项需求验收映射

1. **AI 会话式查询**：MCP 工具可搜索、查看详情、下载、列书架、转换、总结、生成导图和创建有声书；REST 提供等价能力。
2. **格式转换**：PDF → EPUB 有 `auto/reflow/visual`，图片保留并输出质量报告；后续扩展 EPUB/TXT/Markdown/DOCX。
3. **AudioSmith**：创建、渲染、查进度和导出有声书，所有接口限定回环地址。
4. **存放位置**：配置书库、下载、转换、报告和音频目录；启动时验证可写性。
5. **自动命名**：模板预览、字段缺失处理、非法字符清理和同名冲突策略均有单元测试。
6. **书架**：SQLite 索引、自动入库、分类、搜索、格式版本关联、总结报告与 Mermaid 导图。
7. **本地大模型**：Ollama 为默认且唯一自动选择；其他提供方必须由用户显式配置。

## 安全与合规

- 不在 Git、日志、API 响应或提示词中保存账号密码和 session token。
- 多账号只用于用户合法控制的账号，并遵守服务规则；下载链接请求开始后不换账号重试。
- 下载文件和书籍内容均视为不可信输入。
- PDF/EPUB 解析放入受限任务，限制单文件大小、页数、图片像素和解压总量。
- 仅处理用户有权获取和转换的内容，不绕过 DRM 或付费控制。
