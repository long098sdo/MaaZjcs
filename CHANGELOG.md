# 发布与维护记录

## v0.1.0-rc.4 · 2026-11-27 · Windows x64 测试版

- 启动时后台检查 GitHub Releases。发现带有 Windows x64 ZIP 的新版时，MFA 标题栏显示版本提示，点击后可打开下载页。
- 保留独立的「检查更新.cmd」。确认下载会转到 GitHub，下载与解压由用户选择。
- 使用官方 MFAAvalonia v2.16.6。对应源码提交为 `8646e0c34fa1fc52cd32505bc2020bae7da9d76a`，发行页同时提供源码存档。
- 已验证模拟新版写入标题栏、标题按钮回调打开 Windows 确认框，以及确认后选择正确的 GitHub 版本地址。便携包默认关闭任务、定时器和补跑。

### 发行文件校验

| 文件 | SHA-256 |
| --- | --- |
| `MaaZjcs-v0.1.0-rc.4-win-x64.zip` | `84fEc9525e236eebfe4279b969fb3ef10a3c7e1a9362875a7c0f6842a28d1ae0` |
| `MFAAvalonia-v2.16.6-corresponding-source.zip` | `0f65629262cbff4cea1550f3c4d800ce78cadbd1d25608e20e0e4615fa0fb787` |

后续发版保持 `MaaZjcs-v版本号-win-x64.zip` 命名，并让 `interface.json` 内版本、Release 标签和附件名对应。测试版标为 Pre-release。先上传并核对附件校验值，再公开 Release。维护时保留工作目录、配置和源码存档，清理仅针对发行目录中的旧构建。
