"""Bilibili 媒体来源：搜索/元数据走公开 Web API，音频地址由 yt-dlp 本机解析。"""

from __future__ import annotations

import base64
import html
import http.cookiejar
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
import yt_dlp
from yt_dlp.utils import DownloadError


logger = logging.getLogger(__name__)
MODULE_ROOT = Path(__file__).resolve().parent
DATA_ROOT = MODULE_ROOT / 'data' / 'bilibili'
ANONYMOUS_COOKIE_PATH = DATA_ROOT / 'anonymous-cookies.txt'
CONFIGURED_COOKIE_PATH = Path(
    os.environ.get('BILIBILI_COOKIE_FILE', '').strip() or DATA_ROOT / 'cookies.txt'
)
MAX_VIDEO_SECONDS = max(60, int(os.environ.get('BILIBILI_MAX_VIDEO_SECONDS', '3600')))
EXTRACT_TIMEOUT_SECONDS = max(10, int(os.environ.get('BILIBILI_EXTRACT_TIMEOUT', '30')))
SEARCH_PAGE_SIZE = 20
USER_AGENT = os.environ.get(
    'BILIBILI_USER_AGENT',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
)
HEADERS = {
    'User-Agent': USER_AGENT,
    'Referer': 'https://www.bilibili.com/',
    'Accept': 'application/json, text/plain, */*',
}
ALLOWED_HOSTS = {
    'bilibili.com',
    'www.bilibili.com',
    'm.bilibili.com',
    'b23.tv',
    'www.b23.tv',
}

_session_lock = threading.RLock()
_extract_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='bilibili-extract')


class BilibiliError(RuntimeError):
    """Bilibili 搜索、元数据或解析错误。"""


class BilibiliInvalidInput(BilibiliError):
    """不是受支持的 Bilibili URL/BV/AV。"""


class BilibiliDurationExceeded(BilibiliError):
    """单个视频或分P超过一小时。"""


def _strip_html(value: Any) -> str:
    return html.unescape(re.sub(r'<[^>]+>', '', str(value or ''))).strip()


def _cover_url(value: Any) -> str:
    url = str(value or '').strip()
    if url.startswith('//'):
        return f'https:{url}'
    if url.startswith('http://'):
        return f'https://{url[7:]}'
    return url


