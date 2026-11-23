# macOS 应用

## 安装和分享

从 [GitHub 发布页](https://github.com/coconut9826/zlibrary-ai-workbench/releases/tag/v0.3.0-dev1) 下载 `ZLibrary-Workbench-macOS-arm64.zip`，解压后把“ZLibrary Workbench.app”拖到“应用程序”文件夹，双击启动。此包适用于 Apple Silicon、macOS 13 或更高版本。应用包含 Python 运行时、工作台代码和格式转换依赖，收件人无需另装 Python。

当前应用使用临时签名，尚未使用 Apple Developer ID 公证。其他电脑首次打开时可能出现系统安全提示。也可以从源码构建一份本机应用。请仅从信任的仓库和发布页面获取应用包。

应用窗口使用系统 WebKit；每次启动时在随机的 `127.0.0.1` 端口运行内置服务，退出窗口后停止该进程。它可以和 `zlibrary-workbench serve-gui` 的默认 `8765` 端口同时运行。书籍、账号会话、密码钥匙串、配置和模型数据都保留在使用者电脑上，分享包不包含这些数据。

搜索和下载需要本机 Tor SOCKS5 监听 `127.0.0.1:9050`，可在应用的“搜索与下载”页检查连接。Ollama 和 AudioSmith 分别是可选的本地服务，默认地址为 `127.0.0.1:11434` 和 `127.0.0.1:3901`。应用包不包含 Tor、Ollama 模型或 AudioSmith。

## 从源码构建

在 Apple Silicon Mac 上安装 Xcode 与 `uv`，然后运行：

```bash
bash packaging/macos/build.sh
```

构建脚本把独立的 CPython 3.14.9 运行时和 `uv.lock` 锁定的 `[desktop]` 依赖放入 `dist/ZLibrary Workbench.app`，再生成 `dist/ZLibrary-Workbench-macOS-arm64.zip`。输出目录由脚本第一个参数指定，`PYTHON_RUNTIME` 可指向已有的 CPython 3.14 可执行文件。脚本只使用项目代码和公开依赖，构建时不复制本机书库、配置或钥匙串。

发布前可检查：

```bash
codesign --verify --deep --strict "dist/ZLibrary Workbench.app"
PYTHONDONTWRITEBYTECODE=1 \
PYTHONHOME="$PWD/dist/ZLibrary Workbench.app/Contents/Resources/python" \
"dist/ZLibrary Workbench.app/Contents/Resources/python/bin/python3.14" \
  -c 'from zlibrary_workbench.api import create_app; from zlibrary_workbench.config import AppConfig; create_app(AppConfig())'
```
