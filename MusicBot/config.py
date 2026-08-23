"""
KOOK 音乐机器人服务端配置。

从环境变量读取 Token、FFmpeg 路径、音乐 API 与 Web 监听参数；
未设置时使用 Linux 系统默认路径。

changelog:
- 2026-08-23: 移除 Windows ffmpeg.exe 默认路径，改为 Linux 系统路径，
  并从环境变量读取 HOST/PORT/DEBUG
"""

import os

# 基本配置：优先读 .env，便于同一份代码在不同机器上部署
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8004"))

# KOOK 机器人 Token，必须通过环境变量或 .env 注入
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Linux 系统 FFmpeg / FFprobe，可用环境变量覆盖
FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "/usr/bin/ffmpeg")
FFPROBE_PATH = os.environ.get("FFPROBE_PATH", "/usr/bin/ffprobe")

# 网易云兼容音乐 API
MUSIC_API_BASE = os.environ.get(
    "MUSIC_API_BASE",
    "https://1304404172-f3na0r58ws.ap-beijing.tencentscf.com",
)

# 备用 API 地址
BACKUP_MUSIC_API = os.environ.get(
    "BACKUP_MUSIC_API",
    "https://api.music.liuzhijin.cn",
)

# Web 控制台密钥
SECRET_KEY = os.environ.get("SECRET_KEY", "kook_web_music_secret_key")
