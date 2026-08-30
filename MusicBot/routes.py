from flask import render_template, request, jsonify, redirect, url_for, Blueprint, abort, session
import logging
import asyncio
import functools
import hmac
import ipaddress
import json
import re
import subprocess
import sys
import time
from pathlib import Path
import kookvoice
import requests
from config import BOT_TOKEN, MUSIC_IDLE_DISCONNECT_SECONDS, MUSIC_SETTINGS_TOKEN
from utils import (
    search_music,
    search_music_page,
    get_hot_searches,
    get_hot_playlist_tracks,
    get_music_url,
    get_playlist,
    get_playlist_urls,
    format_playlist_data,
    get_song_detail,
    get_song_lyrics_data,
    netease_auth_status,
    save_cookie_header,
    clear_cookie_header,
    create_netease_login_qrcode,
    check_netease_login_qrcode,
    MusicAPIError,
)
import threading
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from . import qqmusic_service as qqmusic
except ImportError:
    import qqmusic_service as qqmusic

try:
    from . import bilibili_service as bilibili
except ImportError:
    import bilibili_service as bilibili

try:
    from . import recommendation_auth, recommendation_service
except ImportError:
    import recommendation_auth
    import recommendation_service

logger = logging.getLogger(__name__)
LOG_DIRECTORY = Path(__file__).resolve().parent
KOOK_LATENCY_SESSION = requests.Session()
KOOK_LATENCY_LOCK = threading.Lock()

# 全局变量
guild_data = {}  # 存储服务器信息
current_guild_id = None  # 当前选中的服务器ID


def measure_icmp_latency(host: str):
    """测量当前 RTP 网关的 ICMP RTT；不支持或被禁用时返回 None。"""
    try:
        ipaddress.ip_address(str(host))
        command = ['ping', '-c', '1']
        if sys.platform == 'darwin':
            command.extend(['-W', '1000'])
        else:
            command.extend(['-W', '1'])
        command.append(str(host))
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        match = re.search(r'time[=<]([0-9.]+)\s*ms', result.stdout)
        return round(float(match.group(1)), 1) if match else None
    except Exception:
        return None

# 异步函数运行器
def run_async(coro):
    """在Flask中运行异步函数"""
    try:
        # 创建新的事件循环在线程中运行
        result = [None]
        exception = [None]
        
        def run_in_thread():
            try:
                # 创建新的事件循环
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                
                # 运行协程
                result[0] = new_loop.run_until_complete(coro)
            except Exception as e:
                exception[0] = e
            finally:
                # 清理事件循环
                try:
                    new_loop.close()
                except:
                    pass
        
        # 在新线程中运行
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join(timeout=15)  # 15秒超时
        
        if thread.is_alive():
            # 超时处理
            logger.warning("异步函数执行超时")
            return None
            
        if exception[0]:
            raise exception[0]
        return result[0]
        
    except Exception as e:
        logger.error(f"运行异步函数异常: {e}")
        return None

