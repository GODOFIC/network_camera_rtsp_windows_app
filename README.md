# udp_cfg_gui

一个基于 **PySide6（Qt for Python）** 的 Windows 上位机工具，用于通过 **UDP** 配置嵌入式设备上的视频流参数。

该工具专门配合设备端的 `udp_cfgd` 守护进程使用，一次性配置视频流的四个关键参数：

- `width`
- `height`
- `bitrate`
- `fps`

配置成功后，设备端会自动重启 RTSP 程序以生效。

---

## 1. 项目背景

在嵌入式视频系统（如 SSC338Q IPC / AI Camera）中，视频流参数通常由配置文件决定，并且只能在程序启动时读取。

设备端通过 `udp_cfgd` 提供了一个 **轻量级 UDP ASCII 协议**，用于在运行时修改配置文件并重启 RTSP 程序。

本项目提供一个 **Windows 图形化上位机**，用于方便地通过 UDP 修改这些参数，无需手工编辑配置文件或 SSH 登录设备。

---

## 2. 功能特性

- ✅ Windows GUI（PySide6 / Qt）
- ✅ UDP 通信（无连接、低依赖）
- ✅ 一次性配置四个参数（width / height / bitrate / fps）
- ✅ 支持读取当前配置（GET）
- ✅ 显示设备返回的 `OK / ERR` 响应
- ✅ 不依赖 scp / ssh / 远程文件系统

> 本工具**刻意保持功能简单**，仅用于参数配置，不包含复杂的设备管理逻辑。

---

## 3. 协议说明（设备端）

设备端需运行 `udp_cfgd`，并监听 UDP 端口（默认 `5600`）。

### 3.1 设置配置（本工具使用）

```text
SET <width> <height> <bitrate> <fps>
