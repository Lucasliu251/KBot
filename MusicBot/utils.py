import requests
import logging
import json
import os
import threading
import time
from pathlib import Path
from config import MUSIC_API_BASE, BACKUP_MUSIC_API, NETEASE_HOT_PLAYLIST_ID

logger = logging.getLogger(__name__)

COOKIE_DIR = Path(__file__).resolve().parent / "Cookie"
COOKIE_TXT_PATH = COOKIE_DIR / "cookie.txt"
COOKIE_JSON_PATH = COOKIE_DIR / "cookies.json"
_cookie_lock = threading.RLock()


class MusicAPIError(RuntimeError):
    """网易云兼容 API 主备服务均不可用。"""


def configured_api_bases():
    """返回去重后的已配置 API；默认只有本机 api-enhanced。"""
    result = []
    for api_base in (MUSIC_API_BASE, BACKUP_MUSIC_API):
        normalized = str(api_base or '').strip().rstrip('/')
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def parse_cookie_header(cookie_header):
    """Parse a browser Cookie header without ever returning it to the client."""
    cookies = {}
    for part in str(cookie_header or '').split(';'):
        item = part.strip()
        if not item or '=' not in item:
            continue
        key, value = item.split('=', 1)
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def load_cookie_header():
    environment_cookie = os.environ.get("NETEASE_COOKIE", "").strip()
    if environment_cookie:
        return environment_cookie
    try:
        if COOKIE_TXT_PATH.exists():
            return COOKIE_TXT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def save_cookie_header(cookie_header):
    """Validate and atomically persist a NetEase Cookie with owner-only access."""
    if os.environ.get("NETEASE_COOKIE", "").strip():
        raise MusicAPIError('网易云 Cookie 来自环境变量，请修改 NETEASE_COOKIE 后重启服务')
    raw_cookie = str(cookie_header or '').strip()
    if not raw_cookie or len(raw_cookie) > 65536 or '\n' in raw_cookie or '\r' in raw_cookie:
        raise ValueError('Cookie 内容为空或格式无效')
    cookies = parse_cookie_header(raw_cookie)
    if not cookies:
        raise ValueError('没有识别到有效的 Cookie 键值')

    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    text_tmp = COOKIE_TXT_PATH.with_suffix('.tmp')
    json_tmp = COOKIE_JSON_PATH.with_suffix('.tmp')
    normalized = '; '.join(f'{key}={value}' for key, value in cookies.items())
    with _cookie_lock:
        text_tmp.write_text(normalized, encoding='utf-8')
        json_tmp.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding='utf-8')
        os.chmod(text_tmp, 0o600)
        os.chmod(json_tmp, 0o600)
        os.replace(text_tmp, COOKIE_TXT_PATH)
        os.replace(json_tmp, COOKIE_JSON_PATH)
    return netease_auth_status()


def clear_cookie_header():
    """Remove a locally persisted NetEase Cookie; environment credentials are immutable."""
    if os.environ.get("NETEASE_COOKIE", "").strip():
        return False
    with _cookie_lock:
        for path in (COOKIE_TXT_PATH, COOKIE_JSON_PATH):
            path.unlink(missing_ok=True)
    return True


def netease_auth_status():
    """Return a secret-free summary suitable for the settings UI."""
    cookie_header = load_cookie_header()
    cookies = parse_cookie_header(cookie_header)
    source = 'environment' if os.environ.get("NETEASE_COOKIE", "").strip() else ('local' if cookies else 'none')
    updated_at = int(COOKIE_TXT_PATH.stat().st_mtime) if source == 'local' and COOKIE_TXT_PATH.exists() else 0
    return {
        'available': True,
        'authenticated': bool(cookies.get('MUSIC_U') or cookies.get('MUSIC_A')),
        'source': source,
        'cookie_count': len(cookies),
        'updated_at': updated_at,
    }


