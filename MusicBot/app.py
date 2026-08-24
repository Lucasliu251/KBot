from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import json
import asyncio
import sys
from typing import Dict, Any, List, Union, Optional
import threading
import requests
import logging
from pathlib import Path
from khl import Bot, Message

# 修复相对导入
try:
    from . import kookvoice
    from .config import *
    from .utils import search_music, get_music_url, get_playlist, get_playlist_urls
except ImportError:
    import kookvoice
    from config import *
    from utils import search_music, get_music_url, get_playlist, get_playlist_urls

# run.py 会先注册控制台 handler，之后再次调用 basicConfig 不会生效。
# 因此显式挂载绝对路径 FileHandler，确保从任意工作目录启动都能写入日志。
DEBUG_LOG_PATH = Path(__file__).resolve().with_name('debug.log')
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
if not any(
    isinstance(handler, logging.FileHandler)
    and Path(handler.baseFilename).resolve() == DEBUG_LOG_PATH
    for handler in root_logger.handlers
):
    file_handler = logging.FileHandler(DEBUG_LOG_PATH, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)
logger = logging.getLogger(__name__)

# 只关闭Flask的HTTP访问日志，保留其他日志
logging.getLogger('werkzeug').setLevel(logging.ERROR)

class PrefixMiddleware:
    """
    根据反向代理传入的 X-Script-Name 设置 SCRIPT_NAME。

    Nginx 将 /Music 反代到应用根路径时，url_for 会自动带上 /Music；
    本机直连 :8004 没有该头，路径与原来一致。
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        script_name = environ.get("HTTP_X_SCRIPT_NAME", "").strip()
        if script_name:
            if not script_name.startswith("/"):
                script_name = "/" + script_name
            environ["SCRIPT_NAME"] = script_name.rstrip("/") or script_name
        return self.wsgi_app(environ, start_response)


# 初始化Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.wsgi_app = PrefixMiddleware(app.wsgi_app)

# 尝试导入SocketIO，如果不可用则提供备用方案
try:
    from flask_socketio import SocketIO, emit
    socketio = SocketIO(app, cors_allowed_origins="*")
    socketio_available = True
except ImportError:
    logger.warning("flask_socketio未安装，将使用备用方案")
    socketio = None
    socketio_available = False

# 配置KOOK机器人
bot = Bot(
    token=BOT_TOKEN,
    compress=True  # 启用压缩
)

# 强制验证Token有效性
async def verify_token() -> bool:
    try:
        response = await bot.client.gate.request('GET', 'guild/list')
        if not isinstance(response, dict):
            raise ValueError("API响应格式错误")
        items = response.get('items', [])
        if not isinstance(items, list):
            raise ValueError("items应为列表类型")
        print(f"Token验证成功，可访问 {len(items)} 个服务器")
        return True
    except Exception as e:
        print(f"Token验证失败: {str(e)}")
        return False

# 配置FFMPEG
try:
    kookvoice.set_ffmpeg(FFMPEG_PATH)
    kookvoice.configure_logging(True)  # 启用日志记录
    logger.info(f"FFMPEG路径: {FFMPEG_PATH}")
    logger.info(f"FFPROBE路径: {FFPROBE_PATH}")
except Exception as e:
    logger.error(f"FFMPEG配置错误: {str(e)}")
    sys.exit(1)

# 全局变量
guild_data = {}  # 存储服务器信息
current_guild_id = None  # 当前选中的服务器ID

# 获取用户所在的语音频道
async def find_user_voice_channel(gid: str, aid: str) -> Union[str, None]:
    """查找用户所在的语音频道"""
    logger.info(f"获取用户 {aid} 在服务器 {gid} 的语音频道ID")
    try:
        voice_channel_ = await bot.client.gate.request('GET', 'channel-user/get-joined-channel',
                                                   params={'guild_id': gid, 'user_id': aid})
        if voice_channel_ and "items" in voice_channel_:
            voice_channel = voice_channel_["items"]
            if voice_channel:
                logger.info(f"用户 {aid} 当前语音频道ID: {voice_channel[0]['id']}")
                return voice_channel[0]['id']
        logger.warning(f"用户 {aid} 不在任何语音频道")
        return None
    except Exception as e:
        logger.error(f"获取语音频道ID异常: {e}")
        return None

# 获取服务器列表
async def get_guild_list():
    try:
        guilds = await bot.client.gate.request('GET', 'guild/list')
        if guilds and "items" in guilds:
            return guilds["items"]
        return []
    except Exception as e:
        logger.error(f"获取服务器列表异常: {e}")
        return []

# 获取频道列表
async def get_channel_list(guild_id):
    try:
        channels = await bot.client.gate.request('GET', 'channel/list', params={'guild_id': guild_id})
        if channels and "items" in channels:
            return channels["items"]
        return []
    except Exception as e:
        logger.error(f"获取频道列表异常: {e}")
        return []

# 机器人命令
@bot.command(name='ping')
async def ping_cmd(msg: Message):
    await msg.reply('pong!')

@bot.command(name='加入')
async def join_cmd(msg: Message):
    """加入用户所在语音频道"""
    try:
        print(f"收到加入命令 from {msg.author_id}")
        voice_channel = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel:
            # 使用kookvoice.Player加入语音频道
            player = kookvoice.Player(msg.ctx.guild.id, voice_channel, BOT_TOKEN)
            player.join()
            
            # 获取频道信息
            voice_channel_info = await bot.client.fetch_public_channel(voice_channel)
            await msg.reply(f"✅ 已加入语音频道 #{voice_channel_info.name}")
            return True
        await msg.reply("❌ 您当前不在语音频道中")
    except Exception as e:
        print(f"加入命令出错: {e}")
        await msg.reply("⚠️ 加入失败，请检查权限或稍后再试")

@bot.command(name='wy')
async def play_music(msg: Message, music_input: str):
    """播放音乐"""
    try:
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return
        
        # 判断是否为直链
        if music_input.startswith("http"):
            music_url = music_input
            song_name = "直链音乐"
            song_id = ''
            artist_name = '网络音频'
            album_name = ''
            cover_url = ''
            duration = 0
        else:
            try:
                # 搜索歌曲
                search_url = f"{MUSIC_API_BASE}/cloudsearch?keywords={music_input}"
                print(f"🔍 搜索歌曲: {search_url}")
                
                res = requests.get(search_url, timeout=15)
                if res.status_code != 200:
                    await msg.reply("❌ 搜索API错误")
                    return
                
                search_result = res.json()
                songs = search_result.get('result', {}).get('songs', [])
                if not songs:
                    await msg.reply("❌ 未搜索到歌曲")
                    return
                
                song = songs[0]
                song_id = song['id']
                song_name = song.get('name', music_input)
                artist_name = song.get('ar', [{}])[0].get('name', '未知')
                album_data = song.get('al', {}) or {}
                album_name = album_data.get('name', '')
                cover_url = album_data.get('picUrl', '')
                duration = (song.get('dt', 0) or 0) / 1000
                
                print(f"🎵 找到歌曲: {song_name} - {artist_name} (ID: {song_id})")
                
                # 获取歌曲URL
                url_api = f"{MUSIC_API_BASE}/song/url?id={song_id}"
                print(f"🔗 获取URL: {url_api}")
                
                url_res = requests.get(url_api, timeout=15)
                if url_res.status_code != 200:
                    await msg.reply("❌ 获取URL失败")
                    return
                
                url_result = url_res.json()
                music_url = url_result['data'][0]['url']
                if not music_url:
                    await msg.reply("❌ 获取直链失败，可能是VIP歌曲")
                    return
                
                print(f"✅ 获取到音乐URL: {music_url[:50]}...")
                
            except requests.exceptions.Timeout:
                await msg.reply("❌ 网络超时，请稍后重试")
                return
            except requests.exceptions.ConnectionError:
                await msg.reply("❌ 无法连接到音乐API服务器")
                return
            except Exception as e:
                await msg.reply(f"❌ 发生未知错误: {str(e)}")
                return
        
        # 添加音乐到播放队列
        player = kookvoice.Player(msg.ctx.guild.id, voice_channel_id, BOT_TOKEN)
        extra_data = {
            'song_id': str(song_id or 'direct'),
            'title': song_name,
            'artist': artist_name,
            'album': album_name,
            'cover': cover_url,
            'duration': duration,
            'provider': 'netease',
            '点歌人': msg.author_id,
            '文字频道': msg.ctx.channel.id,
        }
        source = (
            f'PLAYLIST_SONG:{song_id}:{song_name}:{artist_name}'
            if song_id else music_url
        )
        player.add_music(source, extra_data)
        
        await msg.reply(f"✅ {song_name} 已加入播放队列")
        
    except Exception as e:
        print(f"播放音乐出错: {e}")
        await msg.reply("⚠️ 播放失败，请稍后再试")

@bot.command(name='停止')
async def stop_music(msg: Message):
    """停止播放"""
    try:
        player = kookvoice.Player(msg.ctx.guild.id)
        player.stop()
        await msg.reply("⏹️ 已停止播放")
    except Exception as e:
        print(f"停止播放出错: {e}")
        await msg.reply("⚠️ 停止失败")

@bot.command(name='跳过')
async def skip_music(msg: Message):
    """跳过当前歌曲"""
    try:
        player = kookvoice.Player(msg.ctx.guild.id)
        player.skip()
        await msg.reply("⏭️ 已跳过当前歌曲")
    except Exception as e:
        print(f"跳过歌曲出错: {e}")
        await msg.reply("⚠️ 跳过失败")

@bot.command(name='暂停')
async def pause_music(msg: Message):
    """暂停播放"""
    try:
        player = kookvoice.Player(msg.ctx.guild.id)
        player.pause()
        await msg.reply("⏸️ 已暂停播放")
    except Exception as e:
        print(f"暂停播放出错: {e}")
        await msg.reply("⚠️ 暂停失败")

@bot.command(name='继续')
async def resume_music(msg: Message):
    """继续播放"""
    try:
        player = kookvoice.Player(msg.ctx.guild.id)
        player.resume()
        await msg.reply("▶️ 已继续播放")
    except Exception as e:
        print(f"继续播放出错: {e}")
        await msg.reply("⚠️ 继续播放失败")

@bot.command(name='wygd')
async def playlist_play(msg: Message, playlist_input: str):
    """播放歌单"""
    try:
        voice_channel_id = await find_user_voice_channel(msg.ctx.guild.id, msg.author_id)
        if voice_channel_id is None:
            await msg.reply("❌ 请先加入语音频道")
            return
        
        # 提取歌单ID
        import re
        def extract_playlist_id(playlist_input):
            match = re.search(r'id=(\d+)', playlist_input) or re.search(r'playlist/(\d+)', playlist_input) or re.search(r'(\d{6,})', playlist_input)
            return match.group(1) if match else playlist_input
        
        playlist_id = extract_playlist_id(playlist_input)
        
        await msg.reply(f"🎶 正在获取歌单[{playlist_id}]的所有歌曲...")
        
        try:
            # 获取歌单详情
            playlist_url = f"{MUSIC_API_BASE}/playlist/detail?id={playlist_id}"
            res = requests.get(playlist_url, timeout=20)
            
            if res.status_code != 200:
                await msg.reply("❌ 获取歌单失败")
                return
            
            playlist_data = res.json()
            playlist_info = playlist_data.get('playlist', {})
            
            # 获取歌单统计信息
            playlist_name = playlist_info.get('name', '未知歌单')
            track_count = playlist_info.get('trackCount', 0)
            
            print(f"🎵 歌单信息: {playlist_name}, 总歌曲数: {track_count}")
            
            # 优先使用 trackIds，如果没有则使用 tracks
            track_ids = []
            if 'trackIds' in playlist_info and playlist_info['trackIds']:
                track_ids = [str(track['id']) for track in playlist_info['trackIds']]
                print(f"📋 从 trackIds 获取到 {len(track_ids)} 首歌曲")
            elif 'tracks' in playlist_info and playlist_info['tracks']:
                track_ids = [str(track['id']) for track in playlist_info['tracks']]
                print(f"📋 从 tracks 获取到 {len(track_ids)} 首歌曲")
            
            if not track_ids:
                await msg.reply("❌ 歌单为空或无法获取歌曲列表")
                return
            
            # 创建播放器
            player = kookvoice.Player(msg.ctx.guild.id, voice_channel_id, BOT_TOKEN)
            
            # 添加歌曲到播放列表
            added_count = 0
            for i, song_id in enumerate(track_ids[:50]):  # 限制最多50首
                try:
                    # 获取歌曲信息
                    song_url = f"{MUSIC_API_BASE}/song/detail?ids={song_id}"
                    song_res = requests.get(song_url, timeout=10)
                    
                    if song_res.status_code == 200:
                        song_data = song_res.json()
                        songs = song_data.get('songs', [])
                        
                        if songs:
                            song = songs[0]
                            song_name = song.get('name', f'歌曲{song_id}')
                            artist_name = song.get('ar', [{}])[0].get('name', '未知歌手')
                            album_data = song.get('al', {}) or {}
                            extra_data = {
                                'song_id': str(song_id),
                                'title': song_name,
                                'artist': artist_name,
                                'album': album_data.get('name', ''),
                                'cover': album_data.get('picUrl', ''),
                                'duration': (song.get('dt', 0) or 0) / 1000,
                                'provider': 'netease',
                                '点歌人': msg.author_id,
                                '文字频道': msg.ctx.channel.id,
                                '歌单来源': playlist_name,
                            }
                            player.add_music(
                                f'PLAYLIST_SONG:{song_id}:{song_name}:{artist_name}',
                                extra_data,
                            )
                            added_count += 1
                            print(f"✅ 已添加: {song_name} - {artist_name}")
                        else:
                            print(f"⚠️ 无法获取歌曲信息: {song_id}")
                    else:
                        print(f"⚠️ 获取歌曲详情失败: {song_id}")
                        
                except Exception as e:
                    print(f"⚠️ 处理歌曲 {song_id} 时出错: {e}")
                    continue
            
            if added_count > 0:
                await msg.reply(f"✅ 已成功添加 {added_count} 首歌曲到播放列表\n📋 歌单: {playlist_name}")
            else:
                await msg.reply("❌ 没有成功添加任何歌曲")
                
        except requests.exceptions.Timeout:
            await msg.reply("❌ 网络超时，请稍后重试")
        except requests.exceptions.ConnectionError:
            await msg.reply("❌ 无法连接到音乐API服务器")
        except Exception as e:
            await msg.reply(f"❌ 处理歌单时发生错误: {str(e)}")
            
    except Exception as e:
        print(f"歌单播放出错: {e}")
        await msg.reply("⚠️ 播放歌单失败，请稍后再试")

# 启动异步事件循环
def start_bot_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # 验证Token
        if not loop.run_until_complete(verify_token()):
            print("Token验证失败，请检查配置")
            sys.exit(1)
            
        # 启动机器人
        print("机器人开始运行...")
        loop.run_until_complete(bot.start())
        print("机器人已成功启动")
        
    except Exception as e:
        print(f"机器人启动异常: {str(e)}")
        sys.exit(1)
    finally:
        loop.close()
    
    # 保持运行
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()

# 导入路由
try:
    from .routes import register_routes
except ImportError:
    from routes import register_routes

# 启动机器人线程
bot_thread = threading.Thread(target=start_bot_loop)
bot_thread.daemon = True
bot_thread.start()

def create_app():
    """
    注册 Web 路由并返回 Flask 应用。

    @returns {Flask} 已挂载路由与子路径中间件的应用实例

    @changelog
    - 2026-08-23: 增加 PrefixMiddleware，支持 Nginx /Music 反代
    """
    # 注册路由
    register_routes(app, bot, socketio if socketio_available else None)
    return app

# 测试路由
@app.route('/api/debug')
def debug():
    try:
        # 测试基础功能
        bot_status = "运行中" if bot.is_running else "未运行"
        
        # 添加播放列表信息
        import kookvoice
        active_guilds = len(kookvoice.play_list) if hasattr(kookvoice, 'play_list') else 0
        playing_songs = 0
        queued_songs = 0
        
        if hasattr(kookvoice, 'play_list'):
            for guild_data in kookvoice.play_list.values():
                if guild_data.get('now_playing'):
                    playing_songs += 1
                queued_songs += len(guild_data.get('play_list', []))
        
        return jsonify({
            "status": "success",
            "bot_status": bot_status,
            "active_guilds": active_guilds,
            "playing_songs": playing_songs,
            "queued_songs": queued_songs,
            "token_valid": bool(BOT_TOKEN),
            "ffmpeg_path": os.path.exists(FFMPEG_PATH)
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

if __name__ == '__main__':
    if socketio_available and socketio:
        socketio.run(app, host=HOST, port=PORT, debug=DEBUG, log_output=False)
    else:
        app.run(host=HOST, port=PORT, debug=DEBUG, use_reloader=False)
