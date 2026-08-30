import asyncio
import os
import threading
import time
import logging
import gc
import psutil
import random
import subprocess
import sys
from array import array
from enum import Enum, unique
from typing import Dict, Union, List, Any, Optional, Coroutine as CoroutineType
from asyncio import AbstractEventLoop
try:
    from .requestor import VoiceRequestor
except ImportError:
    from requestor import VoiceRequestor

try:
    from ..config import (
        MUSIC_CACHE_MAX_SONGS,
        MUSIC_CACHE_TTL,
        MUSIC_CONTINUATION_LEAD_SECONDS,
        MUSIC_IDLE_DISCONNECT_SECONDS,
        MUSIC_PRELOAD_SECONDS,
        MUSIC_STARTUP_BUFFER_SECONDS,
        MUSIC_STARTUP_GRACE_SECONDS,
        MUSIC_STREAM_BUFFER_SECONDS,
    )
except ImportError:
    from config import (
        MUSIC_CACHE_MAX_SONGS,
        MUSIC_CACHE_TTL,
        MUSIC_CONTINUATION_LEAD_SECONDS,
        MUSIC_IDLE_DISCONNECT_SECONDS,
        MUSIC_PRELOAD_SECONDS,
        MUSIC_STARTUP_BUFFER_SECONDS,
        MUSIC_STARTUP_GRACE_SECONDS,
        MUSIC_STREAM_BUFFER_SECONDS,
    )

# 配置日志
logger = logging.getLogger(__name__)
log_enabled = False

def configure_logging(enabled: bool = True):
    global log_enabled
    log_enabled = enabled
    if enabled:
        logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
    else:
        logging.disable(logging.CRITICAL)

ffmpeg_bin = os.environ.get('FFMPEG_BIN', 'ffmpeg')

original_loop = None  # 初始化为None，后面会赋值为AbstractEventLoop

def set_ffmpeg(path):
    global ffmpeg_bin
    ffmpeg_bin = path

@unique
class Status(Enum):
    STOP = 0
    WAIT = 1
    SKIP = 2
    END = 3
    START = 4
    PAUSE = 5
    PLAYING = 10
    EMPTY = 11

guild_status = {}
play_list: Dict[str, Dict[str, Any]] = {}
guild_volume: Dict[str, float] = {}
guild_play_mode: Dict[str, str] = {}
play_history: Dict[str, List[Dict[str, Any]]] = {}
play_list_example = {'服务器id':
                              {'token': '机器人token',
                               'voice_channel': '语音频道id',
                               'text_channel': '最后一次执行指令的文字频道id',
                               'now_playing': {'file': '歌曲文件', 'ss': 0, 'start': 0,'extra':{}},
                               'play_list': [
                                   {'file': '路径', 'ss': 0}]}}

playlist_handle_status = {}


def get_guild_volume(guild_id: str) -> float:
    """返回服务器音量，并限制在 FFmpeg 可接受的安全范围。"""
    return max(0.0, min(1.0, float(guild_volume.get(str(guild_id), 0.4))))

# 音频缓存和预加载机制。统一使用原始 PCM，才能在缓存边界无缝接回实时解码流。
PCM_SAMPLE_RATE = 48000
PCM_CHANNELS = 2
PCM_SAMPLE_BYTES = 2
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * PCM_CHANNELS * PCM_SAMPLE_BYTES
PCM_FRAME_DURATION = 0.02
PCM_FRAME_BYTES = int(PCM_BYTES_PER_SECOND * PCM_FRAME_DURATION)
PCM_SILENCE_FRAME = bytes(PCM_FRAME_BYTES)
VOLUME_RAMP_SECONDS = 0.12
preload_seconds = max(300, MUSIC_PRELOAD_SECONDS)
preload_max_bytes = preload_seconds * PCM_BYTES_PER_SECOND
continuation_lead_seconds = MUSIC_CONTINUATION_LEAD_SECONDS
decoder_buffer_seconds = MUSIC_STREAM_BUFFER_SECONDS
startup_buffer_seconds = min(MUSIC_STARTUP_BUFFER_SECONDS, decoder_buffer_seconds)
startup_grace_seconds = MUSIC_STARTUP_GRACE_SECONDS
idle_disconnect_seconds = MUSIC_IDLE_DISCONNECT_SECONDS
PCM_DECODER_READ_BYTES = PCM_BYTES_PER_SECOND // 2
audio_cache = {}  # key -> {data, complete, duration, owner_guild, ...}
preload_queue = {}  # guild_id -> {key, generation, running}
guild_transport_metrics: Dict[str, Dict[str, Any]] = {}
cache_lock = threading.RLock()
cache_max_size = MUSIC_CACHE_MAX_SONGS
cache_cleanup_interval = MUSIC_CACHE_TTL
last_cache_cleanup = time.time()

# 歌曲播放计数和清理机制
song_play_count = {}  # 每个服务器的歌曲播放计数
cleanup_threshold = 3  # 播放多少首歌曲后清理（可配置为2-4首）

def cleanup_audio_cache():
    """在歌曲切换点清理过期缓存；返回本次是否执行了周期维护。"""
    global audio_cache, last_cache_cleanup
    current_time = time.time()
    
    if current_time - last_cache_cleanup > cache_cleanup_interval:
        # 清理过期的缓存
        with cache_lock:
            expired_keys = [
                key for key, cache_data in audio_cache.items()
                if not cache_data.get('in_use')
                and current_time - cache_data.get('timestamp', 0) > cache_cleanup_interval
            ]

            for key in expired_keys:
                del audio_cache[key]
                if log_enabled:
                    logger.info(f'清理过期音频缓存: {key}')

            # 如果缓存仍然过大，优先清理未播放且最旧的缓存。
            removable = sorted(
                ((key, value) for key, value in audio_cache.items() if not value.get('in_use')),
                key=lambda item: item[1].get('timestamp', 0),
            )
            excess = max(0, len(audio_cache) - cache_max_size)
            for key, _ in removable[:excess]:
                del audio_cache[key]
                if log_enabled:
                    logger.info(f'清理超量音频缓存: {key}')
        
        last_cache_cleanup = current_time
        
        return True
    return False

def smart_cleanup(guild_id):
    """智能清理：根据播放歌曲数量进行清理"""
    global song_play_count, audio_cache
    
    # 初始化播放计数
    if guild_id not in song_play_count:
        song_play_count[guild_id] = 0
    
    # 增加播放计数
    song_play_count[guild_id] += 1
    
    if log_enabled:
        logger.info(f'服务器 {guild_id} 已播放 {song_play_count[guild_id]} 首歌曲')
    
    # 检查是否需要清理
    if song_play_count[guild_id] >= cleanup_threshold:
        if log_enabled:
            logger.info(f'达到清理阈值 ({cleanup_threshold}首)，开始智能清理...')
        
        # 智能清理：只清理过期的缓存，保留最近使用的
        cache_before = len(audio_cache)
        current_time = time.time()
        expired_keys = []
        
        # 找出过期的缓存项（超过10分钟）
        with cache_lock:
            for key, cache_data in audio_cache.items():
                if (not cache_data.get('in_use')
                        and current_time - cache_data.get('timestamp', 0) > cache_cleanup_interval):
                    expired_keys.append(key)

            for key in expired_keys:
                del audio_cache[key]

            removable = sorted(
                ((key, value) for key, value in audio_cache.items() if not value.get('in_use')),
                key=lambda item: item[1].get('timestamp', 0),
            )
            excess_count = max(0, len(audio_cache) - cache_max_size)
            for key, _ in removable[:excess_count]:
                del audio_cache[key]
        
        # 重置播放计数
        song_play_count[guild_id] = 0
        
        # 记录清理结果
        if log_enabled:
            memory_info = psutil.Process().memory_info()
            cache_after = len(audio_cache)
            logger.info(f'智能清理完成: 清理了 {cache_before - cache_after} 个缓存项，剩余 {cache_after} 个')
            logger.info(f'清理后内存使用: RSS={memory_info.rss / 1024 / 1024:.2f}MB, VMS={memory_info.vms / 1024 / 1024:.2f}MB')
        
        return True
    
    return False