def register_routes(app, bot, socketio=None):
    """注册所有路由"""

    def music_settings_required(view):
        """Protect credential-changing endpoints without exposing account secrets."""
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            supplied = str(request.headers.get('X-Music-Settings-Token', ''))
            expected = str(MUSIC_SETTINGS_TOKEN or '')
            if not supplied or not expected or not hmac.compare_digest(supplied, expected):
                return jsonify({
                    'success': False,
                    'error': '管理密钥不正确，请检查 MUSIC_SETTINGS_TOKEN',
                }), 403
            return view(*args, **kwargs)
        return wrapped

    def requested_provider(payload=None):
        """统一解析音源参数，缺省时保持网易云行为。"""
        raw = (payload or {}).get('provider') if isinstance(payload, dict) else None
        provider = str(raw or request.args.get('provider', 'netease')).strip().lower()
        if provider not in ('netease', 'bilibili', 'qqmusic'):
            raise ValueError('不支持的音乐源')
        return provider

    def qqmusic_error_response(exc):
        if isinstance(exc, qqmusic.QQMusicUnavailable):
            status = 503
        elif isinstance(exc, qqmusic.QQMusicAuthRequired):
            status = 401
        elif isinstance(exc, qqmusic.QQMusicPermissionError):
            status = 403
        else:
            status = 502
        return jsonify({'success': False, 'error': str(exc)}), status

    def bilibili_error_response(exc):
        if isinstance(exc, bilibili.BilibiliInvalidInput):
            status = 400
        elif isinstance(exc, bilibili.BilibiliDurationExceeded):
            status = 422
        else:
            status = 502
        return jsonify({'success': False, 'error': str(exc)}), status

    def safe_return_to(value):
        raw = str(value or '/').strip()
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or parsed.path.startswith('//'):
            return '/'
        return urlunsplit(('', '', parsed.path, parsed.query, ''))

    def append_query(url, **values):
        parsed = urlsplit(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update({key: str(value) for key, value in values.items()})
        return urlunsplit(('', '', parsed.path, urlencode(query), ''))

    def recommendation_user():
        value = session.get('recommendation_user')
        return value if isinstance(value, dict) and value.get('id') else None

    def render_console(channel_id=''):
        return render_template('dashboard.html', initial_channel_id=str(channel_id or ''))

    @app.route('/api/auth/kook/status', methods=['GET'])
    def kook_auth_status():
        return jsonify({
            'success': True,
            'configured': recommendation_auth.oauth_configured(),
            'authenticated': bool(recommendation_user()),
            'user': recommendation_user(),
        })

    @app.route('/api/auth/kook/url', methods=['GET'])
    def kook_auth_url():
        try:
            state = recommendation_auth.new_state()
            return_to = safe_return_to(request.args.get('return_to') or '/')
            session['kook_oauth_state'] = state
            session['kook_oauth_return_to'] = return_to
            session.permanent = True
            return jsonify({
                'success': True,
                'authorization_url': recommendation_auth.authorization_url(state),
            })
        except recommendation_auth.KookOAuthError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 503

    @app.route('/api/auth/kook/callback', methods=['GET'])
    def kook_oauth_callback():
        return_to = safe_return_to(session.pop('kook_oauth_return_to', '/'))
        expected_state = str(session.pop('kook_oauth_state', '') or '')
        supplied_state = str(request.args.get('state', '') or '')
        code = str(request.args.get('code', '') or '')
        error = str(request.args.get('error', '') or '')
        if error:
            return redirect(append_query(return_to, oauth='error', message=error))
        if not expected_state or not supplied_state or not secrets.compare_digest(expected_state, supplied_state):
            return redirect(append_query(return_to, oauth='error', message='OAuth state 校验失败'))
        if not code:
            return redirect(append_query(return_to, oauth='error', message='KOOK 未返回授权码'))
        try:
            token = recommendation_auth.exchange_code(code)
            identity, guild_ids = recommendation_auth.fetch_identity(token)
            recommendation_service.upsert_user(identity)
            session['recommendation_user'] = identity
            session['recommendation_guild_ids'] = guild_ids
            session.permanent = True
            return redirect(append_query(return_to, oauth='success'))
        except Exception as exc:
            logger.error('KOOK OAuth 登录失败: %s', exc)
            return redirect(append_query(return_to, oauth='error', message='KOOK 登录失败'))

    @app.route('/api/auth/kook/logout', methods=['POST'])
    def kook_auth_logout():
        session.pop('recommendation_user', None)
        session.pop('recommendation_guild_ids', None)
        return jsonify({'success': True})

    @app.route('/api/recommendations', methods=['GET'])
    def recommendation_board():
        guild_id = str(request.args.get('guild_id', '') or '')
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少 guild_id'}), 400
        try:
            limit = max(1, min(50, int(request.args.get('limit', 20))))
            offset = max(0, int(request.args.get('offset', 0)))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '分页参数无效'}), 400
        user = recommendation_user() or {}
        result = recommendation_service.list_board(
            guild_id,
            viewer_user_id=str(user.get('id') or ''),
            sort=str(request.args.get('sort', 'latest')),
            limit=limit,
            offset=offset,
        )
        return jsonify({'success': True, **result})

    @app.route('/api/recommendations/toggle', methods=['POST'])
    def recommendation_toggle():
        user = recommendation_user()
        if not user:
            return jsonify({
                'success': False,
                'error': '请先使用 KOOK 登录后推荐',
                'login_required': True,
            }), 401
        data = request.json or {}
        guild_id = str(data.get('guild_id', '') or '')
        allowed_guilds = {str(item) for item in (session.get('recommendation_guild_ids') or [])}
        if guild_id not in allowed_guilds:
            return jsonify({'success': False, 'error': '你不在这个 KOOK 服务器中'}), 403
        try:
            result = recommendation_service.toggle(
                guild_id,
                user,
                data.get('track') or {},
                note=str(data.get('note', '') or ''),
                active=data.get('active') if isinstance(data.get('active'), bool) else None,
            )
            return jsonify({'success': True, **result})
        except recommendation_service.RecommendationError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400
    
    @app.route('/')
    def index():
        """控制台入口；反代到 /Music 时这里就是 /Music。"""
        return render_console()

    @app.route('/Music')
    @app.route('/Music/')
    def music_console():
        """直连 Flask 时使用的 /Music 控制台入口。"""
        return render_console()

    @app.route('/Music/<channel_id>')
    @app.route('/dashboard/<channel_id>')
    def music_console_channel(channel_id):
        """按频道 ID 打开的可分享控制台深链。"""
        if not str(channel_id).isdigit():
            abort(404)
        return render_console(channel_id)
    
    @app.route('/dashboard')
    def dashboard():
        """兼容旧控制台地址。"""
        return render_console()
    
    @app.route('/monitor')
    def monitor():
        """监控页面"""
        return render_template('monitor.html')

    @app.route('/<channel_id>')
    def prefixed_music_console_channel(channel_id):
        """兼容 Nginx SCRIPT_NAME=/Music 后的 /Music/<频道ID>。"""
        if not str(channel_id).isdigit():
            abort(404)
        return render_console(channel_id)
    
    @app.route('/api/guilds', methods=['GET'])
    def get_guilds():
        """获取服务器列表"""
        try:
            # 使用同步方式调用KOOK API获取服务器列表
            try:
                import requests
                from config import BOT_TOKEN
                if not BOT_TOKEN:
                    return jsonify({
                        'success': False,
                        'error': 'MUSIC_BOT_TOKEN 未配置，请先复制 .env.example 为 .env 并填写音乐机器人 Token',
                    }), 503
                headers = {
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }
                url = 'https://www.kookapp.cn/api/v3/guild/list'
                
                logger.info(f"请求服务器列表API: {url}")
                response = requests.get(url, headers=headers, timeout=10)
                logger.info(f"服务器列表API响应状态: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"服务器列表API响应数据: {data}")
                    if data.get('code') == 0 and 'data' in data:
                        guilds = data['data'].get('items', [])
                        logger.info(f"获取到 {len(guilds)} 个服务器")
                    else:
                        guilds = []
                        logger.warning(f"服务器列表API返回错误: {data.get('message', '未知错误')}")
                else:
                    logger.error(f"服务器列表API HTTP错误: {response.status_code}")
                    return jsonify({
                        'success': False,
                        'error': f'KOOK 服务器列表请求失败（HTTP {response.status_code}）',
                    }), 502
            except Exception as e:
                logger.error(f"获取服务器列表异常: {e}")
                return jsonify({'success': False, 'error': f'无法连接 KOOK API：{e}'}), 502
            
            # 格式化数据
            formatted_guilds = []
            for guild in guilds:
                formatted_guilds.append({
                    'id': guild.get('id', ''),
                    'name': guild.get('name', '未知服务器'),
                    'icon': guild.get('icon', ''),
                    'master_id': guild.get('master_id', '')
                })
            
            return jsonify({'success': True, 'guilds': formatted_guilds})
        except Exception as e:
            logger.error(f"获取服务器列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/network/ping', methods=['GET'])
    def network_ping():
        """立即返回，供浏览器独立测量到 MusicBot 控制台的往返时间。"""
        return jsonify({'success': True, 'server_time': time.time()})

    @app.route('/api/network/latency', methods=['GET'])
    def get_network_latency():
        """分别测量 KOOK REST 热连接和当前 voice/join RTP 网关。"""
        if not BOT_TOKEN:
            return jsonify({
                'success': False,
                'online': False,
                'error': 'MUSIC_BOT_TOKEN 未配置',
            }), 503

        kook_rest_ms = None
        kook_error = ''
        online = False
        try:
            started_at = time.perf_counter()
            with KOOK_LATENCY_LOCK:
                response = KOOK_LATENCY_SESSION.get(
                    'https://www.kookapp.cn/api/v3/user/me',
                    headers={
                        'Authorization': f'Bot {BOT_TOKEN}',
                        'Content-Type': 'application/json',
                    },
                    timeout=5,
                )
            kook_rest_ms = round((time.perf_counter() - started_at) * 1000)
            if response.status_code != 200:
                kook_error = f'KOOK API 请求失败（HTTP {response.status_code}）'
            else:
                payload = response.json()
                online = payload.get('code') == 0
                if not online:
                    kook_error = payload.get('message', 'KOOK API 返回异常')
        except Exception as e:
            logger.warning(f"KOOK 网络延迟探测失败: {e}")
            kook_error = f'无法连接 KOOK API：{e}'

        guild_id = str(request.args.get('guild_id', '') or '')
        transport = kookvoice.get_voice_transport_metrics(guild_id) if guild_id else {}
        rtp_ip = str(transport.get('rtp_ip') or '')
        voice_gateway_ms = measure_icmp_latency(rtp_ip) if rtp_ip else None
        transport_public = {
            'actual_fps': round(float(transport.get('actual_fps') or 0), 2),
            'target_fps': round(float(transport.get('target_fps') or 50), 2),
            'late_frames': int(transport.get('late_frames') or 0),
            'resyncs': int(transport.get('resyncs') or 0),
            'max_lateness_ms': round(float(transport.get('max_lateness_ms') or 0), 2),
        } if transport else None

        return jsonify({
            'success': True,
            'online': online,
            # kook_ms 暂时保留，兼容旧前端滚动升级。
            'kook_ms': kook_rest_ms,
            'kook_rest_ms': kook_rest_ms,
            'kook_error': kook_error,
            'voice_gateway_ms': voice_gateway_ms,
            'voice_connected': bool(transport),
            'transport': transport_public,
            'measured_at': time.time(),
        })
    
    @app.route('/api/channels', methods=['GET'])
    def get_channels():
        """获取频道列表"""
        guild_id = request.args.get('guild_id')
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            # 使用同步方式调用KOOK API获取频道列表
            try:
                import requests
                from config import BOT_TOKEN
                if not BOT_TOKEN:
                    return jsonify({'success': False, 'error': 'MUSIC_BOT_TOKEN 未配置'}), 503
                headers = {
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json'
                }
                url = f'https://www.kookapp.cn/api/v3/channel/list?guild_id={guild_id}'
                
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('code') == 0 and 'data' in data:
                        channels = data['data'].get('items', [])
                    else:
                        channels = []
                else:
                    return jsonify({
                        'success': False,
                        'error': f'KOOK 频道列表请求失败（HTTP {response.status_code}）',
                    }), 502
            except Exception as e:
                logger.error(f"获取频道列表异常: {e}")
                return jsonify({'success': False, 'error': f'无法连接 KOOK API：{e}'}), 502
            
            # 格式化数据，只返回语音频道
            formatted_channels = []
            for channel in channels:
                # 只返回语音频道 (type=2)
                if channel.get('type') == 2:
                    formatted_channels.append({
                        'id': channel.get('id', ''),
                        'name': channel.get('name', '未知频道'),
                        'type': channel.get('type', 2)
                    })
            
            return jsonify({'success': True, 'channels': formatted_channels})
        except Exception as e:
            logger.error(f"获取频道列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/channel/context', methods=['GET'])
    def get_channel_context():
        """通过频道 ID 解析频道名称和所属服务器，供 /Music/<频道ID> 深链使用。"""
        channel_id = str(request.args.get('channel_id', '')).strip()
        if not channel_id:
            return jsonify({'success': False, 'error': '缺少channel_id参数'}), 400
        try:
            import requests
            from config import BOT_TOKEN
            if not BOT_TOKEN:
                return jsonify({'success': False, 'error': 'MUSIC_BOT_TOKEN 未配置'}), 503
            response = requests.get(
                'https://www.kookapp.cn/api/v3/channel/view',
                params={'target_id': channel_id},
                headers={
                    'Authorization': f'Bot {BOT_TOKEN}',
                    'Content-Type': 'application/json',
                },
                timeout=10,
            )
            if response.status_code != 200:
                return jsonify({
                    'success': False,
                    'error': f'KOOK 频道详情请求失败（HTTP {response.status_code}）',
                }), 502
            payload = response.json()
            if payload.get('code') != 0:
                return jsonify({
                    'success': False,
                    'error': payload.get('message', '频道不存在或机器人没有访问权限'),
                }), 404
            channel = payload.get('data', {})
            if int(channel.get('type', 0)) != 2:
                return jsonify({'success': False, 'error': '该 ID 不是语音频道'}), 400
            return jsonify({
                'success': True,
                'context': {
                    'guild_id': str(channel.get('guild_id', '')),
                    'channel_id': str(channel.get('id', channel_id)),
                    'channel_name': channel.get('name', '未知语音频道'),
                },
            })
        except Exception as e:
            logger.error(f"解析频道上下文异常: {e}")
            return jsonify({'success': False, 'error': f'频道解析失败：{e}'}), 502
    
    @app.route('/api/join', methods=['POST'])
    def join_channel():
        """加入语音频道"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')
        
        if not guild_id or not channel_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        try:
            from config import BOT_TOKEN
            guild_id = str(guild_id)
            channel_id = str(channel_id)
            current_player = kookvoice.play_list.get(guild_id, {})
            current_channel_id = str(current_player.get('voice_channel', ''))
            current_status = kookvoice.guild_status.get(guild_id)

            if current_channel_id == channel_id and current_status not in (
                kookvoice.Status.STOP,
                kookvoice.Status.EMPTY,
            ):
                return jsonify({'success': True, 'already_connected': True, 'channel_id': channel_id})

            if current_channel_id and current_channel_id != channel_id:
                kookvoice.Player(guild_id).stop()
                deadline = time.time() + 4
                while guild_id in kookvoice.play_list and time.time() < deadline:
                    time.sleep(0.1)
                if guild_id in kookvoice.play_list:
                    return jsonify({
                        'success': False,
                        'error': '原语音连接仍在关闭，请稍后再试',
                    }), 409

            player = kookvoice.Player(guild_id, channel_id, BOT_TOKEN)
            player.join()
            
            # 更新全局变量
            global current_guild_id
            current_guild_id = guild_id
            
            return jsonify({'success': True, 'channel_id': channel_id})
        except Exception as e:
            logger.error(f"加入语音频道异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/leave', methods=['POST'])
    def leave_channel():
        """离开语音频道"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            guild_id = str(guild_id)
            if guild_id not in kookvoice.play_list:
                return jsonify({'success': True, 'already_disconnected': True})
            player = kookvoice.Player(guild_id)
            player.stop()
            deadline = time.time() + 4
            while guild_id in kookvoice.play_list and time.time() < deadline:
                time.sleep(0.1)
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"离开语音频道异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/search', methods=['GET'])
    def search():
        """搜索音乐"""
        keyword = request.args.get('keyword')
        if not keyword:
            return jsonify({'success': False, 'error': '缺少keyword参数'})
        try:
            limit = max(1, min(20, int(request.args.get('limit', 8))))
            offset = max(0, int(request.args.get('offset', 0)))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '分页参数无效'}), 400
        try:
            provider = requested_provider()
            if provider == 'bilibili':
                songs, total = bilibili.search_media(keyword, limit=limit, offset=offset)
            elif provider == 'qqmusic':
                songs, total = qqmusic.search_music_page(keyword, limit=limit, offset=offset)
            else:
                songs, total = search_music_page(keyword, limit=limit, offset=offset)
            return jsonify({
                'success': True,
                'provider': provider,
                'songs': songs,
                'pagination': {
                    'offset': offset,
                    'limit': limit,
                    'total': total,
                    'has_more': offset + len(songs) < total,
                },
            })
        except qqmusic.QQMusicError as e:
            logger.error(f"QQ 音乐搜索服务不可用: {e}")
            return qqmusic_error_response(e)
        except bilibili.BilibiliError as e:
            logger.error(f"Bilibili 搜索服务不可用: {e}")
            return bilibili_error_response(e)
        except MusicAPIError as e:
            logger.error(f"搜索音乐服务不可用: {e}")
            return jsonify({'success': False, 'error': str(e)}), 502
        except Exception as e:
            logger.error(f"搜索音乐异常: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/discover', methods=['GET'])
    def discover():
        """搜索框为空时返回当前音源的热搜词与分页热歌榜。"""
        try:
            limit = max(1, min(20, int(request.args.get('limit', 8))))
            offset = max(0, int(request.args.get('offset', 0)))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '分页参数无效'}), 400
        try:
            provider = requested_provider()
            if provider == 'bilibili':
                # 第一版不伪造 B站音乐榜；空搜索页只展示使用引导。
                hot_searches, songs, has_more = [], [], False
            elif provider == 'qqmusic':
                hot_searches, songs, has_more = qqmusic.discover(limit=limit, offset=offset)
            else:
                songs, has_more = get_hot_playlist_tracks(limit=limit, offset=offset)
                hot_searches = get_hot_searches(limit=12) if offset == 0 else []
            return jsonify({
                'success': True,
                'provider': provider,
                # 后续分页不重复传热搜，减少响应体和上游请求。
                'hot_searches': hot_searches,
                'songs': songs,
                'pagination': {
                    'offset': offset,
                    'limit': limit,
                    'has_more': has_more,
                },
            })
        except qqmusic.QQMusicError as e:
            logger.error(f"QQ 音乐发现页服务不可用: {e}")
            return qqmusic_error_response(e)
        except bilibili.BilibiliError as e:
            logger.error(f"Bilibili 发现页服务不可用: {e}")
            return bilibili_error_response(e)
        except MusicAPIError as e:
            logger.error(f"网易云发现页服务不可用: {e}")
            return jsonify({'success': False, 'error': str(e)}), 502
        except Exception as e:
            logger.error(f"加载网易云发现页异常: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/song/detail', methods=['GET'])
    def song_detail():
        """返回控制台所需的精简歌曲信息。"""
        song_id = request.args.get('id')
        if not song_id:
            return jsonify({'success': False, 'error': '缺少id参数'})
        try:
            provider = requested_provider()
            if provider == 'bilibili':
                normalized = bilibili.get_detail(song_id)
                album = normalized.get('al', {})
                artists = normalized.get('ar', [])
                return jsonify({
                    'success': True,
                    'provider': provider,
                    'song': {
                        'id': str(normalized.get('id', song_id)),
                        'name': normalized.get('name', ''),
                        'artist': ' / '.join(artist.get('name', '') for artist in artists if artist.get('name')),
                        'album': album.get('name', ''),
                        'cover': album.get('picUrl', ''),
                        'duration': (normalized.get('dt', 0) or 0) / 1000,
                        'provider': provider,
                    },
                })
            if provider == 'qqmusic':
                normalized = qqmusic.get_song_detail(song_id)
                album = normalized.get('al', {})
                artists = normalized.get('ar', [])
                return jsonify({
                    'success': True,
                    'provider': provider,
                    'song': {
                        'id': str(normalized.get('id', song_id)),
                        'name': normalized.get('name', ''),
                        'artist': ' / '.join(artist.get('name', '') for artist in artists if artist.get('name')),
                        'album': album.get('name', ''),
                        'cover': album.get('picUrl', ''),
                        'duration': (normalized.get('dt', 0) or 0) / 1000,
                        'provider': provider,
                    },
                })
            detail = get_song_detail(song_id)
            album = detail.get('al', {}) if detail else {}
            artists = detail.get('ar', []) if detail else []
            return jsonify({
                'success': True,
                'song': {
                    'id': str(detail.get('id', song_id)),
                    'name': detail.get('name', ''),
                    'artist': ' / '.join(artist.get('name', '') for artist in artists if artist.get('name')),
                    'album': album.get('name', ''),
                    'cover': album.get('picUrl', ''),
                    'duration': (detail.get('dt', 0) or 0) / 1000,
                    'provider': provider,
                },
            })
        except qqmusic.QQMusicError as e:
            return qqmusic_error_response(e)
        except bilibili.BilibiliError as e:
            return bilibili_error_response(e)
        except Exception as e:
            logger.error(f"获取歌曲详情异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/song/lyrics', methods=['GET'])
    def song_lyrics():
        """返回当前音源的原文及逐句翻译 LRC，时间轴合并由前端完成。"""
        song_id = request.args.get('id')
        if not song_id:
            return jsonify({'success': False, 'error': '缺少id参数'})
        try:
            provider = requested_provider()
            if provider == 'bilibili':
                # B站视频不做任何跨平台歌词匹配或搜索。
                lyric_data = {'lyric': '', 'translated_lyric': '', 'romanized_lyric': ''}
            elif provider == 'qqmusic':
                lyric_data = qqmusic.get_song_lyrics_data(song_id)
            else:
                lyric_data = get_song_lyrics_data(song_id)
            return jsonify({
                'success': True,
                'provider': provider,
                **lyric_data,
                'has_translation': bool(lyric_data.get('translated_lyric')),
            })
        except qqmusic.QQMusicError as e:
            return qqmusic_error_response(e)
        except bilibili.BilibiliError as e:
            return bilibili_error_response(e)
        except Exception as e:
            logger.error(f"获取歌词异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/play', methods=['POST'])
    def play_music():
        """播放音乐"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')  # 添加频道ID参数
        song_id = data.get('song_id')
        song_name = data.get('song_name', '')
        artist_name = data.get('artist_name', '')
        album_name = data.get('album_name', '')
        cover_url = data.get('cover_url', '')
        try:
            duration = max(0.0, float(data.get('duration', 0) or 0))
        except (TypeError, ValueError):
            duration = 0.0
        
        if not guild_id or not song_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        try:
            provider = requested_provider(data)
            resolved_url = ''
            resolved_expires_at = 0
            if provider == 'bilibili':
                resolved = bilibili.resolve_audio(str(song_id))
                resolved_url = resolved['url']
                resolved_expires_at = float(resolved.get('expires_at', 0) or 0)
                song_name = song_name or resolved.get('title', '')
                artist_name = artist_name or resolved.get('artist', '')
                album_name = album_name or 'Bilibili 视频'
                cover_url = cover_url or resolved.get('cover', '')
                duration = float(resolved.get('duration', 0) or 0) or duration
                album_data = {'name': album_name, 'picUrl': cover_url}
                source = f'MUSIC_SOURCE:bilibili:{song_id}'
            elif provider == 'qqmusic':
                resolved = qqmusic.resolve_song_url(song_id)
                resolved_url = resolved['url']
                resolved_expires_at = time.time() + max(0, int(resolved.get('expires_in', 0)))
                normalized = resolved.get('song', {})
                album_data = normalized.get('al', {})
                artists = normalized.get('ar', [])
                song_name = song_name or normalized.get('name', '')
                artist_name = artist_name or ' / '.join(
                    artist.get('name', '') for artist in artists if artist.get('name')
                )
                album_name = album_name or album_data.get('name', '')
                cover_url = cover_url or album_data.get('picUrl', '')
                duration = (normalized.get('dt', 0) or 0) / 1000 or duration
                source = f'MUSIC_SOURCE:qqmusic:{song_id}'
            else:
                resolved_url = get_music_url(song_id)
                if not resolved_url:
                    return jsonify({'success': False, 'error': '无法获取音乐URL'})
                detail = get_song_detail(song_id) if not (album_name and cover_url and duration) else {}
                album_data = detail.get('al', {}) if detail else {}
                duration = ((detail.get('dt', 0) or 0) / 1000 if detail else 0) or duration
                # 队列中只保存歌曲 ID。轮到预加载/播放时再刷新临时 URL，
                # 避免排队期间网易云地址过期造成后半段断流。
                source = f'PLAYLIST_SONG:{song_id}:{song_name}:{artist_name}'

            from config import BOT_TOKEN
            player = kookvoice.Player(guild_id, channel_id, BOT_TOKEN)
            extra_data = {
                'song_id': str(song_id),
                'title': song_name,
                'artist': artist_name,
                'album': album_name or album_data.get('name', ''),
                'cover': cover_url or album_data.get('picUrl', ''),
                'duration': duration,
                'provider': provider,
                '_resolved_url': resolved_url,
                '_resolved_expires_at': (
                    resolved_expires_at if provider in ('bilibili', 'qqmusic') else time.time() + 240
                ),
            }
            if provider == 'bilibili':
                http_headers = resolved.get('headers') or {}
                extra_data['header'] = ''.join(
                    f'{key}: {value}\r\n' for key, value in http_headers.items()
                )
                extra_data['user_agent'] = http_headers.get('User-Agent', '')
                extra_data['referer'] = http_headers.get('Referer', '')
                extra_data['webpage_url'] = resolved.get('webpage_url', '')
            player.add_music(source, extra_data)
            
            return jsonify({'success': True, 'provider': provider})
        except qqmusic.QQMusicError as e:
            logger.error(f"播放 QQ 音乐异常: {e}")
            return qqmusic_error_response(e)
        except bilibili.BilibiliError as e:
            logger.error(f"播放 Bilibili 音频异常: {e}")
            return bilibili_error_response(e)
        except Exception as e:
            logger.error(f"播放音乐异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/music/providers', methods=['GET'])
    def music_providers():
        """返回不包含 Cookie/密钥的音源登录状态。"""
        return jsonify({
            'success': True,
            'default': 'netease',
            'providers': {
                'netease': netease_auth_status(),
                'bilibili': bilibili.auth_status(),
                'qqmusic': qqmusic.auth_status(),
            },
        })

    @app.route('/api/music/settings/unlock', methods=['POST'])
    @music_settings_required
    def music_settings_unlock():
        return jsonify({'success': True})

    @app.route('/api/netease/login/qrcode', methods=['POST'])
    @music_settings_required
    def netease_login_qrcode():
        try:
            result = create_netease_login_qrcode()
            return jsonify({'success': True, **result})
        except (MusicAPIError, ValueError) as e:
            return jsonify({'success': False, 'error': str(e)}), 502

    @app.route('/api/netease/login/status', methods=['POST'])
    @music_settings_required
    def netease_login_status():
        try:
            data = request.get_json(silent=True) or {}
            result = check_netease_login_qrcode(data.get('key', ''))
            return jsonify({'success': True, **result})
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except MusicAPIError as e:
            return jsonify({'success': False, 'error': str(e)}), 502

    @app.route('/api/netease/cookie', methods=['POST'])
    @music_settings_required
    def netease_cookie_update():
        data = request.get_json(silent=True) or {}
        try:
            auth = save_cookie_header(data.get('cookie', ''))
            return jsonify({'success': True, 'auth': auth})
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)}), 400
        except MusicAPIError as e:
            return jsonify({'success': False, 'error': str(e)}), 409

    @app.route('/api/netease/logout', methods=['POST'])
    @music_settings_required
    def netease_logout():
        if not clear_cookie_header():
            return jsonify({
                'success': False,
                'error': '网易云 Cookie 来自环境变量，请修改 NETEASE_COOKIE 后重启服务',
            }), 409
        return jsonify({'success': True, 'auth': netease_auth_status()})

    @app.route('/api/qqmusic/login/qrcode', methods=['POST'])
    @music_settings_required
    def qqmusic_login_qrcode():
        data = request.get_json(silent=True) or {}
        try:
            result = qqmusic.create_login_qrcode(str(data.get('login_type', 'qq')).lower())
            return jsonify({'success': True, **result})
        except qqmusic.QQMusicError as e:
            return qqmusic_error_response(e)

    @app.route('/api/qqmusic/login/status', methods=['POST'])
    @music_settings_required
    def qqmusic_login_status():
        data = request.get_json(silent=True) or {}
        identifier = str(data.get('identifier', '')).strip()
        login_type = str(data.get('login_type', 'qq')).strip().lower()
        try:
            result = qqmusic.check_login_qrcode(identifier, login_type)
            return jsonify({'success': True, **result})
        except qqmusic.QQMusicError as e:
            return qqmusic_error_response(e)

    @app.route('/api/qqmusic/logout', methods=['POST'])
    @music_settings_required
    def qqmusic_logout():
        try:
            if not qqmusic.clear_credential():
                return jsonify({
                    'success': False,
                    'error': '当前 QQ 音乐账号来自环境变量，请从 .env 删除后重启服务',
                }), 409
            return jsonify({'success': True, 'auth': qqmusic.auth_status()})
        except qqmusic.QQMusicError as e:
            return qqmusic_error_response(e)
    
    @app.route('/api/playlist', methods=['POST'])
    def add_playlist():
        """添加歌单"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        channel_id = data.get('channel_id')  # 添加频道ID参数
        playlist_id = data.get('playlist_id')
        
        if not guild_id or not playlist_id:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        try:
            # 获取歌单中所有歌曲
            songs = get_playlist_urls(playlist_id)
            if not songs:
                return jsonify({'success': False, 'error': '歌单为空或无法获取歌单'})
            
            # 添加到播放列表 - 提供必要的参数
            from config import BOT_TOKEN
            player = kookvoice.Player(guild_id, channel_id, BOT_TOKEN)
            for song in songs:
                player.add_music(song['marker'], {
                    'song_id': str(song['id']),
                    'title': song['name'],
                    'artist': song['artist'],
                    'album': song.get('album', ''),
                    'cover': song.get('cover', ''),
                    'duration': song.get('duration', 0),
                })
            
            return jsonify({'success': True, 'count': len(songs)})
        except Exception as e:
            logger.error(f"添加歌单异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/skip', methods=['POST'])
    def skip_music():
        """跳过当前歌曲"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            player = kookvoice.Player(guild_id)
            player.skip()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"跳过歌曲异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/seek', methods=['POST'])
    def seek_music():
        """跳转到指定位置"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        position = data.get('position')
        
        if not guild_id or position is None:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        try:
            player = kookvoice.Player(guild_id)
            player.seek(int(position))
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"跳转位置异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/playlist/current', methods=['GET'])
    def get_current_playlist():
        """获取当前播放列表"""
        guild_id = request.args.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            if guild_id in kookvoice.play_list:
                guild_playlist = kookvoice.play_list[guild_id]
                playlist_data = format_playlist_data(guild_playlist)
                status = kookvoice.guild_status.get(guild_id)
                now_playing = guild_playlist.get('now_playing') or {}
                paused = status == kookvoice.Status.PAUSE
                active = (
                    status == kookvoice.Status.PLAYING
                    and bool(now_playing.get('start'))
                )
                return jsonify({
                    'success': True,
                    'playlist': playlist_data,
                    'playing': active,
                    'paused': paused,
                    'preparing': bool(now_playing) and not active and not paused,
                })
            else:
                return jsonify({
                    'success': True,
                    'playlist': [],
                    'playing': False,
                    'paused': False,
                    'preparing': False,
                })
        except Exception as e:
            logger.error(f"获取播放列表异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/player/state', methods=['GET'])
    def get_player_state():
        """获取顶栏连接状态和播放器偏好。"""
        guild_id = request.args.get('guild_id')
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        guild_id = str(guild_id)
        guild_playlist = kookvoice.play_list.get(guild_id, {})
        status = kookvoice.guild_status.get(guild_id)
        now_playing = guild_playlist.get('now_playing') or {}
        paused = status == kookvoice.Status.PAUSE
        active = (
            status == kookvoice.Status.PLAYING
            and bool(now_playing.get('start'))
        )
        return jsonify({
            'success': True,
            'connected': bool(guild_playlist.get('voice_channel')) and status not in (
                kookvoice.Status.STOP,
                kookvoice.Status.EMPTY,
            ),
            'channel_id': guild_playlist.get('voice_channel', ''),
            'volume': kookvoice.guild_volume.get(guild_id, 0.4),
            'play_mode': kookvoice.guild_play_mode.get(guild_id, 'order'),
            'paused': paused,
            'playing': active,
            'preparing': bool(now_playing) and not active and not paused,
            'position': float(now_playing.get('ss', 0)),
        })

    @app.route('/api/volume', methods=['POST'])
    def set_volume():
        """设置服务器播放音量；发送循环会在约 120ms 内平滑应用。"""
        data = request.json or {}
        guild_id = data.get('guild_id')
        try:
            volume = float(data.get('volume'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'volume必须是0到1之间的数字'})
        if not guild_id or not 0 <= volume <= 1:
            return jsonify({'success': False, 'error': '音量范围必须是0到1'})
        guild_id = str(guild_id)
        try:
            kookvoice.guild_volume[guild_id] = volume
            now_playing = kookvoice.play_list.get(guild_id, {}).get('now_playing')
            return jsonify({
                'success': True,
                'volume': volume,
                'position': float((now_playing or {}).get('ss', 0)),
            })
        except Exception as e:
            logger.error(f"设置音量异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/play-mode', methods=['POST'])
    def set_play_mode():
        """切换顺序、单曲循环或随机播放。"""
        data = request.json or {}
        guild_id = str(data.get('guild_id', ''))
        mode = data.get('mode')
        if not guild_id or mode not in ('order', 'repeat-one', 'shuffle'):
            return jsonify({'success': False, 'error': '播放模式无效'})
        kookvoice.guild_play_mode[guild_id] = mode
        return jsonify({'success': True, 'mode': mode})

    @app.route('/api/previous', methods=['POST'])
    def previous_music():
        """从历史记录回到上一首歌曲。"""
        data = request.json or {}
        guild_id = str(data.get('guild_id', ''))
        history = kookvoice.play_history.get(guild_id, [])
        if not guild_id or not history:
            return jsonify({'success': False, 'error': '暂无上一首歌曲'})
        try:
            previous = history.pop()
            previous['ss'] = 0
            previous.pop('start', None)
            previous.pop('duration', None)
            kookvoice.play_list[guild_id]['play_list'].insert(0, previous)
            kookvoice.Player(guild_id).refresh_preload()
            if kookvoice.play_list[guild_id].get('now_playing'):
                kookvoice.Player(guild_id).skip()
            else:
                kookvoice.guild_status[guild_id] = kookvoice.Status.END
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"返回上一首异常: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/queue/reorder', methods=['POST'])
    def reorder_queue():
        """按队列索引移动歌曲，供前端拖拽排序。"""
        data = request.json or {}
        guild_id = str(data.get('guild_id', ''))
        try:
            from_index = int(data.get('from_index'))
            to_index = int(data.get('to_index'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': '队列索引无效'})
        try:
            queue = kookvoice.play_list[guild_id]['play_list']
            if not (0 <= from_index < len(queue) and 0 <= to_index < len(queue)):
                return jsonify({'success': False, 'error': '队列索引超出范围'})
            item = queue.pop(from_index)
            queue.insert(to_index, item)
            kookvoice.Player(guild_id).refresh_preload()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"调整队列顺序异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/pause', methods=['POST'])
    def pause_music():
        """暂停播放"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        guild_id = str(guild_id)
        
        try:
            player = kookvoice.Player(guild_id)
            player.pause()
            position = float((kookvoice.play_list.get(str(guild_id), {}).get('now_playing') or {}).get('ss', 0))
            return jsonify({'success': True, 'paused': True, 'position': position})
        except Exception as e:
            logger.error(f"暂停播放异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/resume', methods=['POST'])
    def resume_music():
        """继续播放"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            player = kookvoice.Player(guild_id)
            player.resume()
            position = float((kookvoice.play_list.get(str(guild_id), {}).get('now_playing') or {}).get('ss', 0))
            return jsonify({'success': True, 'paused': False, 'position': position})
        except Exception as e:
            logger.error(f"继续播放异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/stop', methods=['POST'])
    def stop_music():
        """停止播放"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        
        try:
            player = kookvoice.Player(guild_id)
            player.stop()
            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"停止播放异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/clear', methods=['POST'])
    def clear_playlist():
        """清空当前歌曲与等待队列，并退出语音频道。"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        
        if not guild_id:
            return jsonify({'success': False, 'error': '缺少guild_id参数'})
        guild_id = str(guild_id)
        
        try:
            if guild_id in kookvoice.play_list:
                kookvoice.Player(guild_id).clear()
                deadline = time.time() + MUSIC_IDLE_DISCONNECT_SECONDS + 5
                while guild_id in kookvoice.play_list and time.time() < deadline:
                    waiting = kookvoice.play_list[guild_id].get('play_list', [])
                    if waiting:
                        return jsonify({
                            'success': True,
                            'disconnected': False,
                            'playlist': format_playlist_data(kookvoice.play_list[guild_id]),
                        })
                    time.sleep(0.05)
                if guild_id in kookvoice.play_list:
                    return jsonify({
                        'success': True,
                        'disconnected': False,
                        'playlist': [],
                        'cooling_down': True,
                    })
            else:
                # 即使连接已结束，也确保旧历史与缓存目标不会残留。
                kookvoice.Player(guild_id).clear()
            return jsonify({'success': True, 'disconnected': True, 'playlist': []})
        except Exception as e:
            logger.error(f"清空全部音乐异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/remove', methods=['POST'])
    def remove_from_playlist():
        """从播放列表中移除歌曲"""
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'})
            
        guild_id = data.get('guild_id')
        index = data.get('index')
        
        if not guild_id or index is None:
            return jsonify({'success': False, 'error': '缺少必要参数'})
        
        try:
            if guild_id in kookvoice.play_list:
                playlist = kookvoice.play_list[guild_id]['play_list']
                if 0 <= int(index) < len(playlist):
                    playlist.pop(int(index))
                    kookvoice.Player(guild_id).refresh_preload()
                    return jsonify({'success': True})
                else:
                    return jsonify({'success': False, 'error': '索引超出范围'})
            else:
                return jsonify({'success': False, 'error': '播放列表不存在'})
        except Exception as e:
            logger.error(f"移除歌曲异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/system/status', methods=['GET'])
    def get_system_status():
        """获取系统状态信息"""
        try:
            import psutil
            import os
            import time
            
            # 获取系统资源信息
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # 获取进程信息
            process = psutil.Process()
            process_memory = process.memory_info()
            process_cpu = process.cpu_percent()
            child_processes = process.children(recursive=True)
            child_memory = []
            child_cpu = 0.0
            for child in child_processes:
                try:
                    child_memory.append(child.memory_info())
                    child_cpu += child.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            process_memory_rss = process_memory.rss + sum(item.rss for item in child_memory)
            process_memory_vms = process_memory.vms + sum(item.vms for item in child_memory)
            
            # 获取网络信息
            network = psutil.net_io_counters()
            
            # 获取音频缓存信息
            from kookvoice.kookvoice import audio_cache, cache_max_size, get_cleanup_stats
            cache_count = len(audio_cache)
            cache_size = sum(cache_data.get('size', 0) for cache_data in audio_cache.values())
            cleanup_stats = get_cleanup_stats()
            
            # 调试信息：记录缓存状态
            logger.debug(f'缓存统计 - 数量: {cache_count}, 大小: {cache_size} bytes, 缓存键: {list(audio_cache.keys())}')
            
            # 获取播放状态
            active_guilds = len(kookvoice.play_list)
            playing_songs = 0
            queued_songs = 0
            
            for guild_data in kookvoice.play_list.values():
                if guild_data.get('now_playing'):
                    playing_songs += 1
                queued_songs += len(guild_data.get('play_list', []))
            
            return jsonify({
                'success': True,
                'system': {
                    'cpu_percent': cpu_percent,
                    'memory': {
                        'total': memory.total,
                        'available': memory.available,
                        'percent': memory.percent,
                        'used': memory.used
                    },
                    'disk': {
                        'total': disk.total,
                        'used': disk.used,
                        'free': disk.free,
                        'percent': (disk.used / disk.total) * 100
                    },
                    'network': {
                        'bytes_sent': network.bytes_sent,
                        'bytes_recv': network.bytes_recv,
                        'packets_sent': network.packets_sent,
                        'packets_recv': network.packets_recv
                    }
                },
                'process': {
                    'pid': process.pid,
                    # 包含由 run.py 管理的本地网易云 Node 子进程。
                    'memory_rss': process_memory_rss,
                    'memory_vms': process_memory_vms,
                    'cpu_percent': process_cpu + child_cpu,
                    'child_count': len(child_memory),
                    'create_time': process.create_time(),
                    'uptime': time.time() - process.create_time()
                },
                'audio_cache': {
                    'count': cache_count,
                    'max_size': cache_max_size,
                    'total_size': cache_size,
                    'size_mb': cache_size / 1024 / 1024
                },
                'cleanup_stats': cleanup_stats,
                'playback': {
                    'active_guilds': active_guilds,
                    'playing_songs': playing_songs,
                    'queued_songs': queued_songs
                },
                'timestamp': time.time()
            })
        except Exception as e:
            logger.error(f"获取系统状态异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/logs', methods=['GET'])
    def get_logs():
        """获取日志信息"""
        try:
            import os
            lines = request.args.get('lines', 100, type=int)
            log_type = request.args.get('type', 'app', type=str)
            
            # 确定日志文件路径
            if log_type == 'app':
                log_file = LOG_DIRECTORY / 'app.log'
            elif log_type == 'debug':
                log_file = LOG_DIRECTORY / 'debug.log'
            else:
                return jsonify({'success': False, 'error': '无效的日志类型'})
            
            # 读取日志文件
            if not os.path.exists(log_file):
                return jsonify({'success': False, 'error': '日志文件不存在'})
            
            # 读取最后N行
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            
            # 解析日志行
            logs = []
            for line in recent_lines:
                line = line.strip()
                if line:
                    # 简单的日志解析
                    if ' - ' in line:
                        parts = line.split(' - ', 2)
                        if len(parts) >= 3:
                            timestamp = parts[0]
                            level = parts[1]
                            message = parts[2]
                            
                            # 确定日志级别
                            if 'ERROR' in level:
                                log_level = 'error'
                            elif 'WARNING' in level:
                                log_level = 'warning'
                            elif 'INFO' in level:
                                log_level = 'info'
                            elif 'DEBUG' in level:
                                log_level = 'debug'
                            else:
                                log_level = 'info'
                            
                            logs.append({
                                'timestamp': timestamp,
                                'level': log_level,
                                'message': message,
                                'raw': line
                            })
                        else:
                            logs.append({
                                'timestamp': '',
                                'level': 'info',
                                'message': line,
                                'raw': line
                            })
                    else:
                        logs.append({
                            'timestamp': '',
                            'level': 'info',
                            'message': line,
                            'raw': line
                        })
            
            return jsonify({
                'success': True,
                'logs': logs,
                'total_lines': len(all_lines),
                'returned_lines': len(logs),
                'log_type': log_type
            })
            
        except Exception as e:
            logger.error(f"获取日志异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/logs/clear', methods=['POST'])
    def clear_logs():
        """清空日志文件"""
        try:
            log_type = request.json.get('type', 'app') if request.json else 'app'
            
            if log_type == 'app':
                log_file = LOG_DIRECTORY / 'app.log'
            elif log_type == 'debug':
                log_file = LOG_DIRECTORY / 'debug.log'
            else:
                return jsonify({'success': False, 'error': '无效的日志类型'})
            
            # 清空日志文件
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write('')
            
            return jsonify({'success': True, 'message': f'{log_type}日志已清空'})
            
        except Exception as e:
            logger.error(f"清空日志异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/system/cleanup', methods=['POST'])
    def manual_cleanup():
        """手动清理缓存和内存"""
        try:
            import psutil
            from kookvoice.kookvoice import audio_cache, song_play_count, cleanup_audio_cache, gc, cache_max_size
            
            # 记录清理前的状态
            cache_before = len(audio_cache)
            memory_before = psutil.Process().memory_info()
            
            # 手动清理：清空所有音频缓存
            audio_cache.clear()
            
            # 记录清理后的状态
            cache_after = len(audio_cache)
            cache_cleared = cache_before - cache_after
            
            # 重置播放计数
            song_play_count.clear()
            
            # 强制垃圾回收
            gc.collect()
            
            # 记录清理后的状态
            memory_after = psutil.Process().memory_info()
            memory_freed = (memory_before.rss - memory_after.rss) / 1024 / 1024
            
            return jsonify({
                'success': True,
                'message': '手动清理完成',
                'details': {
                    'cache_cleared': cache_cleared,
                    'cache_before': cache_before,
                    'cache_after': cache_after,
                    'memory_freed_mb': round(memory_freed, 2),
                    'memory_before_mb': round(memory_before.rss / 1024 / 1024, 2),
                    'memory_after_mb': round(memory_after.rss / 1024 / 1024, 2)
                }
            })
            
        except Exception as e:
            logger.error(f"手动清理异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/system/cleanup/config', methods=['POST'])
    def update_cleanup_config():
        """更新清理配置"""
        try:
            from kookvoice.kookvoice import cleanup_threshold
            
            data = request.json
            if not data:
                return jsonify({'success': False, 'error': '请求数据为空'})
            
            new_threshold = data.get('threshold')
            if new_threshold is not None:
                if not isinstance(new_threshold, int) or new_threshold < 1 or new_threshold > 10:
                    return jsonify({'success': False, 'error': '清理阈值必须在1-10之间'})
                
                # 更新全局变量
                import kookvoice.kookvoice
                kookvoice.kookvoice.cleanup_threshold = new_threshold
                
                return jsonify({
                    'success': True,
                    'message': f'清理阈值已更新为 {new_threshold} 首歌曲',
                    'new_threshold': new_threshold
                })
            else:
                return jsonify({'success': False, 'error': '缺少threshold参数'})
                
        except Exception as e:
            logger.error(f"更新清理配置异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/terminal/output', methods=['GET'])
    def get_terminal_output():
        """获取终端输出"""
        try:
            import subprocess
            import os
            
            # 获取请求参数
            last_position = request.args.get('last_position', 0, type=int)
            
            # 获取最新的终端输出
            log_file = LOG_DIRECTORY / 'app.log'
            if os.path.exists(log_file):
                # 获取文件大小
                file_size = os.path.getsize(log_file)
                
                # 如果文件大小小于上次位置，说明文件被清空了
                if file_size < last_position:
                    last_position = 0
                
                # 只读取新增的内容
                if file_size > last_position:
                    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(last_position)
                        output = f.read()
                else:
                    output = ""
                
                # 调试信息
                logger.debug(f'终端输出API - 文件大小: {file_size}, 上次位置: {last_position}, 新内容长度: {len(output)}')
                    
                return jsonify({
                    'success': True,
                    'output': output,
                    'timestamp': time.time(),
                    'file_size': file_size,
                    'last_position': last_position
                })
            else:
                return jsonify({
                    'success': True,
                    'output': '日志文件不存在',
                    'timestamp': time.time(),
                    'file_size': 0,
                    'last_position': 0
                })
                
        except Exception as e:
            logger.error(f"获取终端输出异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/terminal/command', methods=['POST'])
    def execute_terminal_command():
        """执行终端命令"""
        try:
            data = request.json
            if not data or 'command' not in data:
                return jsonify({'success': False, 'error': '缺少命令参数'})
            
            command = data['command']
            
            # 安全检查：只允许特定的安全命令
            allowed_commands = [
                'ps', 'top', 'htop', 'df', 'free', 'uptime', 'whoami',
                'pwd', 'ls', 'cat', 'tail', 'head', 'grep', 'find'
            ]
            
            command_base = command.split()[0] if command.split() else ''
            if command_base not in allowed_commands:
                return jsonify({'success': False, 'error': f'不允许执行命令: {command_base}'})
            
            # 执行命令
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return jsonify({
                'success': True,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode,
                'command': command
            })
            
        except subprocess.TimeoutExpired:
            return jsonify({'success': False, 'error': '命令执行超时'})
        except Exception as e:
            logger.error(f"执行终端命令异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    

    
    @app.route('/api/cache/test', methods=['POST'])
    def test_cache():
        """测试缓存功能"""
        try:
            from kookvoice.kookvoice import audio_cache
            import threading
            
            # 创建一个测试音频文件
            test_file = "test_audio.mp3"
            
            # 在后台线程中预加载测试文件
            def run_test_preload():
                try:
                    cache_key = f"{test_file}:0"
                    if cache_key not in audio_cache:
                        # 模拟预加载过程
                        audio_cache[cache_key] = {
                            'data': b'test_audio_data_' + str(time.time()).encode(),
                            'timestamp': time.time(),
                            'size': 1024 * 1024  # 1MB
                        }
                        logger.info(f'测试缓存添加成功: {cache_key}')
                    else:
                        logger.info(f'测试缓存已存在: {cache_key}')
                except Exception as e:
                    logger.error(f'测试缓存失败: {e}')
            
            # 启动测试线程
            test_thread = threading.Thread(target=run_test_preload)
            test_thread.daemon = True
            test_thread.start()
            
            return jsonify({
                'success': True,
                'message': '测试缓存已启动',
                'cache_count': len(audio_cache)
            })
            
        except Exception as e:
            logger.error(f"测试缓存异常: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    # 如果SocketIO可用，注册SocketIO事件
    if socketio:
        @socketio.on('connect')
        def handle_connect():
            logger.info('客户端已连接')
        
        @socketio.on('disconnect')
        def handle_disconnect():
            logger.info('客户端已断开连接')
        
        @socketio.on('join_room')
        def handle_join_room(data):
            guild_id = data.get('guild_id')
            if guild_id:
                socketio.join_room(guild_id)
                logger.info(f'客户端加入房间: {guild_id}')
        
        @socketio.on('leave_room')
        def handle_leave_room(data):
            guild_id = data.get('guild_id')
            if guild_id:
                socketio.leave_room(guild_id)
                logger.info(f'客户端离开房间: {guild_id}')

# 辅助函数
async def get_guild_list(bot):
    """获取服务器列表"""
    try:
        guilds = await bot.client.gate.request('GET', 'guild/list')
        if guilds and "items" in guilds:
            return guilds["items"]
        return []
    except Exception as e:
        logger.error(f"获取服务器列表异常: {e}")
        return []

async def get_channel_list(bot, guild_id):
    """获取频道列表"""
    try:
        channels = await bot.client.gate.request('GET', 'channel/list', params={'guild_id': guild_id})
        if channels and "items" in channels:
            # 过滤出语音频道
            voice_channels = [c for c in channels["items"] if c.get('type') == 2]
            return voice_channels
        return []
    except Exception as e:
        logger.error(f"获取频道列表异常: {e}")
        return []
