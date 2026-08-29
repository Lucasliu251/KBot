#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 Linux 版 .env 模板。

已存在 .env 时不会覆盖，避免把已配置的 Token 冲掉。

changelog:
- 2026-08-23: 改为 Linux FFmpeg 路径；已有 .env 时直接退出
"""

from __future__ import annotations

import os

ENV_CONTENT = """# KOOK机器人配置
MUSIC_BOT_TOKEN=your_music_bot_token_here

# FFMPEG配置（可留空让程序从 macOS/Linux PATH 自动发现）
FFMPEG_PATH=/usr/bin/ffmpeg
FFPROBE_PATH=/usr/bin/ffprobe

# 下一首歌曲预解码缓存与实时流缓冲
MUSIC_PRELOAD_SECONDS=600
MUSIC_CACHE_TTL=900
MUSIC_CACHE_MAX_SONGS=3
MUSIC_STREAM_BUFFER_SECONDS=45
MUSIC_STARTUP_BUFFER_SECONDS=8
MUSIC_STARTUP_GRACE_SECONDS=2.5
MUSIC_CONTINUATION_LEAD_SECONDS=90
MUSIC_IDLE_DISCONNECT_SECONDS=3

# 内置网易云API（仅监听本机，由 run.py 自动管理）
NETEASE_API_HOST=127.0.0.1
NETEASE_API_PORT=8005
NETEASE_API_MANAGED=True
NETEASE_API_START_TIMEOUT=30
MUSIC_API_BASE=http://127.0.0.1:8005
BACKUP_MUSIC_API=

# Bilibili（匿名公开视频；单视频/分P最长1小时）
BILIBILI_MAX_VIDEO_SECONDS=3600
BILIBILI_EXTRACT_TIMEOUT=30
BILIBILI_COOKIE_FILE=

# Web控制台配置
SECRET_KEY=kook_web_music_secret_key
HOST=0.0.0.0
PORT=8004
DEBUG=False
"""


def create_env_file(target_path: str = ".env") -> str:
    """
    在当前目录写入 Linux 版 .env 模板。

    @param {str} target_path - 要创建的环境文件路径，默认 `.env`
    @returns {str} 实际写入或已存在的文件路径
    @raises {FileExistsError} 目标文件已存在时抛出，防止覆盖现有 Token
    """
    if os.path.exists(target_path):
        raise FileExistsError(f"{target_path} 已存在，拒绝覆盖")

    with open(target_path, "w", encoding="utf-8") as env_file:
        env_file.write(ENV_CONTENT)
    return target_path


if __name__ == "__main__":
    try:
        path = create_env_file()
        print(f".env 文件创建成功: {path}")
    except FileExistsError as exc:
        print(f"跳过: {exc}")
