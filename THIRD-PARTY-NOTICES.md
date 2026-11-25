# 第三方组件和发布核对

| 组件 | 来源与随包声明 |
| --- | --- |
| MFAAvalonia | [上游源码](https://github.com/MaaXYZ/MFAAvalonia)。使用官方运行文件构建的候选包在 `MFA-SOURCE.md` 记录了具体源码提交、官方发行文件和校验值。许可文本见 `licenses/LICENSE-MFA-GPL-3.0`。来自工作目录的旧版 Windows EXE/DLL 仍需单独确认对应源码。 |
| MaaFramework | [上游源码](https://github.com/MaaXYZ/MaaFramework)。项目已有 LGPL 文本见 `licenses/LICENSE-MaaFramework-LGPL-3.0`，Python 包自带的许可证和元数据保存在 `agent/vendor`。分发前核对桌面原生 DLL 对应的版本和声明。 |
| Python、NumPy 与 OpenCV | 解释器许可见 `portable/python/LICENSE.txt`。NumPy、OpenCV 和其他 Python 依赖的版本及声明随 `agent/vendor` 下各包的 `dist-info` 提供。 |
| .NET | 随附 `portable/dotnet/LICENSE.txt` 和 `portable/dotnet/ThirdPartyNotices.txt`。 |

MaaZjcs 是《杖剑传说》的非官方日常操作辅助工具，通过识别模拟器画面和模拟点击执行用户勾选的任务。[雷霆通行证服务条款](https://www.leiting.com/common/protocol.html) 第 6.3 条涉及多类第三方软件，具体适用性取决于实际功能和用途。

随包公开提供的项目图标、界面识别模板和联动图片，应按各自来源核对可分发依据。

正式收录前应准备可访问的源码仓库和发行页，并与 [Mirror 酱](https://github.com/MirrorChyan/docs) 确认 `res_id`、下载上传流程和项目展示资料。候选包用于验收。
