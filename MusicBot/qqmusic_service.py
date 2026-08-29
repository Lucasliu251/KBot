"""QQ 音乐能力适配层。

本模块把 vendored QQMusicApi 的异步模型转换为 MusicBot 现有的网易云兼容
数据结构。上层只需要传入 provider=qqmusic，就可以复用同一套搜索、发现、
歌曲详情、歌词和播放队列界面。
"""

from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Coroutine, TypeVar
from urllib.parse import urljoin


logger = logging.getLogger(__name__)
MODULE_ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = MODULE_ROOT / "vendor" / "QQMusicApi"
DATA_ROOT = MODULE_ROOT / "data" / "qqmusic"
CREDENTIAL_PATH = Path(os.environ.get("QQ_MUSIC_CREDENTIAL_FILE", "").strip() or DATA_ROOT / "credential.json")
DEVICE_PATH = Path(os.environ.get("QQ_MUSIC_DEVICE_FILE", "").strip() or DATA_ROOT / "device.json")
TOP_ID = int(os.environ.get("QQ_MUSIC_TOP_ID", "26"))
DEFAULT_QUALITY = os.environ.get("QQ_MUSIC_QUALITY", "mp3_320").strip().lower()

if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))

_IMPORT_ERROR: Exception | None = None
try:
    from qqmusic_api import Client, Credential
    from qqmusic_api.core.exceptions import CredentialExpiredError
    from qqmusic_api.models.login import QR, QRCodeLoginEvents, QRLoginType
    from qqmusic_api.modules.search import SearchType
    from qqmusic_api.modules.song import SongFileInfo, SongFileType
except Exception as exc:  # pragma: no cover - exercised by deployment diagnostics
    _IMPORT_ERROR = exc
    Client = Credential = None  # type: ignore[assignment,misc]
    CredentialExpiredError = Exception  # type: ignore[assignment,misc]
    QR = QRCodeLoginEvents = QRLoginType = None  # type: ignore[assignment,misc]
    SearchType = SongFileInfo = SongFileType = None  # type: ignore[assignment,misc]


T = TypeVar("T")
_credential_lock = threading.RLock()


class QQMusicError(RuntimeError):
    """QQ 音乐上游或配置错误。"""


class QQMusicUnavailable(QQMusicError):
    """QQMusicApi 或其运行依赖尚不可用。"""


class QQMusicAuthRequired(QQMusicError):
    """操作需要 QQ 音乐登录态。"""


class QQMusicPermissionError(QQMusicError):
    """当前账号没有目标音频的完整播放权限。"""


async def _await_request(request):
    """把 QQMusicApi 的可等待请求描述符包装成可被 asyncio.gather 接受的协程。"""
    return await request


def _ensure_available() -> None:
    if _IMPORT_ERROR is not None:
        raise QQMusicUnavailable(f"QQ 音乐组件加载失败：{_IMPORT_ERROR}")


