# 实施计划

## 阶段 1：本地核心与配置

- 配置文件、路径边界和目录验证
- 自动命名规则与预览
- SQLite 书架、格式版本和任务记录
- 复用 `zlibrary_tor.py` 的搜索、账号与下载

## 阶段 2：转换

- PDF 检测与 `auto/reflow/visual` 模式
- 图片、封面、章节和 EPUB 元数据
- 原子发布与转换质量报告
- 文本/扫描件/图文混排测试样本

## 阶段 3：Ollama 分析

- 健康检查、模型发现、结构化 JSON 输出
- PDF/EPUB 文本抽取与有来源的分块
- 分类、摘要、Markdown 报告和 Mermaid 导图
- 中断恢复、缓存和提示词版本

## 阶段 4：AudioSmith

- 本地健康检查
- 创建有声书、渲染任务、任务查询和导出
- 书籍元数据、封面、旁白、M4B 与 ACX 响度

## 阶段 5：AI 工具接入

- MCP stdio 工具与资源
- REST API 与 OpenAPI 文档
- Codex、Claude Desktop、Cline 示例配置
- 权限提示、输出目录限制和审计日志

## 阶段 6：云端验收后安装

- GitHub CI：Python 3.11–3.14、macOS/Linux/Windows
- 离线单元测试与模拟服务集成测试
- 真实环境只做经用户授权的 doctor、Ollama、AudioSmith 测试
- 用户确认版本后，才安装到本机 Skill/CLI 目录