def create_netease_login_qrcode():
    """Create a NetEase app-login QR image through the configured compatible API."""
    last_error = None
    for api_base in configured_api_bases():
        try:
            timestamp = int(time.time() * 1000)
            key_response = requests.get(
                f"{api_base}/login/qr/key",
                params={'timestamp': timestamp},
                timeout=12,
            )
            key_response.raise_for_status()
            key_data = key_response.json()
            key = str((key_data.get('data') or {}).get('unikey') or '').strip()
            if key_data.get('code') != 200 or not key:
                raise MusicAPIError(key_data.get('message') or '网易云未返回登录 key')
            image_response = requests.get(
                f"{api_base}/login/qr/create",
                params={'key': key, 'qrimg': 'true', 'type': 1, 'timestamp': timestamp},
                timeout=12,
            )
            image_response.raise_for_status()
            image_data = image_response.json()
            payload = image_data.get('data') or {}
            image = str(payload.get('qrimg') or '').strip()
            if image_data.get('code') != 200 or not image.startswith('data:image'):
                raise MusicAPIError(image_data.get('message') or '网易云未返回二维码图片')
            return {'key': key, 'image': image}
        except Exception as exc:
            last_error = exc
            logger.warning(f"网易云登录二维码接口失败 ({api_base}): {exc}")
    raise MusicAPIError(f'网易云登录二维码生成失败：{last_error or "上游服务不可用"}')


def check_netease_login_qrcode(key):
    """Poll a NetEase QR and persist the returned Cookie once login succeeds."""
    login_key = str(key or '').strip()
    if not login_key:
        raise ValueError('网易云登录 key 无效')
    last_error = None
    for api_base in configured_api_bases():
        try:
            response = requests.get(
                f"{api_base}/login/qr/check",
                params={'key': login_key, 'timestamp': int(time.time() * 1000)},
                timeout=12,
            )
            response.raise_for_status()
            data = response.json()
            code = int(data.get('code') or 0)
            status_map = {800: 'timeout', 801: 'scan', 802: 'confirm', 803: 'done'}
            status = status_map.get(code, 'error')
            result = {'status': status, 'message': data.get('message') or data.get('msg') or ''}
            if code == 803:
                cookie_header = str(data.get('cookie') or (data.get('data') or {}).get('cookie') or '').strip()
                if not cookie_header and response.cookies:
                    cookie_header = '; '.join(f'{name}={value}' for name, value in response.cookies.items())
                if not cookie_header:
                    raise MusicAPIError('扫码成功，但上游没有返回可保存的 Cookie')
                result['auth'] = save_cookie_header(cookie_header)
            return result
        except MusicAPIError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(f"网易云登录状态接口失败 ({api_base}): {exc}")
    raise MusicAPIError(f'网易云登录状态检查失败：{last_error or "上游服务不可用"}')


def build_headers(extra: dict | None = None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
    }
    cookie_str = load_cookie_header()
    if cookie_str:
        headers["Cookie"] = cookie_str
    if extra:
        headers.update(extra)
    return headers

# 搜索音乐
def search_music_page(keyword, limit=8, offset=0):
    """按页搜索歌曲，避免一次把全部结果发送给客户端。"""
    limit = max(1, min(50, int(limit)))
    offset = max(0, int(offset))
    for api_index, api_base in enumerate(configured_api_bases()):
        endpoint = 'cloudsearch' if api_index == 0 else 'search'
        try:
            res = requests.get(
                f"{api_base}/{endpoint}",
                params={'keywords': keyword, 'limit': limit, 'offset': offset},
                headers=build_headers(),
                timeout=12,
            )
            res.raise_for_status()
            data = res.json()
            result = data.get('result', {}) or {}
            songs = result.get('songs', []) or []
            total_value = result.get('songCount')
            total = int(total_value or 0) if total_value is not None else (
                offset + len(songs) + (1 if len(songs) >= limit else 0)
            )
            return songs, total
        except Exception as exc:
            logger.warning(f"音乐搜索接口失败 ({api_base}): {exc}")
    raise MusicAPIError('音乐搜索服务不可用，请检查 MUSIC_API_BASE / BACKUP_MUSIC_API 配置')


def search_music(keyword):
    """兼容机器人文字命令的旧接口，默认返回前 30 首。"""
    songs, _ = search_music_page(keyword, limit=30, offset=0)
    return songs


def get_hot_searches(limit=12):
    """获取网易云实时热搜词；失败时返回空列表，不影响热歌榜展示。"""
    limit = max(1, min(20, int(limit)))
    for api_base in configured_api_bases():
        try:
            res = requests.get(
                f"{api_base}/search/hot/detail",
                headers=build_headers(),
                timeout=10,
            )
            res.raise_for_status()
            items = res.json().get('data', []) or []
            hot_searches = []
            for item in items:
                keyword = str(item.get('searchWord', '')).strip()
                if not keyword:
                    continue
                hot_searches.append({
                    'keyword': keyword,
                    'score': item.get('score', 0),
                    'content': item.get('content', ''),
                    'icon_type': item.get('iconType', 0),
                })
                if len(hot_searches) >= limit:
                    break
            if hot_searches:
                return hot_searches
        except Exception as exc:
            logger.warning(f"网易云热搜接口失败 ({api_base}): {exc}")
    return []