def run_transition_maintenance(guild_id):
    """只在一首歌曲结束后执行缓存维护与强制 GC，避免打断正在发送的 RTP。"""
    cache_maintenance_due = cleanup_audio_cache()
    smart_maintenance_due = smart_cleanup(guild_id)
    if not cache_maintenance_due and not smart_maintenance_due:
        return False
    started_at = time.monotonic()
    collected = gc.collect()
    if log_enabled:
        memory_info = psutil.Process().memory_info()
        logger.info(
            f'歌曲切换维护完成: GC={collected}, '
            f'耗时={(time.monotonic() - started_at) * 1000:.1f}ms, '
            f'RSS={memory_info.rss / 1024 / 1024:.2f}MB'
        )
    return True

def get_cleanup_stats():
    """获取清理统计信息"""
    return {
        'song_play_count': song_play_count.copy(),
        'cleanup_threshold': cleanup_threshold,
        'cache_count': len(audio_cache),
        'cache_max_size': cache_max_size
    }

def get_cache_key(file_path, ss_value=0):
    """生成与音量无关的原始 PCM 缓存键。"""
    return f"{file_path}:{float(ss_value):.3f}"


def get_audio_identity(music_info):
    """使用音源和歌曲 ID 生成稳定标识，避免临时 URL 更新后缓存失效。"""
    extra = music_info.get('extra', {}) if isinstance(music_info, dict) else {}
    song_id = extra.get('song_id') if isinstance(extra, dict) else None
    provider = extra.get('provider', 'netease') if isinstance(extra, dict) else 'netease'
    file_path = music_info.get('file', '') if isinstance(music_info, dict) else str(music_info)
    if song_id:
        return f'{provider}:song:{song_id}'
    if file_path.startswith('PLAYLIST_SONG:'):
        parts = file_path.split(':', 3)
        if len(parts) > 1:
            return f'song:{parts[1]}'
    return file_path


def get_queue_item_cache_key(guild_id, music_info):
    identity = get_audio_identity(music_info)
    ss_value = music_info.get('ss', 0) if isinstance(music_info, dict) else 0
    return get_cache_key(f'guild:{guild_id}:{identity}', ss_value)


def apply_pcm_gain(pcm_data: bytes, gain: float) -> bytes:
    """对 16-bit little-endian PCM 应用增益，不改变缓存中的原始数据。"""
    if not pcm_data:
        return pcm_data
    gain = max(0.0, min(1.0, float(gain)))
    if gain <= 0.0001:
        return bytes(len(pcm_data))
    if gain >= 0.9999:
        return pcm_data
    samples = array('h')
    samples.frombytes(pcm_data)
    if sys.byteorder != 'little':
        samples.byteswap()
    for index, sample in enumerate(samples):
        samples[index] = int(sample * gain)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


class PCMVolumeRamp:
    """在若干个 20ms 帧内平滑过渡音量，避免突变产生爆音。"""

    def __init__(self, gain: float):
        self.current = max(0.0, min(1.0, float(gain)))
        self.target = self.current
        self.step = 0.0
        self.remaining = 0

    def process(self, pcm_data: bytes, target_gain: float) -> bytes:
        target_gain = max(0.0, min(1.0, float(target_gain)))
        if abs(target_gain - self.target) > 0.0001:
            self.target = target_gain
            self.remaining = max(1, round(VOLUME_RAMP_SECONDS / PCM_FRAME_DURATION))
            self.step = (self.target - self.current) / self.remaining
        if self.remaining > 0:
            self.current += self.step
            self.remaining -= 1
            if self.remaining == 0:
                self.current = self.target
        return apply_pcm_gain(pcm_data, self.current)


class PCMTransportPacer:
    """用绝对截止时间维持长期 50fps；大于一帧的迟到只重同步、不突发追赶。"""

    def __init__(self, frame_duration=PCM_FRAME_DURATION, clock=time.monotonic, sleeper=asyncio.sleep):
        self.frame_duration = float(frame_duration)
        self.clock = clock
        self.sleeper = sleeper
        self.deadline = self.clock()

    async def wait(self):
        now = self.clock()
        lateness = max(0.0, now - self.deadline)
        resynced = lateness > self.frame_duration
        if resynced:
            # 严重迟到时从当前帧重新起算，避免连续补发造成听感加速。
            self.deadline = now
        else:
            delay = self.deadline - now
            if delay > 0:
                await self.sleeper(delay)
                now = self.clock()
                lateness = max(0.0, now - self.deadline)
                if lateness > self.frame_duration:
                    # 调度器本身严重过眠时也立刻重同步，下一帧不能紧贴当前帧突发。
                    self.deadline = now
                    resynced = True
        self.deadline += self.frame_duration
        return lateness, resynced


def get_voice_transport_metrics(guild_id: str) -> Dict[str, Any]:
    """返回当前语音连接的发送时钟快照，供监控接口读取。"""
    metrics = guild_transport_metrics.get(str(guild_id)) or {}
    if not metrics:
        return {}
    first_sent_at = float(metrics.get('first_sent_at') or 0)
    last_sent_at = float(metrics.get('last_sent_at') or 0)
    frames_sent = int(metrics.get('frames_sent') or 0)
    elapsed = max(0.0, last_sent_at - first_sent_at)
    snapshot = dict(metrics)
    snapshot['actual_fps'] = (
        (frames_sent - 1) / elapsed
        if frames_sent > 1 and elapsed > 0
        else 0.0
    )
    snapshot['target_fps'] = 1 / PCM_FRAME_DURATION
    return snapshot


class BufferedPCMDecoder:
    """持续读取 FFmpeg 输出，并与 20ms RTP 发送时钟解耦。"""

    def __init__(self, process, capacity_seconds=decoder_buffer_seconds):
        self.process = process
        chunk_capacity = max(
            2,
            int(capacity_seconds * PCM_BYTES_PER_SECOND / PCM_DECODER_READ_BYTES),
        )
        self.queue = asyncio.Queue(maxsize=chunk_capacity)
        self.buffered_bytes = 0
        self.eof = False
        self.error = None
        self._closed = False
        self.task = asyncio.create_task(self._pump())

    async def _pump(self):
        try:
            if not self.process or not self.process.stdout:
                return
            while not self._closed:
                reached_eof = False
                try:
                    # 固定聚合为 0.5 秒块，队列容量才能准确对应配置的秒数。
                    chunk = await self.process.stdout.readexactly(PCM_DECODER_READ_BYTES)
                except asyncio.IncompleteReadError as exc:
                    chunk = exc.partial
                    reached_eof = True
                if not chunk:
                    break
                await self.queue.put(chunk)
                self.buffered_bytes += len(chunk)
                if reached_eof:
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = exc
        finally:
            self.eof = True

    async def read(self, timeout=PCM_FRAME_DURATION):
        """有数据返回 bytes，暂时缺数据返回 None，完整结束返回 b''。"""
        if self.eof and self.queue.empty():
            return b''
        try:
            chunk = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return b'' if self.eof and self.queue.empty() else None
        self.buffered_bytes = max(0, self.buffered_bytes - len(chunk))
        return chunk

    async def close(self):
        self._closed = True
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass


def resolve_audio_source(music_info):
    """把音源标记解析为临时播放 URL，并在过期前复用。"""
    file_path = music_info.get('file', '')
    is_netease_playlist = file_path.startswith('PLAYLIST_SONG:')
    is_provider_song = file_path.startswith('MUSIC_SOURCE:')
    if not is_netease_playlist and not is_provider_song:
        return file_path

    extra = music_info.get('extra', {}) if isinstance(music_info, dict) else {}
    resolved = music_info.get('resolved_file', '') or extra.get('_resolved_url', '')
    expires_at = float(extra.get('_resolved_expires_at', 0) or 0)
    if resolved and (expires_at <= 0 or expires_at > time.time() + 60):
        return resolved

    try:
        if is_provider_song:
            parts = file_path.split(':', 2)
            if len(parts) != 3:
                return ''
            provider, song_id = parts[1], parts[2]
            if provider == 'qqmusic':
                try:
                    from .. import qqmusic_service
                except ImportError:
                    import qqmusic_service
                source = qqmusic_service.resolve_song_url(song_id)
                resolved = source.get('url', '')
                extra['_resolved_url'] = resolved
                extra['_resolved_expires_at'] = time.time() + max(0, int(source.get('expires_in', 0)))
            elif provider == 'bilibili':
                try:
                    from .. import bilibili_service
                except ImportError:
                    import bilibili_service
                source = bilibili_service.resolve_audio(song_id)
                resolved = source.get('url', '')
                extra['_resolved_url'] = resolved
                extra['_resolved_expires_at'] = float(source.get('expires_at', 0) or 0)
                http_headers = source.get('headers') or {}
                extra['header'] = ''.join(
                    f'{key}: {value}\r\n' for key, value in http_headers.items()
                )
                extra['user_agent'] = http_headers.get('User-Agent', '')
                extra['referer'] = http_headers.get('Referer', '')
                extra['duration'] = float(source.get('duration', 0) or extra.get('duration', 0) or 0)
            else:
                return ''
        else:
            parts = file_path.split(':', 3)
            if len(parts) < 2:
                return ''
            try:
                from ..utils import get_music_url
            except ImportError:
                from utils import get_music_url
            resolved = get_music_url(parts[1])
            extra['_resolved_url'] = resolved
            # 网易云播放 URL 通常是临时地址；保守地在 4 分钟后重新解析。
            extra['_resolved_expires_at'] = time.time() + 240
        if resolved:
            music_info['resolved_file'] = resolved
        return resolved
    except Exception as exc:
        if log_enabled:
            logger.warning(f'预加载时解析歌曲 URL 失败: {exc}')
        return ''


def build_ffmpeg_input_options(extra_data):
    """把来源所需的请求头/Cookie组装为 FFmpeg 输入参数。"""
    extra_data = extra_data or {}
    full_command = str(extra_data.get('extra_command', '') or '')
    for name, value in (
        ('headers', extra_data.get('header')),
        ('cookies', extra_data.get('cookies')),
        ('user_agent', extra_data.get('user_agent')),
        ('referer', extra_data.get('referer')),
    ):
        if value:
            full_command += f' -{name} "{value}"'
    return full_command


def decode_audio_prefix(file_path, ss_value=0, extra_command='', cancel_event=None):
    """同步预解码最多 preload_seconds 秒 PCM，并标记是否已经读完整首。"""
    command = (
        f'{ffmpeg_bin} -loglevel error -nostats -reconnect 1 -reconnect_streamed 1 '
        f'-reconnect_delay_max 2 -timeout 30000000 {extra_command} '
        f'-ss {ss_value} -i "{file_path}" -acodec pcm_s16le -ac {PCM_CHANNELS} '
        f'-ar {PCM_SAMPLE_RATE} -f s16le -y -'
    )
    process = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    audio_data = bytearray()
    complete = False
    cancelled = False
    try:
        while len(audio_data) < preload_max_bytes:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break
            remaining = preload_max_bytes - len(audio_data)
            chunk = process.stdout.read(min(96000, remaining)) if process.stdout else b''
            if not chunk:
                complete = True
                break
            audio_data.extend(chunk)
    finally:
        if complete:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        else:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
    data = bytes(audio_data)
    return {
        'data': data,
        'complete': complete,
        'duration': len(data) / PCM_BYTES_PER_SECOND,
        'size': len(data),
        'timestamp': time.time(),
        'cancelled': cancelled,
    }


def schedule_next_preload(guild_id):
    """只缓存指定服务器队列中的下一首；队列变化时旧任务结果会被丢弃。"""
    guild_id = str(guild_id)
    guild_playlist = play_list.get(guild_id, {})
    queue = guild_playlist.get('play_list', [])
    next_song = queue[0] if queue else None
    current_song = guild_playlist.get('now_playing')
    next_key = get_queue_item_cache_key(guild_id, next_song) if next_song else ''
    current_key = get_queue_item_cache_key(guild_id, current_song) if current_song else ''

    with cache_lock:
        protected_keys = {key for key in (next_key, current_key) if key}
        for key, value in list(audio_cache.items()):
            if (value.get('owner_guild') == guild_id and key not in protected_keys
                    and not value.get('in_use')):
                del audio_cache[key]

        existing_job = preload_queue.get(guild_id, {})
        if not next_song:
            cancel_event = existing_job.get('cancel_event')
            if cancel_event:
                cancel_event.set()
            preload_queue.pop(guild_id, None)
            return
        if next_key in audio_cache or (
            existing_job.get('key') == next_key and existing_job.get('running')
        ):
            return
        previous_cancel_event = existing_job.get('cancel_event')
        if previous_cancel_event:
            previous_cancel_event.set()
        generation = time.time_ns()
        cancel_event = threading.Event()
        preload_queue[guild_id] = {
            'key': next_key,
            'generation': generation,
            'running': True,
            'cancel_event': cancel_event,
        }

    def run_preload():
        try:
            file_path = resolve_audio_source(next_song)
            if not file_path:
                return
            extra = next_song.get('extra', {}) if isinstance(next_song, dict) else {}
            extra_command = build_ffmpeg_input_options(extra)
            cached = decode_audio_prefix(
                file_path,
                next_song.get('ss', 0),
                extra_command,
                cancel_event,
            )
            if cached.get('cancelled'):
                if log_enabled:
                    logger.info(f'下一首预加载已取消: {next_key}')
                return
            try:
                expected_remaining = max(
                    0.0,
                    float(extra.get('duration', 0) or 0) - float(next_song.get('ss', 0) or 0),
                )
            except (TypeError, ValueError):
                expected_remaining = 0.0
            if (cached.get('complete') and expected_remaining > 0
                    and cached.get('duration', 0) < expected_remaining - 2.0):
                # FFmpeg 正常退出不代表歌曲真的完整；临时 URL 失效时也可能只返回
                # 一个短片段。按 API 元数据识别“假 EOF”，保留前缀并继续续流。
                cached['complete'] = False
                next_song.pop('resolved_file', None)
                extra.pop('_resolved_url', None)
                extra.pop('_resolved_expires_at', None)
                if log_enabled:
                    logger.warning(
                        f'下一首预加载提前结束: 得到 {cached["duration"]:.1f}s / '
                        f'预期 {expected_remaining:.1f}s，将在播放时刷新 URL 续流'
                    )
            with cache_lock:
                job = preload_queue.get(guild_id, {})
                current_queue = play_list.get(guild_id, {}).get('play_list', [])
                current_next_key = get_queue_item_cache_key(guild_id, current_queue[0]) if current_queue else ''
                if job.get('generation') != generation or current_next_key != next_key:
                    return
                cached['owner_guild'] = guild_id
                cached['in_use'] = False
                cached.pop('cancelled', None)
                audio_cache[next_key] = cached
                job['running'] = False
                if log_enabled:
                    logger.info(
                        f'下一首预加载完成: {cached["duration"]:.1f}s, '
                        f'{cached["size"] / 1024 / 1024:.1f}MiB, complete={cached["complete"]}'
                    )
        except Exception as exc:
            if log_enabled:
                logger.error(f'下一首预加载失败: {exc}')
        finally:
            with cache_lock:
                job = preload_queue.get(guild_id, {})
                if job.get('generation') == generation:
                    job['running'] = False

    preload_thread = threading.Thread(target=run_preload, daemon=True)
    preload_thread.start()