def run_async(coroutine: Coroutine[Any, Any, T]) -> T:
    """从 Flask 同步路由安全执行单次异步 QQMusicApi 调用。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result: list[T | None] = [None]
    error: list[BaseException | None] = [None]

    def runner() -> None:
        try:
            result[0] = asyncio.run(coroutine)
        except BaseException as exc:  # pragma: no cover - defensive fallback
            error[0] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=30)
    if thread.is_alive():
        raise QQMusicError("QQ 音乐请求超时")
    if error[0] is not None:
        raise error[0]
    return result[0]  # type: ignore[return-value]


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).strip()


def _credential_from_environment():
    _ensure_available()
    raw_json = os.environ.get("QQ_MUSIC_CREDENTIAL_JSON", "").strip()
    if raw_json:
        try:
            return Credential.model_validate_json(raw_json)
        except ValueError as exc:
            raise QQMusicError("QQ_MUSIC_CREDENTIAL_JSON 格式无效") from exc

    musicid = os.environ.get("QQ_MUSIC_MUSICID", "").strip()
    musickey = os.environ.get("QQ_MUSIC_MUSICKEY", "").strip()
    if not musicid or not musickey:
        return None
    try:
        return Credential(
            musicid=int(musicid),
            str_musicid=musicid,
            musickey=musickey,
            refresh_key=os.environ.get("QQ_MUSIC_REFRESH_KEY", ""),
            refresh_token=os.environ.get("QQ_MUSIC_REFRESH_TOKEN", ""),
            access_token=os.environ.get("QQ_MUSIC_ACCESS_TOKEN", ""),
            openid=os.environ.get("QQ_MUSIC_OPENID", ""),
        )
    except ValueError as exc:
        raise QQMusicError("QQ_MUSIC_MUSICID 必须是数字") from exc


def load_credential():
    """环境变量优先，其次读取网页扫码后保存在本机的凭证。"""
    _ensure_available()
    environment_credential = _credential_from_environment()
    if environment_credential is not None:
        return environment_credential
    with _credential_lock:
        if not CREDENTIAL_PATH.exists():
            return None
        try:
            credential = Credential.model_validate_json(CREDENTIAL_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("QQ 音乐凭证读取失败: %s", exc)
            return None
    return credential if credential.musicid and credential.musickey else None


def save_credential(credential) -> None:
    """原子保存扫码或刷新得到的完整凭证，文件权限限制为当前用户。"""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    CREDENTIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = CREDENTIAL_PATH.with_suffix(".tmp")
    with _credential_lock:
        temporary_path.write_text(credential.model_dump_json(by_alias=True), encoding="utf-8")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, CREDENTIAL_PATH)


def clear_credential() -> bool:
    """删除网页扫码保存的本地凭证；环境变量凭证不会被改动。"""
    if _credential_from_environment() is not None:
        return False
    with _credential_lock:
        try:
            CREDENTIAL_PATH.unlink(missing_ok=True)
        except OSError as exc:
            raise QQMusicError(f"无法删除 QQ 音乐登录信息：{exc}") from exc
    return True


def auth_status() -> dict[str, Any]:
    """返回不包含密钥的 QQ 音乐登录状态。"""
    if _IMPORT_ERROR is not None:
        return {"available": False, "authenticated": False, "error": str(_IMPORT_ERROR)}
    try:
        environment_credential = _credential_from_environment()
        credential = environment_credential or load_credential()
    except QQMusicError as exc:
        return {"available": True, "authenticated": False, "error": str(exc)}
    if credential is None:
        return {"available": True, "authenticated": False}
    musicid = str(credential.str_musicid or credential.musicid)
    masked = musicid if len(musicid) <= 4 else f"{musicid[:2]}****{musicid[-2:]}"
    locally_expired = bool(
        credential.musickey_create_time > 0
        and credential.key_expires_in > 0
        and credential.is_expired()
    )
    return {
        "available": True,
        "authenticated": not locally_expired,
        "account": masked,
        "expired": locally_expired,
        "login_source": "environment" if environment_credential is not None else "local",
    }


async def _refresh_if_needed(credential):
    if credential is None:
        return None
    needs_refresh = bool(
        credential.musickey_create_time > 0
        and credential.key_expires_in > 0
        and credential.is_expired()
    )
    if not needs_refresh:
        return credential
    if not credential.refresh_key and not credential.refresh_token:
        raise QQMusicAuthRequired("QQ 音乐登录已过期，请重新扫码登录")
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(credential=credential, device_path=str(DEVICE_PATH)) as client:
        refreshed = await client.login.refresh_credential(credential)
    if _credential_from_environment() is None:
        save_credential(refreshed)
    return refreshed


def _normalize_song(song: Any) -> dict[str, Any]:
    singers = getattr(song, "singer", []) or []
    album = getattr(song, "album", None)
    cover = ""
    try:
        cover = song.cover_url(500)
    except (AttributeError, ValueError):
        pass
    return {
        "id": str(getattr(song, "mid", "") or getattr(song, "id", "")),
        "qq_id": int(getattr(song, "id", 0) or 0),
        "name": _clean_text(getattr(song, "name", "") or getattr(song, "title", "")),
        "ar": [{"name": _clean_text(getattr(singer, "name", ""))} for singer in singers],
        "al": {
            "name": _clean_text(getattr(album, "name", "") or getattr(album, "title", "")),
            "picUrl": cover,
        },
        "dt": int(getattr(song, "interval", 0) or 0) * 1000,
        "provider": "qqmusic",
        "song_type": int(getattr(song, "type", 0) or 0),
        "media_mid": str(getattr(getattr(song, "file", None), "media_mid", "") or ""),
    }


async def _search(keyword: str, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    _ensure_available()
    credential = await _refresh_if_needed(load_credential())
    page = offset // limit + 1
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(credential=credential, device_path=str(DEVICE_PATH)) as client:
        result = await client.search.search_by_type(
            keyword,
            search_type=SearchType.SONG,
            num=limit,
            page=page,
            highlight=False,
        )
    return [_normalize_song(song) for song in result.song], int(result.total_num or 0)


def search_music_page(keyword: str, limit: int = 8, offset: int = 0):
    limit = max(1, min(20, int(limit)))
    offset = max(0, int(offset))
    return run_async(_search(keyword, limit, offset))


async def _discover(limit: int, offset: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    _ensure_available()
    credential = await _refresh_if_needed(load_credential())
    page = offset // limit + 1
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(credential=credential, device_path=str(DEVICE_PATH)) as client:
        top_request = client.top.get_detail(top_id=TOP_ID, num=limit, page=page, tag=False)
        if offset == 0:
            top_result, hot_result = await asyncio.gather(
                _await_request(top_request),
                _await_request(client.search.get_hotkey()),
            )
            hot_searches = [
                {
                    "keyword": _clean_text(item.query or item.title),
                    "score": item.score,
                    "content": _clean_text(item.description),
                    "icon_type": 0,
                }
                for item in hot_result.vec_hotkey
                if _clean_text(item.query or item.title)
            ][:12]
        else:
            top_result = await top_request
            hot_searches = []
    songs = [_normalize_song(song) for song in top_result.songs]
    total = int(top_result.info.total_num or 0)
    return hot_searches, songs, offset + len(songs) < total


def discover(limit: int = 8, offset: int = 0):
    limit = max(1, min(20, int(limit)))
    offset = max(0, int(offset))
    return run_async(_discover(limit, offset))


async def _song_detail(song_id: str) -> dict[str, Any]:
    _ensure_available()
    credential = await _refresh_if_needed(load_credential())
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(credential=credential, device_path=str(DEVICE_PATH)) as client:
        result = await client.song.get_detail(song_id)
    return _normalize_song(result.track)


def get_song_detail(song_id: str) -> dict[str, Any]:
    return run_async(_song_detail(str(song_id)))


async def _song_lyrics_data(song_id: str) -> dict[str, str]:
    _ensure_available()
    credential = await _refresh_if_needed(load_credential())
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(credential=credential, device_path=str(DEVICE_PATH)) as client:
        try:
            result = await client.lyric.get_lyric(song_id, qrc=False, trans=True)
        except Exception as exc:
            # 个别歌曲的翻译 CGI 会返回 24001；翻译属于增强能力，不能因此
            # 连原文歌词也丢失，所以自动回退到普通歌词请求。
            logger.info("QQ 音乐翻译歌词不可用，回退原文: %s", exc)
            result = await client.lyric.get_lyric(song_id, qrc=False, trans=False)
    return {
        'lyric': result.lyric or '',
        'translated_lyric': result.trans or '',
        'romanized_lyric': result.roma or '',
    }


def get_song_lyrics_data(song_id: str) -> dict[str, str]:
    try:
        return run_async(_song_lyrics_data(str(song_id)))
    except QQMusicError:
        raise
    except Exception as exc:
        raise QQMusicError(f"QQ 音乐歌词请求失败：{exc}") from exc


def get_song_lyrics(song_id: str) -> str:
    return get_song_lyrics_data(song_id)['lyric']


def _quality_order() -> list[Any]:
    quality_map = {
        "flac": SongFileType.FLAC,
        "mp3_320": SongFileType.MP3_320,
        "mp3_128": SongFileType.MP3_128,
    }
    preferred = quality_map.get(DEFAULT_QUALITY, SongFileType.MP3_320)
    return list(dict.fromkeys([preferred, SongFileType.MP3_320, SongFileType.MP3_128]))


async def _resolve_song_url(song_id: str) -> dict[str, Any]:
    _ensure_available()
    credential = await _refresh_if_needed(load_credential())
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async def request_with_credential(active_credential):
        async with Client(credential=active_credential, device_path=str(DEVICE_PATH)) as client:
            detail = await client.song.get_detail(song_id)
            track = detail.track
            file_info = [
                SongFileInfo(
                    mid=track.mid,
                    file_type=quality,
                    song_type=track.type,
                    media_mid=track.file.media_mid or None,
                )
                for quality in _quality_order()
            ]
            urls, dispatch = await asyncio.gather(
                _await_request(client.song.get_song_urls(file_info)),
                _await_request(client.song.get_cdn_dispatch()),
            )
            return track, urls, dispatch

    try:
        track, urls, dispatch = await request_with_credential(credential)
    except CredentialExpiredError:
        if credential is None or (not credential.refresh_key and not credential.refresh_token):
            raise QQMusicAuthRequired("QQ 音乐登录已过期，请重新扫码登录") from None
        async with Client(credential=credential, device_path=str(DEVICE_PATH)) as refresh_client:
            credential = await refresh_client.login.refresh_credential(credential)
        if _credential_from_environment() is None:
            save_credential(credential)
        track, urls, dispatch = await request_with_credential(credential)

    cdn = next((item for item in dispatch.sip if item), "https://isure.stream.qqmusic.qq.com/")
    result_codes: list[int] = []
    for quality, info in zip(_quality_order(), urls.data, strict=False):
        result_codes.append(int(info.result))
        if info.result == 0 and info.purl:
            return {
                "url": urljoin(cdn.rstrip("/") + "/", info.purl.lstrip("/")),
                "quality": quality.name.lower(),
                "expires_in": int(urls.expiration or dispatch.expiration or 0),
                "song": _normalize_song(track),
            }

    if 104003 in result_codes:
        if credential is None:
            raise QQMusicAuthRequired("请先扫码登录 QQ 音乐会员账号后再播放完整歌曲")
        raise QQMusicPermissionError("当前 QQ 音乐账号没有这首歌的完整播放权限")
    if 104013 in result_codes:
        raise QQMusicPermissionError("QQ 音乐限制了当前设备播放，请在官方客户端检查设备状态")
    raise QQMusicError(f"QQ 音乐未返回可播放地址（result={result_codes or 'empty'}）")


def resolve_song_url(song_id: str) -> dict[str, Any]:
    return run_async(_resolve_song_url(str(song_id)))


async def _create_login_qrcode(login_type: str) -> dict[str, Any]:
    _ensure_available()
    type_map = {"qq": QRLoginType.QQ, "wx": QRLoginType.WX}
    selected_type = type_map.get(login_type)
    if selected_type is None:
        raise QQMusicError("只支持 QQ 或微信扫码登录")
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(device_path=str(DEVICE_PATH)) as client:
        qrcode = await client.login.get_qrcode(selected_type)
    return {
        "login_type": login_type,
        "identifier": qrcode.identifier,
        "image": f"data:{qrcode.mimetype or 'image/png'};base64,{base64.b64encode(qrcode.data).decode('ascii')}",
    }


def create_login_qrcode(login_type: str = "qq") -> dict[str, Any]:
    return run_async(_create_login_qrcode(login_type))


async def _check_login_qrcode(identifier: str, login_type: str) -> dict[str, Any]:
    _ensure_available()
    type_map = {"qq": QRLoginType.QQ, "wx": QRLoginType.WX}
    selected_type = type_map.get(login_type)
    if selected_type is None or not identifier:
        raise QQMusicError("登录二维码参数无效")
    qrcode = QR(data=b"", qr_type=selected_type, mimetype="image/png", identifier=identifier)
    DEVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with Client(device_path=str(DEVICE_PATH)) as client:
        result = await client.login.check_qrcode(qrcode)
    status = result.event.name.lower()
    response: dict[str, Any] = {"status": status}
    if result.event == QRCodeLoginEvents.DONE and result.credential is not None:
        save_credential(result.credential)
        response["auth"] = auth_status()
    return response


def check_login_qrcode(identifier: str, login_type: str = "qq") -> dict[str, Any]:
    return run_async(_check_login_qrcode(identifier, login_type))
