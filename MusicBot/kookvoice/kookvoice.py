import asyncio
import os
import threading
import time
import logging
import gc
import psutil
import random
from enum import Enum, unique
from typing import Dict, Union, List, Any, Optional, Coroutine as CoroutineType
from asyncio import AbstractEventLoop
try:
    from .requestor import VoiceRequestor
except ImportError:
    from requestor import VoiceRequestor

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

# 音频缓存和预加载机制
audio_cache = {}  # 缓存已解码的音频数据
preload_queue = {}  # 预加载队列
cache_max_size = 3  # 最大缓存歌曲数量
cache_cleanup_interval = 300  # 缓存清理间隔（秒）
last_cache_cleanup = time.time()

# 歌曲播放计数和清理机制
song_play_count = {}  # 每个服务器的歌曲播放计数
cleanup_threshold = 3  # 播放多少首歌曲后清理（可配置为2-4首）

def cleanup_audio_cache():
    """清理音频缓存，释放内存"""
    global audio_cache, last_cache_cleanup
    current_time = time.time()
    
    if current_time - last_cache_cleanup > cache_cleanup_interval:
        # 清理过期的缓存
        expired_keys = []
        for key, cache_data in audio_cache.items():
            if current_time - cache_data.get('timestamp', 0) > cache_cleanup_interval:
                expired_keys.append(key)
        
        for key in expired_keys:
            del audio_cache[key]
            if log_enabled:
                logger.info(f'清理过期音频缓存: {key}')
        
        # 如果缓存仍然过大，清理最旧的缓存
        if len(audio_cache) > cache_max_size:
            sorted_cache = sorted(audio_cache.items(), key=lambda x: x[1].get('timestamp', 0))
            for key, _ in sorted_cache[:len(audio_cache) - cache_max_size]:
                del audio_cache[key]
                if log_enabled:
                    logger.info(f'清理超量音频缓存: {key}')
        
        last_cache_cleanup = current_time
        
        # 强制垃圾回收
        gc.collect()
        
        if log_enabled:
            memory_info = psutil.Process().memory_info()
            logger.info(f'内存使用情况: RSS={memory_info.rss / 1024 / 1024:.2f}MB, VMS={memory_info.vms / 1024 / 1024:.2f}MB')

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
        for key, cache_data in audio_cache.items():
            if current_time - cache_data.get('timestamp', 0) > 600:  # 10分钟
                expired_keys.append(key)
        
        # 删除过期缓存
        for key in expired_keys:
            del audio_cache[key]
        
        # 如果缓存仍然过多，清理最旧的
        if len(audio_cache) > cache_max_size:
            sorted_cache = sorted(audio_cache.items(), key=lambda x: x[1].get('timestamp', 0))
            excess_count = len(audio_cache) - cache_max_size
            for i in range(excess_count):
                del audio_cache[sorted_cache[i][0]]
        
        # 强制垃圾回收
        gc.collect()
        
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

def get_cleanup_stats():
    """获取清理统计信息"""
    return {
        'song_play_count': song_play_count.copy(),
        'cleanup_threshold': cleanup_threshold,
        'cache_count': len(audio_cache),
        'cache_max_size': cache_max_size
    }

def get_cache_key(file_path, ss_value=0):
    """生成缓存键"""
    return f"{file_path}:{ss_value}"