async def preload_audio(file_path, ss_value=0, extra_command=''):
    """预加载音频数据到缓存"""
    cache_key = get_cache_key(file_path, ss_value)
    with cache_lock:
        if cache_key in audio_cache:
            return audio_cache[cache_key]
    try:
        if log_enabled:
            logger.info(f'开始预加载音频: {file_path}')
        cached = await asyncio.to_thread(
            decode_audio_prefix,
            file_path,
            ss_value,
            extra_command,
        )
        with cache_lock:
            audio_cache[cache_key] = cached
        if log_enabled:
            logger.info(f'预加载完成: {file_path}, 时长: {cached["duration"]:.1f}s')
        return cached
    except Exception as e:
        if log_enabled:
            logger.error(f'预加载音频失败: {file_path}, 错误: {e}')
        return None

class Player:
    def __init__(self, guild_id, voice_channel_id=None, token=None):
        """
            :param str guild_id: 推流服务器id
            :param str voice_channel_id: 推流语音频道id
            :param str token: 推流机器人token
        """
        self.guild_id = str(guild_id)

        if self.guild_id in play_list:
            if token is None:
                token = play_list[self.guild_id]['token']
            else:
                if token != play_list[self.guild_id]['token']:
                    raise ValueError('播放歌曲过程中无法更换token')
            if voice_channel_id is None:
                voice_channel_id = play_list[self.guild_id]['voice_channel']
            else:
                if voice_channel_id != play_list[self.guild_id]['voice_channel']:
                    raise ValueError('播放歌曲过程中无法更换语音频道')
        self.token = str(token) if token else ""
        self.voice_channel_id = str(voice_channel_id) if voice_channel_id else ""

    def join(self):
        global guild_status
        if not self.voice_channel_id:
            raise ValueError('第一次启动推流时，你需要指定语音频道id')
        if not self.token:
            raise ValueError('第一次启动推流时，你需要指定机器人token')
        if self.guild_id not in play_list:
            play_list[self.guild_id] = {'token': self.token,
                                        'now_playing': None,
                                        'play_list': []}
        guild_volume.setdefault(self.guild_id, 0.4)
        guild_play_mode.setdefault(self.guild_id, 'order')
        play_history.setdefault(self.guild_id, [])
        guild_status[self.guild_id] = Status.WAIT
        play_list[self.guild_id]['voice_channel'] = self.voice_channel_id
        if log_enabled:
            logger.info(f'加入语音频道: {self.voice_channel_id}，服务器: {self.guild_id}')
        PlayHandler(self.guild_id, self.token).start()

    def add_music(self, music: str, extra_data: dict = {}):
        """
        添加音乐到播放列表
            :param str music: 音乐文件路径或音乐链接
            :param dict extra_data: 可以在这里保存音乐信息
        """
        if not self.voice_channel_id:
            raise ValueError('第一次启动推流时，你需要指定语音频道id')
        if not self.token:
            raise ValueError('第一次启动推流时，你需要指定机器人token')
        need_start = False
        if self.guild_id not in play_list:
            need_start = True
            play_list[self.guild_id] = {'token': self.token,
                                        'now_playing': None,
                                        'play_list': []}
        guild_volume.setdefault(self.guild_id, 0.4)
        guild_play_mode.setdefault(self.guild_id, 'order')
        play_history.setdefault(self.guild_id, [])
        # 延迟解析的网易云歌单/QQ 音乐标记不对应本地文件。
        if not music.startswith(("PLAYLIST_SONG:", "MUSIC_SOURCE:")):
            if 'http' not in music:
                if not os.path.exists(music):
                    raise ValueError('文件不存在')

        play_list[self.guild_id]['voice_channel'] = self.voice_channel_id
        play_list[self.guild_id]['play_list'].append({'file': music, 'ss': 0, 'extra': extra_data})
        
        # 无论批量加入多少歌曲，都只跟踪队首这一首作为“下一首”。
        schedule_next_preload(self.guild_id)
        
        if log_enabled:
            logger.info(f'添加音乐到播放列表，服务器: {self.guild_id}，音乐: {music}')
        if (self.guild_id in guild_status
                and guild_status[self.guild_id] in (Status.WAIT, Status.EMPTY)):
            guild_status[self.guild_id] = Status.END
        if need_start:
            if play_list[self.guild_id]['play_list']:
                PlayHandler(self.guild_id, self.token).start()
            elif ((self.guild_id not in playlist_handle_status
                   or (not playlist_handle_status[self.guild_id]))
                  and play_list[self.guild_id]['play_list']):
                PlayHandler(self.guild_id, self.token).start()
    
    def refresh_preload(self):
        """队列排序、删除或清空后重新锁定唯一的下一首缓存目标。"""
        schedule_next_preload(self.guild_id)

    def stop(self):
        global guild_status, playlist_handle_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        guild_status[self.guild_id] = Status.STOP
        if log_enabled:
            logger.info(f'停止播放，服务器: {self.guild_id}')

    def clear(self):
        """清空全部音乐；播放线程保留短暂冷却，期间有新歌则继续复用连接。"""
        global guild_status

        guild_playlist = play_list.get(self.guild_id)
        if guild_playlist:
            guild_playlist['play_list'] = []
            guild_playlist['now_playing'] = None

        play_history.pop(self.guild_id, None)
        song_play_count.pop(self.guild_id, None)

        # 取消下一首预加载目标并移除本服务器缓存；播放循环已经持有的数据
        # 仍有自己的引用，可安全等待 SKIP 在下一帧边界结束。
        with cache_lock:
            preload_job = preload_queue.pop(self.guild_id, None)
            cancel_event = preload_job.get('cancel_event') if preload_job else None
            if cancel_event:
                cancel_event.set()
            for key, value in list(audio_cache.items()):
                if value.get('owner_guild') == self.guild_id:
                    del audio_cache[key]

        # SKIP 会立即停止当前歌曲，但不会立刻拆掉 RTP/语音连接。
        guild_status[self.guild_id] = Status.SKIP
        if log_enabled:
            logger.info(
                f'清空全部音乐，进入 {idle_disconnect_seconds:.1f}s 退出冷却，'
                f'服务器: {self.guild_id}'
            )

    def skip(self, skip_amount: int = 1):
        '''
        跳过指定数量的歌曲
            :param amount int: 要跳过的歌曲数量,默认为一首
        '''
        global guild_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        for i in range(skip_amount - 1):
            try:
                if play_list[self.guild_id]['play_list']:
                    play_list[self.guild_id]['play_list'].pop(0)
            except:
                pass
        schedule_next_preload(self.guild_id)
        guild_status[self.guild_id] = Status.SKIP
        if log_enabled:
            logger.info(f'跳过了 {skip_amount} 首歌曲，服务器: {self.guild_id}')

    def pause(self):
        global guild_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        if not play_list[self.guild_id].get('now_playing'):
            raise ValueError('当前没有正在播放的歌曲')
        guild_status[self.guild_id] = Status.PAUSE
        if log_enabled:
            logger.info(f'暂停播放，服务器: {self.guild_id}')

    def resume(self):
        global guild_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        if not play_list[self.guild_id].get('now_playing'):
            raise ValueError('当前没有可继续播放的歌曲')
        guild_status[self.guild_id] = Status.PLAYING
        if log_enabled:
            logger.info(f'继续播放，服务器: {self.guild_id}')

    def list(self, json=True):
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        if json:
            result = []
            if play_list[self.guild_id]['now_playing']:
                result.append(play_list[self.guild_id]['now_playing'])
            result.extend(play_list[self.guild_id]['play_list'])
            return result
        else:
            # 懒得写
            return []

    def seek(self, music_seconds: int):
        '''
        跳转至歌曲指定位置
            :param music_seconds int: 所要跳转到歌曲的秒数
        '''
        global play_list
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        if play_list[self.guild_id]['now_playing']:
            now_play = play_list[self.guild_id]['now_playing'].copy()
            now_play['ss'] = int(music_seconds)
            if 'start' in now_play:
                del now_play['start']
            play_list[self.guild_id]['play_list'].insert(0, now_play)
            guild_status[self.guild_id] = Status.SKIP
            if log_enabled:
                logger.info(f'跳转至 {music_seconds} 秒，服务器: {self.guild_id}')