def get_hot_playlist_tracks(limit=8, offset=0):
    """分页获取网易云热歌榜，返回歌曲列表和是否可能还有下一页。"""
    limit = max(1, min(50, int(limit)))
    offset = max(0, int(offset))
    for api_base in configured_api_bases():
        try:
            res = requests.get(
                f"{api_base}/playlist/track/all",
                params={
                    'id': NETEASE_HOT_PLAYLIST_ID,
                    'limit': limit,
                    'offset': offset,
                },
                headers=build_headers(),
                timeout=12,
            )
            res.raise_for_status()
            data = res.json()
            if data.get('code') not in (None, 200):
                raise MusicAPIError(data.get('message') or '热歌榜接口返回异常')
            songs = data.get('songs', []) or []
            return songs, len(songs) >= limit
        except Exception as exc:
            logger.warning(f"网易云热歌榜接口失败 ({api_base}): {exc}")
    raise MusicAPIError('网易云热歌榜暂时不可用，请稍后重试')

# 获取音乐URL
def get_music_url(song_id):
    for api_base in configured_api_bases():
        try:
            res = requests.get(
                f"{api_base}/song/url",
                params={'id': song_id},
                headers=build_headers(),
                timeout=12,
            )
            res.raise_for_status()
            data = res.json()
            url = data.get('data', [{}])[0].get('url', '')
            if url:
                return url
        except Exception as exc:
            logger.warning(f"获取音乐URL失败 ({api_base}): {exc}")
    return ''


def get_song_detail(song_id):
    """获取单曲的专辑、封面和时长信息。"""
    for api_base in configured_api_bases():
        try:
            res = requests.get(
                f"{api_base}/song/detail?ids={song_id}",
                headers=build_headers(),
                timeout=10,
            )
            songs = res.json().get('songs', [])
            if songs:
                return songs[0]
        except Exception as exc:
            logger.warning(f"获取歌曲详情失败 ({api_base}): {exc}")
    return {}


def get_song_lyrics(song_id):
    """获取 LRC 歌词，优先原歌词，接口失败时返回空字符串。"""
    for api_base in configured_api_bases():
        try:
            res = requests.get(
                f"{api_base}/lyric?id={song_id}",
                headers=build_headers(),
                timeout=10,
            )
            lyric = res.json().get('lrc', {}).get('lyric', '')
            if lyric:
                return lyric
        except Exception as exc:
            logger.warning(f"获取歌词失败 ({api_base}): {exc}")
    return ''

# 获取歌单
def get_playlist(playlist_id):
    for api_base in configured_api_bases():
        try:
            res = requests.get(
                f"{api_base}/playlist/detail",
                params={'id': playlist_id},
                headers=build_headers(),
                timeout=12,
            )
            res.raise_for_status()
            data = res.json()
            playlist = data.get('playlist', {})
            if playlist:
                return playlist
        except Exception as exc:
            logger.warning(f"获取歌单失败 ({api_base}): {exc}")
    return {}

# 获取歌单中所有歌曲（支持分页）
def get_playlist_all_tracks(playlist_id):
    """获取歌单中所有歌曲，支持分页"""
    try:
        # 首先获取歌单基本信息
        playlist = get_playlist(playlist_id)
        if not playlist:
            return []
        
        track_count = playlist.get('trackCount', 0)
        print(f"歌单总歌曲数: {track_count}")
        
        all_tracks = []
        limit = 1000  # 每次请求的最大数量
        offset = 0
        
        while offset < track_count:
            try:
                # 使用分页参数获取歌曲 - 只获取歌曲信息，不获取URL
                url = f"{MUSIC_API_BASE}/playlist/track/all?id={playlist_id}&limit={limit}&offset={offset}"
                print(f"请求分页: offset={offset}, limit={limit}")
                
                res = requests.get(url, timeout=10, headers=build_headers())
                if res.status_code == 200:
                    data = res.json()
                    tracks = data.get('songs', [])
                    
                    if not tracks:
                        break
                    
                    all_tracks.extend(tracks)
                    print(f"获取到 {len(tracks)} 首歌曲")
                    
                    if len(tracks) < limit:
                        break
                    
                    offset += limit
                else:
                    print(f"分页请求失败: {res.status_code}")
                    break
                    
            except Exception as e:
                print(f"分页请求异常: {e}")
                break
        
        print(f"总共获取到 {len(all_tracks)} 首歌曲")
        return all_tracks
        
    except Exception as e:
        logger.error(f"获取完整歌单异常: {e}")
        return []

