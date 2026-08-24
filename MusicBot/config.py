"""
KOOK 音乐机器人服务端配置。

从环境变量读取 Token、FFmpeg 路径、音乐 API 与 Web 监听参数；
未设置时使用 Linux 系统默认路径。

changelog:
- 2026-08-23: 移除 Windows ffmpeg.exe 默认路径，改为 Linux 系统路径，
  并从环境变量读取 HOST/PORT/DEBUG
"""

import os
import shutil

# 基本配置：优先读 .env，便于同一份代码在不同机器上部署
DEBUG = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8004"))

# MusicBot 独立使用的 KOOK 机器人 Token。
# 保留 BOT_TOKEN 回退仅用于兼容旧部署；其它 KBot 功能不会读取本配置文件。
MUSIC_BOT_TOKEN = os.environ.get("MUSIC_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
BOT_TOKEN = MUSIC_BOT_TOKEN

# 下一首歌曲至少预解码 5 分钟。PCM 为 48kHz / 16-bit / stereo，约 55 MiB。
MUSIC_PRELOAD_SECONDS = max(300, int(os.environ.get("MUSIC_PRELOAD_SECONDS", "300")))
MUSIC_CACHE_TTL = max(600, int(os.environ.get("MUSIC_CACHE_TTL", "900")))
MUSIC_CACHE_MAX_SONGS = max(1, int(os.environ.get("MUSIC_CACHE_MAX_SONGS", "3")))

def resolve_media_binary(env_name: str, command: str, linux_default: str) -> str:
    """优先使用有效的显式路径，否则自动发现 macOS/Linux PATH 中的程序。"""
    configured = os.environ.get(env_name, '').strip()
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    detected = shutil.which(command)
    return detected or configured or linux_default


FFMPEG_PATH = resolve_media_binary("FFMPEG_PATH", "ffmpeg", "/usr/bin/ffmpeg")
FFPROBE_PATH = resolve_media_binary("FFPROBE_PATH", "ffprobe", "/usr/bin/ffprobe")

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

# 网易云热歌榜。保留环境变量覆盖，方便兼容 API 更换榜单来源。
NETEASE_HOT_PLAYLIST_ID = os.environ.get("NETEASE_HOT_PLAYLIST_ID", "3778678")

# Web 控制台密钥
SECRET_KEY = os.environ.get("SECRET_KEY", "kook_web_music_secret_key")
