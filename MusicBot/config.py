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

# 下一首歌曲默认预解码 10 分钟。PCM 为 48kHz / 16-bit / stereo，约 110 MiB；
# 每个频道仍然只预载队首下一首，不会把整个歌单同时放进内存。
MUSIC_PRELOAD_SECONDS = max(300, int(os.environ.get("MUSIC_PRELOAD_SECONDS", "600")))
MUSIC_CACHE_TTL = max(600, int(os.environ.get("MUSIC_CACHE_TTL", "900")))
MUSIC_CACHE_MAX_SONGS = max(1, int(os.environ.get("MUSIC_CACHE_MAX_SONGS", "3")))

# 实时播放由独立解码生产者持续向有界缓冲写入，RTP 发送线程只按 20ms 消费。
MUSIC_STREAM_BUFFER_SECONDS = max(15, int(os.environ.get("MUSIC_STREAM_BUFFER_SECONDS", "45")))
MUSIC_STARTUP_BUFFER_SECONDS = max(3, int(os.environ.get("MUSIC_STARTUP_BUFFER_SECONDS", "8")))
MUSIC_STARTUP_GRACE_SECONDS = max(0.5, float(os.environ.get("MUSIC_STARTUP_GRACE_SECONDS", "2.5")))
MUSIC_CONTINUATION_LEAD_SECONDS = max(30, int(os.environ.get("MUSIC_CONTINUATION_LEAD_SECONDS", "90")))
MUSIC_IDLE_DISCONNECT_SECONDS = max(0.0, float(os.environ.get("MUSIC_IDLE_DISCONNECT_SECONDS", "3")))

def resolve_media_binary(env_name: str, command: str, linux_default: str) -> str:
    """优先使用有效的显式路径，否则自动发现 macOS/Linux PATH 中的程序。"""
    configured = os.environ.get(env_name, '').strip()
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return configured
    detected = shutil.which(command)
    return detected or configured or linux_default


FFMPEG_PATH = resolve_media_binary("FFMPEG_PATH", "ffmpeg", "/usr/bin/ffmpeg")
FFPROBE_PATH = resolve_media_binary("FFPROBE_PATH", "ffprobe", "/usr/bin/ffprobe")

# MusicBot 内置的 api-enhanced 仅监听本机；不通过 Nginx 暴露。
NETEASE_API_HOST = os.environ.get("NETEASE_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
NETEASE_API_PORT = int(os.environ.get("NETEASE_API_PORT", "8005"))
if not 1 <= NETEASE_API_PORT <= 65535:
    raise ValueError("NETEASE_API_PORT 必须在 1 到 65535 之间")
netease_api_url_host = f"[{NETEASE_API_HOST}]" if ':' in NETEASE_API_HOST else NETEASE_API_HOST
LOCAL_NETEASE_API_BASE = f"http://{netease_api_url_host}:{NETEASE_API_PORT}"
NETEASE_API_MANAGED = os.environ.get("NETEASE_API_MANAGED", "True").lower() in (
    "true",
    "1",
    "yes",
    "on",
)

# 受管模式下始终强制走本机地址，旧 .env 里的公共 URL 不再参与运行。
# 只有显式关闭 NETEASE_API_MANAGED 后，才允许高级部署指定自有外部实例。
configured_music_api = os.environ.get("MUSIC_API_BASE", "").strip().rstrip("/")
MUSIC_API_BASE = (
    LOCAL_NETEASE_API_BASE
    if NETEASE_API_MANAGED
    else configured_music_api or LOCAL_NETEASE_API_BASE
)

# 默认不再连接任何公共备用实例。高级部署可显式指定另一个自有地址。
configured_backup_api = os.environ.get("BACKUP_MUSIC_API", "").strip().rstrip("/")
BACKUP_MUSIC_API = "" if NETEASE_API_MANAGED else configured_backup_api

# 网易云热歌榜。保留环境变量覆盖，方便兼容 API 更换榜单来源。
NETEASE_HOT_PLAYLIST_ID = os.environ.get("NETEASE_HOT_PLAYLIST_ID", "3778678")

# Web 控制台密钥
SECRET_KEY = os.environ.get("SECRET_KEY", "kook_web_music_secret_key")
# 音乐账号设置后台的管理密钥；未单独配置时沿用 Flask SECRET_KEY。
MUSIC_SETTINGS_TOKEN = os.environ.get("MUSIC_SETTINGS_TOKEN", "").strip() or SECRET_KEY

# KOOK OAuth：用于识别“谁推荐了歌曲”，不与机器人 Token 混用。
KOOK_OAUTH_CLIENT_ID = os.environ.get("KOOK_OAUTH_CLIENT_ID", "").strip()
KOOK_OAUTH_CLIENT_SECRET = os.environ.get("KOOK_OAUTH_CLIENT_SECRET", "").strip()
KOOK_OAUTH_REDIRECT_URI = os.environ.get("KOOK_OAUTH_REDIRECT_URI", "").strip()
KOOK_OAUTH_AUTHORIZE_URL = os.environ.get(
    "KOOK_OAUTH_AUTHORIZE_URL",
    "https://www.kookapp.cn/app/oauth2/authorize",
).strip()
KOOK_OAUTH_SCOPES = "get_user_info get_user_guilds"
MUSIC_SESSION_COOKIE_SECURE = os.environ.get(
    "MUSIC_SESSION_COOKIE_SECURE",
    "False",
).lower() in ("true", "1", "yes", "on")
RECOMMENDATION_DB_PATH = os.environ.get(
    "RECOMMENDATION_DB_PATH",
    os.path.join(os.path.dirname(__file__), "data", "recommendations.sqlite3"),
)