# 获取歌单中所有歌曲信息（不获取URL）
def get_playlist_urls(playlist_id):
    """获取歌单中所有歌曲信息，使用.env中配置的API，不获取URL"""
    # 使用分页功能获取所有歌曲
    tracks = get_playlist_all_tracks(playlist_id)
    result = []
    
    print(f"处理 {len(tracks)} 首歌曲...")
    
    for track in tracks:
        song_id = track.get('id')
        song_name = track.get('name', '')
        artists = track.get('ar', [])
        artist_name = artists[0].get('name', '') if artists else ''
        album_data = track.get('al', {}) or {}
        
        # 创建歌单歌曲标记，稍后实时获取URL
        song_marker = f"PLAYLIST_SONG:{song_id}:{song_name}:{artist_name}"
        
        result.append({
            'id': song_id,
            'name': song_name,
            'artist': artist_name,
            'album': album_data.get('name', ''),
            'cover': album_data.get('picUrl', ''),
            'duration': (track.get('dt', 0) or 0) / 1000,
            'marker': song_marker
        })
    
    print(f"成功处理 {len(result)} 首歌曲")
    return result

# 格式化播放列表数据
def format_playlist_data(play_list_data):
    result = []
    
    # 处理当前播放的歌曲
    now_playing = play_list_data.get('now_playing')
    if now_playing:
        file_path = now_playing.get('file', '')
        extra_data = now_playing.get('extra', {})
        
        # 检查是否是歌单歌曲标记
        if file_path.startswith("PLAYLIST_SONG:"):
            parts = file_path.split(":")
            if len(parts) >= 4:
                song_id = parts[1]
                song_name = parts[2]
                artist_name = parts[3]
                
                result.append({
                    'id': song_id,
                    'name': song_name,
                    'artist': artist_name,
                    'album': extra_data.get('album', ''),
                    'cover': extra_data.get('cover', ''),
                    'duration': now_playing.get('duration', extra_data.get('duration', 0)),
                    'provider': extra_data.get('provider', 'netease'),
                    'playing': True,
                    'position': now_playing.get('ss', 0),
                    'start_time': now_playing.get('start', 0)
                })
        else:
            # 普通文件
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path
            result.append({
                'id': str(extra_data.get('song_id', 'local')),
                'name': extra_data.get('title', file_name),
                'artist': extra_data.get('artist', '本地文件'),
                'album': extra_data.get('album', ''),
                'cover': extra_data.get('cover', ''),
                'duration': now_playing.get('duration', extra_data.get('duration', 0)),
                'provider': extra_data.get('provider', 'netease'),
                'playing': True,
                'position': now_playing.get('ss', 0),
                'start_time': now_playing.get('start', 0)
            })
    
    # 处理播放列表中的歌曲
    play_list = play_list_data.get('play_list', [])
    for queue_index, item in enumerate(play_list):
        file_path = item.get('file', '')
        extra_data = item.get('extra', {})
        
        # 检查是否是歌单歌曲标记
        if file_path.startswith("PLAYLIST_SONG:"):
            parts = file_path.split(":")
            if len(parts) >= 4:
                song_id = parts[1]
                song_name = parts[2]
                artist_name = parts[3]
                
                result.append({
                    'id': song_id,
                    'name': song_name,
                    'artist': artist_name,
                    'album': extra_data.get('album', ''),
                    'cover': extra_data.get('cover', ''),
                    'duration': extra_data.get('duration', 0),
                    'provider': extra_data.get('provider', 'netease'),
                    'queue_index': queue_index,
                    'playing': False
                })
        else:
            # 普通文件
            file_name = file_path.split('/')[-1] if '/' in file_path else file_path
            result.append({
                'id': str(extra_data.get('song_id', 'local')),
                'name': extra_data.get('title', file_name),
                'artist': extra_data.get('artist', '本地文件'),
                'album': extra_data.get('album', ''),
                'cover': extra_data.get('cover', ''),
                'duration': extra_data.get('duration', 0),
                'provider': extra_data.get('provider', 'netease'),
                'queue_index': queue_index,
                'playing': False
            })
    
    return result

# 保存配置到文件
def save_config(config_data, file_path='config.json'):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存配置异常: {e}")
        return False

# 从文件加载配置
def load_config(file_path='config.json'):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载配置异常: {e}")
        return {}