async def preload_audio(file_path, ss_value=0, extra_command=''):
    """预加载音频数据到缓存"""
    cache_key = get_cache_key(file_path, ss_value)
    
    if cache_key in audio_cache:
        return audio_cache[cache_key]
    
    try:
        if log_enabled:
            logger.info(f'开始预加载音频: {file_path}')
        
        # 使用FFMPEG预解码音频
        command = f'{ffmpeg_bin} -nostats -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -timeout 30000000 -ss {ss_value} -i "{file_path}" {extra_command} -filter:a volume=0.4 -acodec pcm_s16le -ac 2 -ar 48000 -f wav -y -'
        
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # 读取音频数据
        audio_data = b''
        chunk_size = 96000
        
        while True:
            try:
                chunk = await asyncio.wait_for(process.stdout.read(chunk_size), timeout=5.0)
                if not chunk:
                    break
                audio_data += chunk
                
                # 限制预加载大小，避免内存占用过大
                if len(audio_data) > 10 * 1024 * 1024:  # 10MB限制
                    break
                    
            except asyncio.TimeoutError:
                break
        
        # 等待进程结束
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            process.kill()
        
        # 缓存音频数据
        audio_cache[cache_key] = {
            'data': audio_data,
            'timestamp': time.time(),
            'size': len(audio_data)
        }
        
        if log_enabled:
            logger.info(f'预加载完成: {file_path}, 大小: {len(audio_data) / 1024 / 1024:.2f}MB')
        
        return audio_cache[cache_key]
        
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
        # 检查是否是歌单歌曲标记，如果是则跳过文件存在检查
        if not music.startswith("PLAYLIST_SONG:"):
            if 'http' not in music:
                if not os.path.exists(music):
                    raise ValueError('文件不存在')

        play_list[self.guild_id]['voice_channel'] = self.voice_channel_id
        play_list[self.guild_id]['play_list'].append({'file': music, 'ss': 0, 'extra': extra_data})
        
        # 启动预加载任务（在后台线程中运行）
        if len(play_list[self.guild_id]['play_list']) <= 2:  # 只预加载前两首
            # 在后台线程中运行同步预加载
            import threading
            preload_thread = threading.Thread(target=self._preload_next_song_sync, args=(music, extra_data))
            preload_thread.daemon = True
            preload_thread.start()
        
        if log_enabled:
            logger.info(f'添加音乐到播放列表，服务器: {self.guild_id}，音乐: {music}')
        if self.guild_id in guild_status and guild_status[self.guild_id] == Status.WAIT:
            guild_status[self.guild_id] = Status.END
        if need_start:
            if play_list[self.guild_id]['play_list']:
                PlayHandler(self.guild_id, self.token).start()
            elif ((self.guild_id not in playlist_handle_status
                   or (not playlist_handle_status[self.guild_id]))
                  and play_list[self.guild_id]['play_list']):
                PlayHandler(self.guild_id, self.token).start()
    
    def _preload_next_song_sync(self, music: str, extra_data: dict):
        """同步预加载下一首歌曲"""
        try:
            # 清理缓存
            cleanup_audio_cache()
            
            # 如果是歌单歌曲，先获取URL
            if music.startswith("PLAYLIST_SONG:"):
                # 歌单歌曲的预加载在播放时进行
                return
            
            # 预加载音频数据（使用同步方式）
            extra_command = ''
            if extra_data and isinstance(extra_data, dict):
                extra_command = extra_data.get('extra_command', '')
            
            # 使用同步方式预加载
            cache_key = get_cache_key(music, 0)
            if cache_key not in audio_cache:
                if log_enabled:
                    logger.info(f'开始同步预加载音频: {music}')
                
                # 使用subprocess同步执行FFMPEG
                import subprocess
                command = f'{ffmpeg_bin} -nostats -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -timeout 30000000 -i "{music}" {extra_command} -filter:a volume={get_guild_volume(self.guild_id)} -acodec pcm_s16le -ac 2 -ar 48000 -f wav -y -'
                
                try:
                    # 限制预加载大小
                    process = subprocess.Popen(
                        command,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    # 读取前10MB数据
                    audio_data = b''
                    chunk_size = 96000
                    max_size = 10 * 1024 * 1024  # 10MB
                    
                    while len(audio_data) < max_size:
                        chunk = process.stdout.read(chunk_size)
                        if not chunk:
                            break
                        audio_data += chunk
                    
                    # 终止进程
                    process.terminate()
                    process.wait(timeout=2)
                    
                    # 缓存音频数据
                    if audio_data:
                        audio_cache[cache_key] = {
                            'data': audio_data,
                            'timestamp': time.time(),
                            'size': len(audio_data)
                        }
                        if log_enabled:
                            logger.info(f'同步预加载完成: {music}, 大小: {len(audio_data) / 1024 / 1024:.2f}MB')
                    
                except Exception as e:
                    if log_enabled:
                        logger.error(f'同步预加载失败: {music}, 错误: {e}')
            
        except Exception as e:
            if log_enabled:
                logger.error(f'预加载歌曲失败: {music}, 错误: {e}')

    def stop(self):
        global guild_status, playlist_handle_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        guild_status[self.guild_id] = Status.STOP
        if log_enabled:
            logger.info(f'停止播放，服务器: {self.guild_id}')

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
        guild_status[self.guild_id] = Status.SKIP
        if log_enabled:
            logger.info(f'跳过了 {skip_amount} 首歌曲，服务器: {self.guild_id}')

    def pause(self):
        global guild_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
        guild_status[self.guild_id] = Status.PAUSE
        if log_enabled:
            logger.info(f'暂停播放，服务器: {self.guild_id}')

    def resume(self):
        global guild_status
        if self.guild_id not in play_list:
            raise ValueError('该服务器没有正在播放的歌曲')
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

        # 可选地取消未完成的任务
        for task in pending:
            task.cancel()

        # 触发 task3 开始
        start_event.set()
        await task3

    async def stop(self, start_event):
        await start_event.wait()
        global playlist_handle_status
        if self.guild in play_list:
            del play_list[self.guild]
        if self.guild in playlist_handle_status and playlist_handle_status[self.guild]:
            playlist_handle_status[self.guild] = False
        try:
            await self.requestor.leave(self.channel_id)
        except:
            pass
        if log_enabled:
            logger.info(f'停止并清理，服务器: {self.guild}')

    async def push(self):
        global playlist_handle_status
        playlist_handle_status[self.guild] = True
        try:
            await asyncio.sleep(1)
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

                bitrate = int(res['bitrate'] / 1000)
                bitrate *= 0.9 if bitrate > 100 else 1

                while self.guild in guild_status and guild_status[self.guild] == Status.WAIT:
                    await asyncio.sleep(2)

                command = f"{ffmpeg_bin} -re -loglevel level+info -nostats -f wav -i - -map 0:a:0 -acodec libopus -ab {bitrate}k -ac 2 -ar 48000 -filter:a volume=1.0 -f tee [select=a:f=rtp:ssrc={audio_ssrc}:payload_type={audio_pt}]{rtp_url}"
                if log_enabled:
                    logger.info(f'运行 ffmpeg 命令: {command}')
                p = await asyncio.create_subprocess_shell(
                    command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )

                while True:
                    await asyncio.sleep(0.5)
                    if self.guild in play_list:
                        if play_list[self.guild]['now_playing'] and not play_list[self.guild]['play_list']:
                            music_info = play_list[self.guild]['now_playing']
                        else:
                            if play_list[self.guild]['play_list']:
                                music_info = play_list[self.guild]['play_list'].pop(0)
                                music_info['start'] = time.time()
                                play_list[self.guild]['now_playing'] = music_info
                            else:
                                break
                        
                        if isinstance(music_info, dict) and 'file' in music_info:
                            file = music_info['file']

                            # 检查是否是歌单歌曲标记，如果是则实时获取URL
                            if file.startswith("PLAYLIST_SONG:"):
                                try:
                                    # 解析歌单歌曲标记
                                    parts = file.split(":")
                                    if len(parts) >= 4:
                                        song_id = parts[1]
                                        song_name = parts[2]
                                        artist_name = parts[3]
                                        
                                        if log_enabled:
                                            logger.info(f'🎵 实时获取歌单歌曲URL: {song_name} - {artist_name}')
                                        
                                        # 实时获取歌曲URL
                                        import requests
                                        # 尝试加载主程序的构建请求头（含Cookie）
                                        try:
                                            from ..utils import build_headers as _kv_build_headers
                                        except Exception:
                                            def _kv_build_headers(extra: dict | None = None):
                                                headers = {
                                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36",
                                                }
                                                try:
                                                    import os
                                                    cookie_path = os.path.join(os.path.dirname(__file__), "..", "Cookie", "cookie.txt")
                                                    cookie_path = os.path.abspath(cookie_path)
                                                    if os.path.exists(cookie_path):
                                                        with open(cookie_path, "r", encoding="utf-8") as f:
                                                            cookie_str = f.read().strip()
                                                            if cookie_str:
                                                                headers["Cookie"] = cookie_str
                                                except Exception:
                                                    pass
                                                if extra:
                                                    headers.update(extra)
                                                return headers
                                        try:
                                            from ..config import MUSIC_API_BASE
                                        except ImportError:
                                            from config import MUSIC_API_BASE
                                        
                                        url_api = f"{MUSIC_API_BASE}/song/url?id={song_id}"
                                        url_res = requests.get(url_api, timeout=15, headers=_kv_build_headers())
                                        
                                        if url_res.status_code == 200:
                                            url_data = url_res.json()
                                            if url_data.get('data') and url_data['data'][0].get('url'):
                                                file = url_data['data'][0]['url']
                                                if log_enabled:
                                                    logger.info(f'✅ 实时获取到URL: {song_name} - {artist_name}')
                                            else:
                                                if log_enabled:
                                                    logger.warning(f'❌ 无法获取播放链接: {song_name} - {artist_name}')
                                                continue  # 跳过这首歌
                                        else:
                                            if log_enabled:
                                                logger.error(f'❌ 获取URL失败: {song_name} - {artist_name}')
                                            continue  # 跳过这首歌
                                except Exception as e:
                                    if log_enabled:
                                        logger.error(f'❌ 实时获取URL异常: {e}')
                                    continue  # 跳过这首歌

                            extra_command = ''
                            if 'extra' in music_info and music_info['extra']:
                                extra_data = music_info['extra']
                                extra_command = extra_data.get('extra_command', '')

                                def pack_command(full_command, name, value):
                                    if value:
                                        full_command += f' -{name} "{value}"'
                                    return full_command

                                if isinstance(extra_data, dict):
                                    extra_command = pack_command(extra_command, 'headers', extra_data.get('header'))
                                    extra_command = pack_command(extra_command, 'cookies', extra_data.get('cookies'))
                                    extra_command = pack_command(extra_command, 'user_agent', extra_data.get('user_agent'))
                                    extra_command = pack_command(extra_command, 'referer', extra_data.get('referer'))

                            ss_value = music_info.get('ss', 0)
                            
                            # 检查网络连接状态（仅对HTTP URL）
                            if file.startswith('http'):
                                if log_enabled:
                                    logger.info(f'检查网络连接状态: {file[:50]}...')
                                try:
                                    import requests
                                    # 发送HEAD请求检查URL是否可访问
                                    response = requests.head(file, timeout=5, allow_redirects=True)
                                    if response.status_code not in [200, 206]:  # 206是部分内容响应
                                        if log_enabled:
                                            logger.warning(f'URL可能不可访问，状态码: {response.status_code}')
                                except Exception as e:
                                    if log_enabled:
                                        logger.warning(f'网络连接检查失败: {e}')
                            
                            # 获取音频时长
                            if log_enabled:
                                logger.info(f'获取音频时长: {file}')
                            
                            audio_duration = 0
                            try:
                                # 使用ffprobe获取音频时长
                                try:
                                    from ..config import FFPROBE_PATH
                                except ImportError:
                                    from config import FFPROBE_PATH
                                duration_command = f'"{FFPROBE_PATH}" -v quiet -show_entries format=duration -of csv=p=0 "{file}"'
                                
                                if log_enabled:
                                    logger.info(f'执行时长获取命令: {duration_command}')
                                
                                duration_process = await asyncio.create_subprocess_shell(
                                    duration_command,
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=asyncio.subprocess.PIPE
                                )
                                stdout, stderr = await duration_process.communicate()
                                
                                if stdout:
                                    duration_text = stdout.decode('utf-8', errors='ignore').strip()
                                    if duration_text and duration_text != 'N/A':
                                        try:
                                            audio_duration = float(duration_text)
                                            if log_enabled:
                                                logger.info(f'音频时长: {audio_duration:.2f} 秒')
                                        except ValueError:
                                            if log_enabled:
                                                logger.warning(f'无法解析音频时长: {duration_text}')
                                    else:
                                        if log_enabled:
                                            logger.warning(f'ffprobe返回空时长: {duration_text}')
                                else:
                                    if log_enabled:
                                        logger.warning(f'ffprobe无输出，尝试备用方法')
                                    
                                    # 备用方法：使用ffmpeg获取时长
                                    backup_command = f'{ffmpeg_bin} -i "{file}" {extra_command} -f null - 2>&1'
                                    backup_process = await asyncio.create_subprocess_shell(
                                        backup_command,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE
                                    )
                                    _, stderr = await backup_process.communicate()
                                    stderr_text = stderr.decode('utf-8', errors='ignore')
                                    
                                    # 解析音频时长
                                    import re
                                    duration_match = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})', stderr_text)
                                    if duration_match:
                                        hours = int(duration_match.group(1))
                                        minutes = int(duration_match.group(2))
                                        seconds = int(duration_match.group(3))
                                        centiseconds = int(duration_match.group(4))
                                        audio_duration = hours * 3600 + minutes * 60 + seconds + centiseconds / 100
                                        if log_enabled:
                                            logger.info(f'备用方法获取音频时长: {audio_duration:.2f} 秒')
                                    else:
                                        if log_enabled:
                                            logger.warning(f'备用方法也无法获取音频时长')
                                            
                            except Exception as e:
                                if log_enabled:
                                    logger.error(f'获取音频时长失败: {e}')
                                audio_duration = 0
                            
                            expected_duration = audio_duration
                            
                            # 如果无法获取音频时长，设置默认时长（3分钟）
                            if expected_duration <= 0:
                                expected_duration = 180.0  # 3分钟
                                if log_enabled:
                                    logger.info(f'使用默认音频时长: {expected_duration:.2f} 秒')
                            
                            # 将预期时长写入当前播放信息，供前端显示总时长
                            try:
                                if self.guild in play_list and play_list[self.guild]['now_playing']:
                                    play_list[self.guild]['now_playing']['duration'] = float(expected_duration)
                            except Exception:
                                pass

                            # 检查是否有缓存的音频数据
                            cache_key = get_cache_key(file, ss_value)
                            cached_audio = None
                            
                            if cache_key in audio_cache:
                                cached_audio = audio_cache[cache_key]['data']
                                if log_enabled:
                                    logger.info(f'使用缓存音频数据: {file}, 大小: {len(cached_audio) / 1024 / 1024:.2f}MB')
                            
                            # 如果没有缓存，使用FFMPEG解码
                            if not cached_audio:
                                # FFMPEG命令 - 增加网络稳定性参数
                                command2 = f'{ffmpeg_bin} -nostats -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -timeout 30000000 -ss {ss_value} -i "{file}" {extra_command} -filter:a volume={get_guild_volume(self.guild)} -acodec pcm_s16le -ac 2 -ar 48000 -f wav -y -'
                                if log_enabled:
                                    logger.info(f'正在播放文件: {file}')
                                    logger.info(f'FFMPEG命令: {command2}')
                                
                                try:
                                    p2 = await asyncio.create_subprocess_shell(
                                        command2,
                                        stdin=asyncio.subprocess.DEVNULL,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.PIPE
                                    )
                                    
                                    # 等待一小段时间检查进程是否正常启动
                                    await asyncio.sleep(0.1)
                                    if p2.returncode is not None:
                                        if log_enabled:
                                            logger.error(f'FFMPEG进程启动失败，返回码: {p2.returncode}')
                                            if p2.stderr:
                                                try:
                                                    stderr_data = await p2.stderr.read()
                                                    if stderr_data:
                                                        stderr_text = stderr_data.decode('utf-8', errors='ignore')
                                                        logger.error(f'FFMPEG启动错误: {stderr_text[:1000]}')
                                                except Exception as e:
                                                    logger.error(f'读取FFMPEG启动错误失败: {e}')
                                        continue  # 跳过这首歌曲
                                        
                                except Exception as e:
                                    if log_enabled:
                                        logger.error(f'创建FFMPEG进程失败: {e}')
                                    continue  # 跳过这首歌曲
                            else:
                                p2 = None  # 使用缓存数据，不需要FFMPEG进程

                            # 音频播放逻辑 - 解码到编码管道
                            if log_enabled:
                                logger.info(f'开始播放音频，预期时长: {expected_duration:.2f} 秒')

                            # 记录播放开始时间
                            first_music_start_time = time.time()
                            
                            # 进程健康检查
                            def check_process_health():
                                """检查进程健康状态"""
                                if p2 and p2.returncode is not None:
                                    if log_enabled:
                                        logger.warning(f'FFMPEG进程异常退出，返回码: {p2.returncode}')
                                    return False
                                if p and p.returncode is not None:
                                    if log_enabled:
                                        logger.warning(f'编码进程异常退出，返回码: {p.returncode}')
                                    return False
                                return True

                            # 设置播放状态
                            if self.guild not in guild_status:
                                guild_status[self.guild] = Status.END

                            if guild_status[self.guild] == Status.END:
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
                                guild_status[self.guild] = Status.PLAYING

                            chunk_size = 96000
                            total_audio = b''
                            last_write_time = 0.0
                            consecutive_empty_reads = 0
                            max_empty_reads = 10  # 最大连续空读取次数

                            try:
                                skip_song = False
                                audio_data_index = 0  # 缓存数据索引
                                
                                while True:
                                    # 检查进程健康状态
                                    if not check_process_health():
                                        if log_enabled:
                                            logger.error(f'进程健康检查失败，停止播放: {file}')
                                        break
                                    
                                    new_audio = None
                                    
                                    # 优先使用缓存数据
                                    if cached_audio:
                                        if audio_data_index < len(cached_audio):
                                            end_index = min(audio_data_index + chunk_size, len(cached_audio))
                                            new_audio = cached_audio[audio_data_index:end_index]
                                            audio_data_index = end_index
                                            
                                            if audio_data_index >= len(cached_audio):
                                                # 缓存数据播放完毕
                                                if log_enabled:
                                                    logger.info(f'缓存音频播放完成: {file}')
                                                break
                                        else:
                                            break
                                    elif p2 and p2.stdout:
                                        try:
                                            # 使用超时读取，避免无限阻塞
                                            new_audio = await asyncio.wait_for(
                                                p2.stdout.read(chunk_size), 
                                                timeout=2.0
                                            )
                                        except asyncio.TimeoutError:
                                            # 读取超时，检查进程状态
                                            if p2.returncode is not None:
                                                # 进程已退出
                                                if log_enabled:
                                                    logger.warning(f'解码进程已退出: {file}, 返回码: {p2.returncode}')
                                                    # 读取进程错误输出
                                                    if p2.stderr:
                                                        try:
                                                            stderr_data = await p2.stderr.read()
                                                            if stderr_data:
                                                                stderr_text = stderr_data.decode('utf-8', errors='ignore')
                                                                logger.warning(f'解码进程错误输出: {stderr_text[:500]}')
                                                        except Exception as e:
                                                            logger.warning(f'读取解码进程错误输出失败: {e}')
                                                break
                                            # 进程仍在运行，继续尝试读取
                                            consecutive_empty_reads += 1
                                            if consecutive_empty_reads >= max_empty_reads:
                                                if log_enabled:
                                                    logger.warning(f'连续{max_empty_reads}次读取超时，可能网络问题: {file}')
                                                    logger.warning(f'当前进程状态: 返回码={p2.returncode}, 是否运行中={p2.returncode is None}')
                                                break
                                            continue

                                        if not new_audio:
                                            consecutive_empty_reads += 1
                                            if consecutive_empty_reads >= max_empty_reads:
                                                # 打印解码器stderr，帮助定位
                                                if p2.stderr:
                                                    try:
                                                        err_text = (await p2.stderr.read()).decode('utf-8', errors='ignore').strip()
                                                        if err_text and log_enabled:
                                                            logger.warning(f'解码进程stderr: {err_text[:500]}')
                                                    except Exception:
                                                        pass

                                                # 写入剩余缓存
                                                if total_audio and p and p.stdin:
                                                    try:
                                                        p.stdin.write(total_audio)
                                                        await p.stdin.drain()
                                                        if log_enabled:
                                                            logger.info(f'写入剩余音频数据: {len(total_audio)} 字节')
                                                    except Exception as e:
                                                        if log_enabled:
                                                            logger.error(f'写入剩余音频数据异常: {e}')

                                                # 若播放时长不足，继续等待凑够最小时长
                                                actual_duration = max(0.0, time.time() - first_music_start_time)
                                                min_play_time = 30.0
                                                target_duration = max(expected_duration, min_play_time)
                                                if actual_duration < target_duration:
                                                    wait_sec = target_duration - actual_duration
                                                    if log_enabled:
                                                        logger.info(f'等待剩余时间: {wait_sec:.2f} 秒 (目标时长: {target_duration:.2f} 秒)')
                                                    await asyncio.sleep(wait_sec)

                                                if log_enabled:
                                                    logger.info(f'音频播放完成: {file}')
                                                break
                                        else:
                                            # 重置连续空读取计数
                                            consecutive_empty_reads = 0
                                    else:
                                        # 没有缓存也没有进程，结束播放
                                        break

                                    if new_audio:
                                        total_audio += new_audio

                                        # 成块写入编码器stdin
                                        while len(total_audio) >= chunk_size:
                                            audio_slice = total_audio[:chunk_size]
                                            total_audio = total_audio[chunk_size:]
                                            if p and p.stdin:
                                                try:
                                                    now = time.time()
                                                    if last_write_time > 0:
                                                        elapsed = now - last_write_time
                                                        if elapsed < 0.02:
                                                            await asyncio.sleep(0.02 - elapsed)
                                                    # 暂停控制：当状态为 PAUSE 时，阻塞写入，直到恢复
                                                    if self.guild in guild_status and guild_status[self.guild] == Status.PAUSE:
                                                        while self.guild in guild_status and guild_status[self.guild] == Status.PAUSE:
                                                            await asyncio.sleep(0.1)
                                                    p.stdin.write(audio_slice)
                                                    await p.stdin.drain()
                                                    last_write_time = time.time()

                                                    # 更新前端显示进度
                                                    if self.guild in play_list and play_list[self.guild]['now_playing']:
                                                        play_list[self.guild]['now_playing']['ss'] = last_write_time - first_music_start_time

                                                    # 中断控制
                                                    if self.guild in guild_status:
                                                        state = guild_status[self.guild]
                                                        if state == Status.SKIP:
                                                            if log_enabled:
                                                                logger.info(f'跳过当前歌曲: {file}')
                                                            # 重置状态并标记跳过当前歌曲，不退出整个推流
                                                            try:
                                                                guild_status[self.guild] = Status.END
                                                            except Exception:
                                                                pass
                                                            skip_song = True
                                                            try:
                                                                if p2:
                                                                    p2.kill()
                                                            except Exception:
                                                                pass
                                                            break
                                                        if state == Status.STOP:
                                                            if log_enabled:
                                                                logger.info(f'停止播放: {file}')
                                                            if self.guild in play_list:
                                                                play_list[self.guild]['play_list'] = []
                                                            return
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
                                    else:
                                        if log_enabled:
                                            logger.error(f'音频进程异常: {file}')
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
                            
                            # 执行智能清理
                            smart_cleanup(self.guild)
                            
                            # 预加载下一首歌曲
                            if self.guild in play_list and play_list[self.guild]['play_list']:
                                next_song = play_list[self.guild]['play_list'][0]
                                if isinstance(next_song, dict) and 'file' in next_song:
                                    next_file = next_song['file']
                                    if not next_file.startswith("PLAYLIST_SONG:"):
                                        # 在后台线程中预加载下一首歌曲
                                        def run_next_preload():
                                            try:
                                                # 使用同步方式预加载
                                                cache_key = get_cache_key(next_file, next_song.get('ss', 0))
                                                if cache_key not in audio_cache:
                                                    if log_enabled:
                                                        logger.info(f'开始预加载下一首歌曲: {next_file}')
                                                    
                                                    # 使用subprocess同步执行FFMPEG
                                                    import subprocess
                                                    command = f'{ffmpeg_bin} -nostats -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 -timeout 30000000 -ss {next_song.get("ss", 0)} -i "{next_file}" -filter:a volume={get_guild_volume(self.guild)} -acodec pcm_s16le -ac 2 -ar 48000 -f wav -y -'
                                                    
                                                    process = subprocess.Popen(
                                                        command,
                                                        shell=True,
                                                        stdout=subprocess.PIPE,
                                                        stderr=subprocess.PIPE
                                                    )
                                                    
                                                    # 读取前10MB数据
                                                    audio_data = b''
                                                    chunk_size = 96000
                                                    max_size = 10 * 1024 * 1024  # 10MB
                                                    
                                                    while len(audio_data) < max_size:
                                                        chunk = process.stdout.read(chunk_size)
                                                        if not chunk:
                                                            break
                                                        audio_data += chunk
                                                    
                                                    # 终止进程
                                                    process.terminate()
                                                    process.wait(timeout=2)
                                                    
                                                    # 缓存音频数据
                                                    if audio_data:
                                                        audio_cache[cache_key] = {
                                                            'data': audio_data,
                                                            'timestamp': time.time(),
                                                            'size': len(audio_data)
                                                        }
                                                        if log_enabled:
                                                            logger.info(f'预加载下一首歌曲完成: {next_file}, 大小: {len(audio_data) / 1024 / 1024:.2f}MB')
                                            
                                            except Exception as e:
                                                if log_enabled:
                                                    logger.error(f'预加载下一首歌曲异常: {e}')
                                        
                                        import threading
                                        preload_thread = threading.Thread(target=run_next_preload)
                                        preload_thread.daemon = True
                                        preload_thread.start()
                            
                            # 检查是否还有更多歌曲
                            if self.guild in play_list and len(play_list[self.guild]['play_list']) == 0:
                                try:
                                    if p:
                                        p.kill()
                                    if p2:
                                        p2.kill()
                                except Exception as e:
                                    if log_enabled:
                                        logger.error(f'关闭FFMPEG进程异常: {e}')
                                if self.guild in playlist_handle_status:
                                    playlist_handle_status[self.guild] = False
                                if log_enabled:
                                    logger.info(f'播放列表结束，服务器: {self.guild}')
                            else:
                                # 还有更多歌曲，继续播放下一首
                                if log_enabled:
                                    logger.info(f'准备播放下一首歌曲，服务器: {self.guild}')
                    else:
                        break
        except Exception as e:
            if log_enabled:
                logger.error(f'推流过程中出现错误: {str(e)}', exc_info=True)

    async def keepalive(self):
        while True:
            await asyncio.sleep(45)
            if self.channel_id:
                await self.requestor.keep_alive(self.channel_id)
                if log_enabled:
                    logger.info(f'发送保活请求，频道: {self.channel_id}')
            
            # 定期清理缓存和内存
            cleanup_audio_cache()

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