def _duration_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    parts = str(value or '').strip().split(':')
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0.0
    if len(numbers) == 3:
        return float(numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
    if len(numbers) == 2:
        return float(numbers[0] * 60 + numbers[1])
    return float(numbers[0]) if numbers else 0.0


def _encode_locator(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode_locator(token: str) -> dict[str, Any]:
    try:
        padding = '=' * (-len(str(token)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(f'{token}{padding}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BilibiliInvalidInput('Bilibili 媒体定位符无效') from exc
    if not isinstance(payload, dict) or not payload.get('bvid'):
        raise BilibiliInvalidInput('Bilibili 媒体定位符缺少 BV 号')
    return payload


def _load_cookie_jar(path: Path) -> http.cookiejar.MozillaCookieJar:
    jar = http.cookiejar.MozillaCookieJar(str(path))
    if path.is_file():
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except (OSError, http.cookiejar.LoadError):
            logger.warning('Bilibili Cookie 文件损坏，将重新生成匿名会话: %s', path)
    return jar


def _save_requests_cookies(cookies: requests.cookies.RequestsCookieJar, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    jar = http.cookiejar.MozillaCookieJar(str(path))
    for item in cookies:
        jar.set_cookie(http.cookiejar.Cookie(
            version=0,
            name=item.name,
            value=item.value,
            port=None,
            port_specified=False,
            domain=item.domain or '.bilibili.com',
            domain_specified=True,
            domain_initial_dot=(item.domain or '').startswith('.'),
            path=item.path or '/',
            path_specified=True,
            secure=bool(item.secure),
            expires=item.expires,
            discard=False,
            comment=None,
            comment_url=None,
            rest={'HttpOnly': None} if item.has_nonstandard_attr('HttpOnly') else {},
            rfc2109=False,
        ))
    jar.save(ignore_discard=True, ignore_expires=True)
    os.chmod(path, 0o600)


def _active_cookie_path() -> Path:
    return CONFIGURED_COOKIE_PATH if CONFIGURED_COOKIE_PATH.is_file() else ANONYMOUS_COOKIE_PATH


def _new_session(force_refresh: bool = False) -> requests.Session:
    with _session_lock:
        cookie_path = _active_cookie_path()
        session = requests.Session()
        session.headers.update(HEADERS)
        if cookie_path.is_file() and not force_refresh:
            jar = _load_cookie_jar(cookie_path)
            session.cookies.update(jar)
        if not session.cookies.get('buvid3'):
            response = session.get('https://www.bilibili.com/', timeout=15)
            response.raise_for_status()
            # 只覆盖匿名文件；用户提供的 Cookie 文件始终原样保留。
            if cookie_path == ANONYMOUS_COOKIE_PATH:
                _save_requests_cookies(session.cookies, ANONYMOUS_COOKIE_PATH)
        return session


def _request_json(path: str, params: dict[str, Any], retry: bool = True) -> dict[str, Any]:
    session = _new_session(force_refresh=False)
    response = session.get(f'https://api.bilibili.com{path}', params=params, timeout=15)
    if response.status_code == 412 and retry and _active_cookie_path() == ANONYMOUS_COOKIE_PATH:
        ANONYMOUS_COOKIE_PATH.unlink(missing_ok=True)
        return _request_json(path, params, retry=False)
    response.raise_for_status()
    payload = response.json()
    if int(payload.get('code', -1)) != 0:
        raise BilibiliError(payload.get('message') or f'Bilibili API code={payload.get("code")}')
    return payload


def _canonical_input(value: str) -> str:
    raw = str(value or '').strip()
    bv_match = re.fullmatch(r'(?i)(BV[0-9A-Za-z]+)(?:\?([^\s]+))?', raw)
    if bv_match:
        suffix = f'?{bv_match.group(2)}' if bv_match.group(2) else ''
        return f'https://www.bilibili.com/video/{bv_match.group(1)}{suffix}'
    av_match = re.fullmatch(r'(?i)av(\d+)(?:\?([^\s]+))?', raw)
    if av_match:
        suffix = f'?{av_match.group(2)}' if av_match.group(2) else ''
        return f'https://www.bilibili.com/video/av{av_match.group(1)}{suffix}'
    if not raw.startswith(('http://', 'https://')):
        raise BilibiliInvalidInput('请输入 Bilibili 关键词、BV/AV 号或视频链接')
    parsed = urlparse(raw)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise BilibiliInvalidInput('只允许 bilibili.com 或 b23.tv 链接')
    if parsed.hostname in {'b23.tv', 'www.b23.tv'}:
        response = _new_session().get(raw, timeout=15, allow_redirects=True)
        response.raise_for_status()
        parsed = urlparse(response.url)
        if parsed.hostname not in ALLOWED_HOSTS:
            raise BilibiliInvalidInput('Bilibili 短链接跳转到了不受支持的地址')
        raw = response.url
    return raw


def _is_direct_input(value: str) -> bool:
    raw = str(value or '').strip()
    return bool(
        re.fullmatch(r'(?i)(BV[0-9A-Za-z]+|av\d+)(?:[?\s].*)?', raw)
        or (raw.startswith(('http://', 'https://')) and urlparse(raw).hostname in ALLOWED_HOSTS)
    )


def _track_from_search(item: dict[str, Any]) -> dict[str, Any]:
    duration = _duration_seconds(item.get('duration'))
    bvid = str(item.get('bvid') or '').strip()
    locator = _encode_locator({'bvid': bvid, 'page': 1})
    playable = 0 < duration <= MAX_VIDEO_SECONDS
    return {
        'id': locator,
        'name': _strip_html(item.get('title')) or bvid,
        'ar': [{'name': _strip_html(item.get('author')) or '未知UP主'}],
        'al': {
            'name': f'Bilibili · {_strip_html(item.get("typename")) or "视频"}',
            'picUrl': _cover_url(item.get('pic')),
        },
        'dt': int(duration * 1000),
        'provider': 'bilibili',
        'playable': playable,
        'restriction': '' if playable else '视频总时长超过1小时；多P请粘贴链接选择分P',
        'bvid': bvid,
        'page': 1,
        'part_count': int(item.get('videos') or 1),
        'webpage_url': f'https://www.bilibili.com/video/{bvid}',
    }


def _tracks_from_view(data: dict[str, Any]) -> list[dict[str, Any]]:
    bvid = str(data.get('bvid') or '').strip()
    root_title = _strip_html(data.get('title')) or bvid
    owner = _strip_html((data.get('owner') or {}).get('name')) or '未知UP主'
    cover = _cover_url(data.get('pic'))
    category = _strip_html(data.get('tname')) or '视频'
    pages = data.get('pages') or [{'page': 1, 'part': root_title, 'duration': data.get('duration')}]
    tracks = []
    for page_data in pages:
        page = int(page_data.get('page') or len(tracks) + 1)
        duration = _duration_seconds(page_data.get('duration'))
        part = _strip_html(page_data.get('part'))
        title = root_title if len(pages) == 1 else f'{root_title} · P{page} {part}'
        locator = _encode_locator({
            'bvid': bvid,
            'aid': data.get('aid'),
            'cid': page_data.get('cid'),
            'page': page,
        })
        playable = 0 < duration <= MAX_VIDEO_SECONDS
        tracks.append({
            'id': locator,
            'name': title,
            'ar': [{'name': owner}],
            'al': {'name': f'Bilibili · {category}', 'picUrl': cover},
            'dt': int(duration * 1000),
            'provider': 'bilibili',
            'playable': playable,
            'restriction': '' if playable else '超过1小时，无法加入播放队列',
            'bvid': bvid,
            'page': page,
            'part_count': len(pages),
            'webpage_url': f'https://www.bilibili.com/video/{bvid}?p={page}',
        })
    return tracks


def _view_from_input(value: str) -> tuple[dict[str, Any], int | None]:
    canonical = _canonical_input(value)
    parsed = urlparse(canonical)
    page_value = parse_qs(parsed.query).get('p', [None])[0]
    page = int(page_value) if str(page_value or '').isdigit() else None
    bv_match = re.search(r'(?i)/video/(BV[0-9A-Za-z]+)', parsed.path)
    av_match = re.search(r'(?i)/video/av(\d+)', parsed.path)
    if not bv_match and not av_match:
        raise BilibiliInvalidInput('链接中没有识别到 BV/AV 号')
    params = {'bvid': bv_match.group(1)} if bv_match else {'aid': av_match.group(1)}
    data = (_request_json('/x/web-interface/view', params).get('data') or {})
    return data, page


def search_media(keyword: str, limit: int = 8, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    limit = max(1, min(20, int(limit)))
    offset = max(0, int(offset))
    if _is_direct_input(keyword):
        data, requested_page = _view_from_input(keyword)
        tracks = _tracks_from_view(data)
        if requested_page:
            tracks = [track for track in tracks if track['page'] == requested_page]
        return tracks[offset:offset + limit], len(tracks)

    first_page = offset // SEARCH_PAGE_SIZE + 1
    last_index = offset + limit
    last_page = max(first_page, (max(0, last_index - 1) // SEARCH_PAGE_SIZE) + 1)
    all_items: list[dict[str, Any]] = []
    total = 0
    for page in range(first_page, last_page + 1):
        payload = _request_json('/x/web-interface/search/all/v2', {
            'keyword': keyword,
            'page': page,
            'order': 'totalrank',
            'duration': 0,
        })
        data = payload.get('data') or {}
        total = min(1000, int(data.get('numResults') or 0))
        groups = data.get('result') or []
        videos = next((group.get('data') or [] for group in groups if group.get('result_type') == 'video'), [])
        all_items.extend(videos)

    page_offset = offset - (first_page - 1) * SEARCH_PAGE_SIZE
    selected = all_items[page_offset:page_offset + limit]
    return [_track_from_search(item) for item in selected if item.get('bvid')], total


def get_detail(locator: str) -> dict[str, Any]:
    target = _decode_locator(locator)
    data = (_request_json('/x/web-interface/view', {'bvid': target['bvid']}).get('data') or {})
    tracks = _tracks_from_view(data)
    page = int(target.get('page') or 1)
    return next((track for track in tracks if track['page'] == page), tracks[0] if tracks else {})


def _extract_audio(locator: str) -> dict[str, Any]:
    _new_session()
    target = _decode_locator(locator)
    bvid = str(target['bvid'])
    page = max(1, int(target.get('page') or 1))
    view_data = (_request_json('/x/web-interface/view', {'bvid': bvid}).get('data') or {})
    page_data = next(
        (item for item in (view_data.get('pages') or []) if int(item.get('page') or 0) == page),
        None,
    )
    declared_duration = _duration_seconds(
        (page_data or {}).get('duration', view_data.get('duration'))
    )
    if declared_duration > MAX_VIDEO_SECONDS:
        raise BilibiliDurationExceeded('Bilibili 单个视频或分P最长只能播放1小时')
    query = urlencode({'p': page}) if page > 1 else ''
    page_url = urlunparse(('https', 'www.bilibili.com', f'/video/{bvid}', '', query, ''))
    try:
        playurl_data = (_request_json('/x/player/playurl', {
            'bvid': bvid,
            'cid': (page_data or {}).get('cid') or target.get('cid'),
            'qn': 80,
            'fnval': 16,
            'fnver': 0,
            'fourk': 1,
        }).get('data') or {})
    except (BilibiliError, requests.RequestException) as exc:
        logger.warning('Bilibili playurl接口不可用，尝试yt-dlp兜底: %s', exc)
        playurl_data = {}
    audio_streams = (playurl_data.get('dash') or {}).get('audio') or []

    def stream_url(item: dict[str, Any]) -> str:
        backups = item.get('backupUrl') or item.get('backup_url') or []
        backup = backups[0] if isinstance(backups, list) and backups else backups
        return str(
            item.get('baseUrl')
            or item.get('base_url')
            or backup
        ).strip()

    # 优先选择兼容性最好的AAC音轨，再按带宽选择；避免Dolby等特殊轨道无法解码。
    selected_stream = max(
        audio_streams,
        key=lambda item: (
            str(item.get('codecs') or '').lower().startswith('mp4a'),
            int(item.get('bandwidth') or 0),
        ),
        default={},
    )
    audio_url = stream_url(selected_stream)
    if not audio_url:
        durl = playurl_data.get('durl') or []
        audio_url = str((durl[0] if durl else {}).get('url') or '').strip()

    # 公开playurl接口是主路径；仅在特殊视频没有返回音轨时才退回yt-dlp。
    fallback_info: dict[str, Any] = {}
    if not audio_url:
        options = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
            'format': 'bestaudio[acodec!=none]/bestaudio/best[acodec!=none]',
            'socket_timeout': 15,
            'cookiefile': str(_active_cookie_path()),
            'http_headers': {**HEADERS, 'Referer': page_url},
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            fallback_info = downloader.extract_info(page_url, download=False)
        if fallback_info.get('is_live') or fallback_info.get('live_status') == 'is_live':
            raise BilibiliError('第一版暂不支持 Bilibili 直播')
        audio_url = str(fallback_info.get('url') or '').strip()

    duration = declared_duration or _duration_seconds(fallback_info.get('duration'))
    if duration > MAX_VIDEO_SECONDS:
        raise BilibiliDurationExceeded('Bilibili 单个视频或分P最长只能播放1小时')
    if not audio_url.startswith(('http://', 'https://')):
        raise BilibiliError('Bilibili 没有返回可播放音频地址')
    headers = {**HEADERS, 'Referer': page_url}
    headers.update({
        str(key): str(value)
        for key, value in (fallback_info.get('http_headers') or {}).items()
        if value is not None
    })
    deadline_value = parse_qs(urlparse(audio_url).query).get('deadline', ['0'])[0]
    try:
        expires_at = float(deadline_value)
    except (TypeError, ValueError):
        expires_at = 0.0
    if expires_at <= time.time() + 60:
        expires_at = time.time() + 240
    return {
        'url': audio_url,
        'expires_at': expires_at,
        'duration': duration,
        'title': _strip_html(view_data.get('title') or fallback_info.get('title')),
        'artist': _strip_html((view_data.get('owner') or {}).get('name') or fallback_info.get('uploader')) or '未知UP主',
        'cover': _cover_url(view_data.get('pic') or fallback_info.get('thumbnail')),
        'webpage_url': page_url,
        'headers': headers,
        'bvid': bvid,
        'page': page,
    }


def resolve_audio(locator: str) -> dict[str, Any]:
    future = _extract_pool.submit(_extract_audio, str(locator))
    try:
        return future.result(timeout=EXTRACT_TIMEOUT_SECONDS)
    except FutureTimeoutError as exc:
        raise BilibiliError('Bilibili 音频解析超时，请稍后重试') from exc
    except DownloadError as exc:
        raise BilibiliError(f'Bilibili 音频解析失败：{exc}') from exc
    except requests.RequestException as exc:
        raise BilibiliError(f'Bilibili 接口请求失败：{exc}') from exc


def auth_status() -> dict[str, Any]:
    try:
        version = yt_dlp.version.__version__
    except Exception:
        version = ''
    return {
        'available': True,
        'authenticated': CONFIGURED_COOKIE_PATH.is_file(),
        'source': 'local' if CONFIGURED_COOKIE_PATH.is_file() else 'none',
        'version': version,
        'max_duration': MAX_VIDEO_SECONDS,
        'error': '',
    }