# 事件处理部分

events = {}

class PlayInfo:
    def __init__(self, guild_id, voice_channel_id, file, bot_token, extra_data):
        self.file = file
        self.extra_data = extra_data
        self.guild_id = guild_id
        self.voice_channel_id = voice_channel_id
        self.token = bot_token

def on_event(event):
    global events
    def _on_event_wrapper(func):
        if event not in events:
            events[event] = []
        events[event].append(func)
        return func
    return _on_event_wrapper

async def trigger_event(event, *args, **kwargs):
    if event in events:
        for func in events[event]:
            await func(*args, **kwargs)

class PlayHandler(threading.Thread):
    channel_id: str = None

    def __init__(self, guild_id: str, token: str):
        threading.Thread.__init__(self)
        self.token = token
        self.guild = guild_id
        self.requestor = VoiceRequestor(token)

    def run(self):
        if log_enabled:
            logger.info(f'开始处理，服务器: {self.guild}')
        loop_t = asyncio.new_event_loop()
        asyncio.set_event_loop(loop_t)
        loop_t.run_until_complete(self.main())
        if log_enabled:
            logger.info(f'处理完成，服务器: {self.guild}')

    async def main(self):
        start_event = asyncio.Event()
        task1 = asyncio.create_task(self.push())
        task2 = asyncio.create_task(self.keepalive())
        task3 = asyncio.create_task(self.stop(start_event))

        done, pending = await asyncio.wait(
            [task1, task2],
            return_when=asyncio.FIRST_COMPLETED
        )
        if done:
            await asyncio.gather(*done, return_exceptions=True)

        # 可选地取消未完成的任务
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        # 触发 task3 开始
        start_event.set()
        await task3

    async def stop(self, start_event):
        await start_event.wait()
        global playlist_handle_status
        try:
            if self.channel_id:
                await self.requestor.leave(self.channel_id)
        except Exception as exc:
            if log_enabled:
                logger.warning(f'退出语音频道失败，频道: {self.channel_id}，错误: {exc}')
        finally:
            try:
                await self.requestor.close()
            except Exception:
                pass
            # /api/clear 会等待 play_list 被移除；因此必须在离开请求完成后
            # 再发布“退出完成”状态，避免前端过早显示已断开。
            play_list.pop(self.guild, None)
            guild_transport_metrics.pop(self.guild, None)
            if self.guild in playlist_handle_status:
                playlist_handle_status[self.guild] = False
        if log_enabled:
            logger.info(f'停止并清理，服务器: {self.guild}')

    async def push(self):
        global playlist_handle_status
        playlist_handle_status[self.guild] = True
        try:
            await asyncio.sleep(1)
            if guild_status.get(self.guild) == Status.STOP:
                return
            if self.guild in play_list and 'voice_channel' in play_list[self.guild]:
                new_channel = play_list[self.guild]['voice_channel']
                self.channel_id = new_channel

                try:
                    await self.requestor.leave(self.channel_id)
                except:
                    pass
                try:
                    res = await self.requestor.join(self.channel_id)
                except Exception as e:
                    if log_enabled:
                        logger.error(f'加入频道失败: {e}')
                    raise RuntimeError(f'加入频道失败 {e}')

                rtp_url = f"rtp://{res['ip']}:{res['port']}?rtcpport={res['rtcp_port']}"
                if log_enabled:
                    try:
                        logger.info(f"RTP配置: {res}")
                    except Exception:
                        pass

                audio_ssrc = res.get('audio_ssrc', 1111)
                audio_pt = res.get('audio_pt', 111)
                transport_metrics = {
                    'rtp_ip': str(res.get('ip') or ''),
                    'rtp_port': int(res.get('port') or 0),
                    'frames_sent': 0,
                    'late_frames': 0,
                    'resyncs': 0,
                    'max_lateness_ms': 0.0,
                    'last_lateness_ms': 0.0,
                    'first_sent_at': 0.0,
                    'last_sent_at': 0.0,
                }
                guild_transport_metrics[self.guild] = transport_metrics

                bitrate = int(res['bitrate'] / 1000)
                bitrate *= 0.9 if bitrate > 100 else 1

                while self.guild in guild_status and guild_status[self.guild] == Status.WAIT:
                    await asyncio.sleep(2)

                # Python 以 20ms 为唯一实时调度时钟；发送端不能再使用 -re 二次节流。
                command = f"{ffmpeg_bin} -loglevel warning -nostats -f s16le -ac {PCM_CHANNELS} -ar {PCM_SAMPLE_RATE} -i - -map 0:a:0 -acodec libopus -ab {bitrate}k -ac 2 -ar 48000 -f tee [select=a:f=rtp:ssrc={audio_ssrc}:payload_type={audio_pt}]{rtp_url}"
                if log_enabled:
                    logger.info(f'运行 ffmpeg 命令: {command}')
                p = await asyncio.create_subprocess_shell(
                    command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )

                async def terminate_process(process):
                    """终止并回收 FFmpeg 子进程，避免停止/跳过后留下孤儿进程。"""
                    if not process:
                        return
                    try:
                        if process.returncode is None:
                            process.kill()
                        await asyncio.wait_for(process.wait(), timeout=0.5)
                    except (ProcessLookupError, asyncio.TimeoutError):
                        pass

                volume_ramp = PCMVolumeRamp(get_guild_volume(self.guild))
                transport_pacer = PCMTransportPacer()

                async def send_transport_frame(frame: bytes):
                    """按绝对 20ms 时钟发送一帧；小延迟自动抵扣，大延迟不突发追赶。"""
                    if not p or not p.stdin:
                        raise RuntimeError('RTP 编码器不可用')
                    if len(frame) < PCM_FRAME_BYTES:
                        frame = frame + bytes(PCM_FRAME_BYTES - len(frame))
                    elif len(frame) > PCM_FRAME_BYTES:
                        frame = frame[:PCM_FRAME_BYTES]
                    lateness, resynced = await transport_pacer.wait()
                    output_frame = volume_ramp.process(frame, get_guild_volume(self.guild))
                    p.stdin.write(output_frame)
                    await p.stdin.drain()
                    sent_at = time.monotonic()
                    transport_metrics['frames_sent'] += 1
                    if not transport_metrics['first_sent_at']:
                        transport_metrics['first_sent_at'] = sent_at
                    transport_metrics['last_sent_at'] = sent_at
                    transport_metrics['last_lateness_ms'] = lateness * 1000
                    transport_metrics['max_lateness_ms'] = max(
                        float(transport_metrics['max_lateness_ms']),
                        lateness * 1000,
                    )
                    if lateness > 0.005:
                        transport_metrics['late_frames'] += 1
                    if resynced:
                        transport_metrics['resyncs'] += 1

                async def wait_for_queue_during_cooldown():
                    """队列暂空时维持 RTP，冷却结束仍无新歌才真正离开频道。"""
                    deadline = time.monotonic() + idle_disconnect_seconds
                    while time.monotonic() < deadline:
                        if guild_status.get(self.guild) == Status.STOP:
                            return False
                        queue = play_list.get(self.guild, {}).get('play_list', [])
                        if queue:
                            guild_status[self.guild] = Status.END
                            if log_enabled:
                                logger.info(f'退出冷却期间收到新歌曲，继续复用语音连接: {self.guild}')
                            return True
                        await send_transport_frame(PCM_SILENCE_FRAME)
                    return False

                while True:
                    await asyncio.sleep(0.5)
                    if self.guild in play_list:
                        if play_list[self.guild]['now_playing'] and not play_list[self.guild]['play_list']:
                            music_info = play_list[self.guild]['now_playing']
                        else:
                            if play_list[self.guild]['play_list']:
                                music_info = play_list[self.guild]['play_list'].pop(0)
                                # 每首新歌都必须重新经历 PREPARING(END) -> PLAYING。
                                # 上一首自然结束后状态仍可能是 PLAYING，若沿用会让新歌
                                # 在预热期间提前启动时间轴，也不会生成新的 start 时间。
                                guild_status[self.guild] = Status.END
                                music_info.pop('start', None)
                                play_list[self.guild]['now_playing'] = music_info
                                # 当前歌曲出队后，立即且只预加载新的队首歌曲。
                                schedule_next_preload(self.guild)
                            else:
                                if await wait_for_queue_during_cooldown():
                                    continue
                                break
                        
                        if isinstance(music_info, dict) and 'file' in music_info:
                            file = resolve_audio_source(music_info)
                            if not file:
                                if log_enabled:
                                    logger.warning('无法解析歌曲播放地址，跳过当前歌曲')
                                continue

                            extra_data = music_info.get('extra') or {}
                            extra_command = build_ffmpeg_input_options(extra_data)

                            ss_value = music_info.get('ss', 0)

                            # API 元数据已经包含时长时不再额外 HEAD/ffprobe 网络 URL；
                            # 旧逻辑的 HEAD 加整曲 ffmpeg 备用探测会阻塞首播数秒甚至整首歌。
                            try:
                                expected_duration = float(extra_data.get('duration', 0) or 0)
                            except (TypeError, ValueError):
                                expected_duration = 0

                            if expected_duration <= 0:
                                try:
                                    try:
                                        from ..config import FFPROBE_PATH
                                    except ImportError:
                                        from config import FFPROBE_PATH
                                    duration_process = await asyncio.create_subprocess_exec(
                                        FFPROBE_PATH,
                                        '-v', 'quiet',
                                        '-show_entries', 'format=duration',
                                        '-of', 'csv=p=0',
                                        file,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE,
                                    )
                                    stdout, _ = await asyncio.wait_for(
                                        duration_process.communicate(),
                                        timeout=8,
                                    )
                                    duration_text = stdout.decode('utf-8', errors='ignore').strip()
                                    if duration_text and duration_text != 'N/A':
                                        expected_duration = float(duration_text)
                                except asyncio.TimeoutError:
                                    try:
                                        duration_process.kill()
                                        await duration_process.wait()
                                    except Exception:
                                        pass
                                    if log_enabled:
                                        logger.warning(f'ffprobe 获取时长超时: {file[:80]}')
                                except Exception as exc:
                                    if log_enabled:
                                        logger.warning(f'ffprobe 获取时长失败: {exc}')

                            if expected_duration <= 0:
                                expected_duration = 180.0
                                if log_enabled:
                                    logger.info(f'缺少音源时长，暂用默认值: {expected_duration:.2f}s')
                            
                            # 将预期时长写入当前播放信息，供前端显示总时长
                            try:
                                if self.guild in play_list and play_list[self.guild]['now_playing']:
                                    play_list[self.guild]['now_playing']['duration'] = float(expected_duration)
                            except Exception:
                                pass

                            cache_key = get_queue_item_cache_key(self.guild, music_info)
                            cache_entry = None
                            with cache_lock:
                                cache_entry = audio_cache.get(cache_key)
                                if cache_entry:
                                    cache_entry['in_use'] = True
                                    cache_entry['timestamp'] = time.time()
                            cached_audio = cache_entry.get('data') if cache_entry else None
                            cache_complete = bool(cache_entry and cache_entry.get('complete'))
                            cached_duration = float(cache_entry.get('duration', 0)) if cache_entry else 0.0
                            continuation_offset = float(ss_value) + cached_duration

                            async def start_decoder(start_position):
                                decoder_file = resolve_audio_source(music_info) or file
                                command2 = (
                                    f'{ffmpeg_bin} -loglevel warning -nostats -reconnect 1 '
                                    f'-reconnect_streamed 1 -reconnect_delay_max 2 -timeout 30000000 '
                                    f'{extra_command} -ss {start_position} -i "{decoder_file}" '
                                    f'-acodec pcm_s16le '
                                    f'-ac {PCM_CHANNELS} -ar {PCM_SAMPLE_RATE} -f s16le -y -'
                                )
                                try:
                                    decoder = await asyncio.create_subprocess_shell(
                                        command2,
                                        stdin=asyncio.subprocess.DEVNULL,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE,
                                    )
                                    if decoder.returncode not in (None, 0):
                                        if log_enabled:
                                            logger.error(f'FFMPEG 解码进程启动失败: {decoder.returncode}')
                                        return None
                                    return decoder
                                except Exception as exc:
                                    if log_enabled:
                                        logger.error(f'创建 FFMPEG 解码进程失败: {exc}')
                                    return None

                            p2 = None
                            decoder_buffer = None
                            continuation_started = False

                            async def close_decoder():
                                """先停止后台读协程，再回收 FFmpeg，避免 stdout 读取任务泄漏。"""
                                nonlocal p2, decoder_buffer
                                old_buffer = decoder_buffer
                                old_decoder = p2
                                decoder_buffer = None
                                p2 = None
                                if old_buffer:
                                    await old_buffer.close()
                                await terminate_process(old_decoder)

                            async def open_decoder(start_position):
                                """启动持续预读的解码器；RTP 发送循环只消费内存缓冲。"""
                                nonlocal p2, decoder_buffer
                                p2 = await start_decoder(start_position)
                                if not p2:
                                    decoder_buffer = None
                                    return False
                                decoder_buffer = BufferedPCMDecoder(p2)
                                return True

                            if cached_audio:
                                if log_enabled:
                                    logger.info(
                                        f'使用下一首缓存: {cached_duration:.1f}s, '
                                        f'{len(cached_audio) / 1024 / 1024:.1f}MiB, complete={cache_complete}'
                                    )
                            else:
                                continuation_started = True
                                if not await open_decoder(ss_value):
                                    continue

                                # 首曲没有预缓存时，先给解码器留出固定握手时间并积累一段 PCM。
                                # 期间 RTP 仍持续发送静音，因此 KOOK 连接已就绪但歌曲时钟尚未启动。
                                warmup_started = time.monotonic()
                                warmup_deadline = warmup_started + max(
                                    startup_grace_seconds + 8.0,
                                    startup_buffer_seconds + 4.0,
                                )
                                warmup_target_bytes = startup_buffer_seconds * PCM_BYTES_PER_SECOND
                                skip_before_start = False
                                while time.monotonic() < warmup_deadline:
                                    state = guild_status.get(self.guild, Status.STOP)
                                    if state == Status.STOP:
                                        if self.guild in play_list:
                                            play_list[self.guild]['play_list'] = []
                                        await close_decoder()
                                        await terminate_process(p)
                                        return
                                    if state == Status.SKIP:
                                        guild_status[self.guild] = Status.END
                                        skip_before_start = True
                                        break

                                    elapsed = time.monotonic() - warmup_started
                                    buffered_bytes = decoder_buffer.buffered_bytes if decoder_buffer else 0
                                    decoder_finished = bool(decoder_buffer and decoder_buffer.eof)
                                    if (elapsed >= startup_grace_seconds
                                            and (buffered_bytes >= warmup_target_bytes or decoder_finished)):
                                        break
                                    await send_transport_frame(PCM_SILENCE_FRAME)

                                if skip_before_start:
                                    await close_decoder()
                                    if self.guild in play_list:
                                        play_list[self.guild]['now_playing'] = None
                                        schedule_next_preload(self.guild)
                                    continue
                                if log_enabled:
                                    ready_seconds = (
                                        decoder_buffer.buffered_bytes / PCM_BYTES_PER_SECOND
                                        if decoder_buffer else 0
                                    )
                                    logger.info(
                                        f'首播预热完成: 等待 {time.monotonic() - warmup_started:.2f}s, '
                                        f'已预读 {ready_seconds:.1f}s'
                                    )

                            # 音频播放逻辑 - 解码到编码管道
                            if log_enabled:
                                logger.info(f'开始播放音频，预期时长: {expected_duration:.2f} 秒')

                            # 设置播放状态
                            if self.guild not in guild_status:
                                guild_status[self.guild] = Status.END

                            if guild_status[self.guild] == Status.END:
                                # 只有预热完成后才发布 PLAYING 和起播时间；预热阶段的
                                # now_playing 只是“准备中的当前曲目”，不能启动时间轴。
                                guild_status[self.guild] = Status.PLAYING
                                music_info['start'] = time.time()
                                if original_loop:
                                    asyncio.run_coroutine_threadsafe(
                                        trigger_event(
                                            Status.START,
                                            PlayInfo(self.guild, self.channel_id, file, self.token, music_info.get('extra'))
                                        ),
                                        original_loop
                                    )
                                if log_enabled:
                                    logger.info(f'开始播放: {file}，服务器: {self.guild}')

                            chunk_size = PCM_FRAME_BYTES
                            total_audio = b''
                            consecutive_empty_reads = 0
                            # 解码读取也使用 20ms 轮询，这样网络缓冲期间仍能持续送静音，
                            # 不会让 RTP 编码器断粮。累计 10 秒无歌曲数据后才尝试续流。
                            max_empty_reads = max(1, int(10 / PCM_FRAME_DURATION))
                            decoder_restart_attempts = 0
                            max_decoder_restart_attempts = 2
                            source_audio_bytes_sent = 0

                            def current_media_position():
                                return float(ss_value) + source_audio_bytes_sent / PCM_BYTES_PER_SECOND

                            def update_media_position():
                                """歌曲时钟只由已经送出的歌曲采样推进，静音帧不参与。"""
                                if self.guild in play_list and play_list[self.guild]['now_playing']:
                                    play_list[self.guild]['now_playing']['ss'] = min(
                                        expected_duration,
                                        current_media_position(),
                                    )

                            async def restart_decoder(reason):
                                """上游在暂停或网络抖动后失效时，从已发送采样处精确续流。"""
                                nonlocal total_audio, consecutive_empty_reads
                                nonlocal continuation_started, decoder_restart_attempts

                                restart_position = current_media_position()
                                if (decoder_restart_attempts >= max_decoder_restart_attempts
                                        or restart_position >= expected_duration - 1.0):
                                    return False

                                decoder_restart_attempts += 1
                                if log_enabled:
                                    logger.warning(
                                        f'解码流{reason}，从 {restart_position:.3f}s 重建 '
                                        f'({decoder_restart_attempts}/{max_decoder_restart_attempts})'
                                    )

                                await close_decoder()

                                # 未满一帧的数据尚未计入歌曲时钟；丢弃后由新解码器重取，
                                # 避免旧半帧与 seek 后的新数据发生重复拼接。
                                total_audio = b''
                                consecutive_empty_reads = 0
                                if music_info.get('file', '').startswith(
                                    ('PLAYLIST_SONG:', 'MUSIC_SOURCE:')
                                ):
                                    # 提前 EOF 往往是临时播放 URL 已失效；强制重新解析，
                                    # 不能用同一条坏地址机械重试。
                                    music_info.pop('resolved_file', None)
                                    extra_data.pop('_resolved_url', None)
                                    extra_data.pop('_resolved_expires_at', None)
                                decoder_ready = await open_decoder(restart_position)
                                continuation_started = True
                                return decoder_ready

                            update_media_position()

                            try:
                                skip_song = False
                                audio_data_index = 0  # 缓存数据索引
                                
                                while True:
                                    state = guild_status.get(self.guild, Status.STOP)
                                    if p and p.returncode is not None:
                                        if log_enabled:
                                            logger.error(f'RTP 编码器异常退出: {p.returncode}')
                                        break

                                    # 控制命令必须在读取、消费下一帧歌曲数据之前处理。
                                    if state == Status.STOP:
                                        if self.guild in play_list:
                                            play_list[self.guild]['play_list'] = []
                                        await close_decoder()
                                        await terminate_process(p)
                                        return
                                    if state == Status.SKIP:
                                        guild_status[self.guild] = Status.END
                                        skip_song = True
                                        await close_decoder()
                                        break
                                    if state == Status.PAUSE:
                                        # 仅推进 RTP 传输时钟，不推进歌曲时钟或解码游标。
                                        await send_transport_frame(PCM_SILENCE_FRAME)
                                        continue

                                    new_audio = None
                                    
                                    # 缓存到达提前量时启动续流，并让后台读协程先积累数据。
                                    if cached_audio:
                                        remaining_cache = len(cached_audio) - audio_data_index
                                        if (not cache_complete and not continuation_started
                                                and remaining_cache <= continuation_lead_seconds * PCM_BYTES_PER_SECOND):
                                            continuation_started = True
                                            await open_decoder(continuation_offset)
                                        if audio_data_index < len(cached_audio):
                                            end_index = min(audio_data_index + chunk_size, len(cached_audio))
                                            new_audio = cached_audio[audio_data_index:end_index]
                                            audio_data_index = end_index

                                            if audio_data_index >= len(cached_audio):
                                                if log_enabled:
                                                    logger.info('缓存播放完毕，切换到续流解码')
                                                cached_audio = None
                                                if not cache_complete and not decoder_buffer:
                                                    await open_decoder(continuation_offset)
                                        else:
                                            cached_audio = None
                                    elif decoder_buffer:
                                        new_audio = await decoder_buffer.read(PCM_FRAME_DURATION)
                                        if new_audio is None:
                                            consecutive_empty_reads += 1
                                            if consecutive_empty_reads >= max_empty_reads:
                                                if await restart_decoder('连续 10 秒无数据'):
                                                    await send_transport_frame(PCM_SILENCE_FRAME)
                                                    continue
                                                if log_enabled:
                                                    logger.warning(f'解码流连续 10 秒无数据且无法恢复: {file}')
                                                break
                                            # 上游短暂抖动只消耗预读缓冲；真正耗尽时才补静音。
                                            await send_transport_frame(PCM_SILENCE_FRAME)
                                            continue
                                        if new_audio == b'':
                                            return_code = p2.returncode if p2 else None
                                            if (current_media_position() < expected_duration - 1.0
                                                    and await restart_decoder(
                                                        f'提前结束（{return_code}）'
                                                    )):
                                                await send_transport_frame(PCM_SILENCE_FRAME)
                                                continue
                                            break
                                        else:
                                            consecutive_empty_reads = 0
                                    else:
                                        # 没有缓存也没有进程，结束播放
                                        break

                                    if new_audio:
                                        total_audio += new_audio

                                        # 只按完整 20ms PCM 帧发送，控制与进度均在帧边界生效。
                                        while len(total_audio) >= chunk_size:
                                            state = guild_status.get(self.guild, Status.STOP)
                                            if state == Status.PAUSE:
                                                break
                                            if state == Status.SKIP:
                                                guild_status[self.guild] = Status.END
                                                skip_song = True
                                                await close_decoder()
                                                break
                                            if state == Status.STOP:
                                                if self.guild in play_list:
                                                    play_list[self.guild]['play_list'] = []
                                                await close_decoder()
                                                await terminate_process(p)
                                                return
                                            audio_slice = total_audio[:chunk_size]
                                            total_audio = total_audio[chunk_size:]
                                            if p and p.stdin:
                                                try:
                                                    await send_transport_frame(audio_slice)
                                                    source_audio_bytes_sent += len(audio_slice)
                                                    update_media_position()
                                                except Exception as e:
                                                    if log_enabled:
                                                        logger.error(f'音频写入异常: {e}', exc_info=True)
                                                        logger.error(f'写入异常详情 - 编码进程状态: {p.returncode if p else "None"}')
                                                        logger.error(f'写入异常详情 - 音频数据大小: {len(audio_slice)}')
                                                        logger.error(f'写入异常详情 - 总音频缓存大小: {len(total_audio)}')
                                                    break
                                        # 若标记跳过，结束本曲读循环
                                        if skip_song:
                                            break

                                # 完整歌曲末尾不足一个 20ms 帧时补静音发送，但只计算真实歌曲字节。
                                if total_audio and not skip_song and p and p.stdin:
                                    while True:
                                        final_state = guild_status.get(self.guild, Status.STOP)
                                        if final_state == Status.PAUSE:
                                            await send_transport_frame(PCM_SILENCE_FRAME)
                                            continue
                                        if final_state == Status.SKIP:
                                            guild_status[self.guild] = Status.END
                                            skip_song = True
                                        elif final_state == Status.STOP:
                                            if self.guild in play_list:
                                                play_list[self.guild]['play_list'] = []
                                            await close_decoder()
                                            await terminate_process(p)
                                            return
                                        else:
                                            final_source_bytes = len(total_audio)
                                            await send_transport_frame(total_audio)
                                            source_audio_bytes_sent += final_source_bytes
                                            update_media_position()
                                        break
                            except Exception as e:
                                if log_enabled:
                                    logger.error(f'音频播放异常: {e}', exc_info=True)
                                    # 添加详细的错误诊断信息
                                    logger.error(f'错误详情 - 文件: {file}')
                                    logger.error(f'错误详情 - 服务器: {self.guild}')
                                    logger.error(f'错误详情 - 频道: {self.channel_id}')
                                    logger.error(f'错误详情 - 进程状态: p2={p2 is not None}, p={p is not None}')
                                    if p2:
                                        logger.error(f'错误详情 - FFMPEG进程返回码: {p2.returncode}')
                                        if p2.stderr:
                                            try:
                                                stderr_data = await p2.stderr.read()
                                                if stderr_data:
                                                    stderr_text = stderr_data.decode('utf-8', errors='ignore')
                                                    logger.error(f'错误详情 - FFMPEG错误输出: {stderr_text[:1000]}')
                                            except Exception as stderr_e:
                                                logger.error(f'错误详情 - 读取stderr失败: {stderr_e}')
                                    if p:
                                        logger.error(f'错误详情 - 编码进程返回码: {p.returncode}')
                                        if p.stderr:
                                            try:
                                                stderr_data = await p.stderr.read()
                                                if stderr_data:
                                                    stderr_text = stderr_data.decode('utf-8', errors='ignore')
                                                    logger.error(f'错误详情 - 编码器错误输出: {stderr_text[:1000]}')
                                            except Exception as stderr_e:
                                                logger.error(f'错误详情 - 读取编码器stderr失败: {stderr_e}')
                            finally:
                                await close_decoder()
                                if cache_entry:
                                    with cache_lock:
                                        live_entry = audio_cache.get(cache_key)
                                        if live_entry:
                                            live_entry['in_use'] = False
                            
                            # 播放完成后清理
                            if log_enabled:
                                logger.info(f'歌曲播放完成: {file}')
                            
                            # 记录历史，并根据播放模式安排下一首。
                            if self.guild in play_list and play_list[self.guild]['now_playing']:
                                finished_song = play_list[self.guild]['now_playing'].copy()
                                history = play_history.setdefault(self.guild, [])
                                history.append(finished_song.copy())
                                if len(history) > 50:
                                    del history[:-50]

                                mode = guild_play_mode.get(self.guild, 'order')
                                if mode == 'repeat-one' and not skip_song:
                                    replay_song = finished_song.copy()
                                    replay_song['ss'] = 0
                                    replay_song.pop('start', None)
                                    replay_song.pop('duration', None)
                                    play_list[self.guild]['play_list'].insert(0, replay_song)
                                elif mode == 'shuffle' and len(play_list[self.guild]['play_list']) > 1:
                                    random.shuffle(play_list[self.guild]['play_list'])

                                play_list[self.guild]['now_playing'] = None
                                schedule_next_preload(self.guild)
                            
                            # 强制 GC 只允许发生在歌曲结束后的切换阶段，不能打断 RTP 热循环。
                            run_transition_maintenance(self.guild)
                            
                            # 编码器保持到外层 3 秒冷却结束，期间新歌曲可直接复用连接。
                            if self.guild in play_list and len(play_list[self.guild]['play_list']) == 0:
                                if log_enabled:
                                    logger.info(
                                        f'播放列表暂空，进入 {idle_disconnect_seconds:.1f}s '
                                        f'退出冷却: {self.guild}'
                                    )
                            else:
                                # 还有更多歌曲，继续播放下一首
                                if log_enabled:
                                    logger.info(f'准备播放下一首歌曲，服务器: {self.guild}')
                    else:
                        break
                await terminate_process(p)
        except Exception as e:
            if log_enabled:
                logger.error(f'推流过程中出现错误: {str(e)}', exc_info=True)

    async def keepalive(self):
        while True:
            await asyncio.sleep(45)
            # 正常播放持续发送 RTP，不需要 REST 保活。暂停时保留一次防御性保活，
            # 即使请求失败也不能结束 keepalive 任务并连带取消正在运行的 push 任务。
            if self.channel_id and guild_status.get(self.guild) == Status.PAUSE:
                try:
                    await self.requestor.keep_alive(self.channel_id)
                    if log_enabled:
                        logger.info(f'暂停期间发送语音保活请求，频道: {self.channel_id}')
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if log_enabled:
                        logger.warning(f'暂停期间语音保活失败，频道: {self.channel_id}，错误: {exc}')

async def start():
    global original_loop
    original_loop = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(1000)

from typing import Coroutine, TypeVar, Any
T = TypeVar('T')

async def run_async(task: CoroutineType[Any, Any, T], timeout=10) -> T:
    if original_loop:
        return asyncio.run_coroutine_threadsafe(task, original_loop).result(timeout=timeout)
    return None

def run():
    asyncio.run(start())
