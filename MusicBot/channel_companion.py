"""Channel housekeeping and one editable now-playing card, outside the RTP loop."""
import json
import logging
import math
import threading
import time
import uuid
from urllib.parse import quote, urlsplit

import requests
try:
    from . import kookvoice
except ImportError:
    import kookvoice

logger = logging.getLogger(__name__)


def number(value, default=0):
    try:
        result = float(value)
        return max(0, result) if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def timestamp(value):
    seconds = int(number(value))
    return f'{seconds // 60}:{seconds % 60:02d}'


def bar(ratio, width=12):
    filled = round(min(1, number(ratio)) * width)
    return '━' * filled + '─' * (width - filled)


def music_card(track, volume, status, channel, public_url, mode='order'):
    extra = track.get('extra') or {}
    duration = number(extra.get('duration'))
    position = number(track.get('ss'))
    volume = min(1, number(volume))
    title, artist, album = (str(extra.get(key) or fallback)[:100] for key, fallback in (
        ('title', '未知歌曲'), ('artist', '未知艺术家'), ('album', '未知专辑')))
    metadata = f'{title} — {artist}\n{album}'
    top = {'type': 'section', 'text': {'type': 'plain-text', 'content': metadata}}
    cover = str(extra.get('cover') or '')
    if urlsplit(cover).scheme in ('https', 'http'):
        top.update(mode='left', accessory={'type': 'image', 'src': cover, 'size': 'sm'})
    progress = bar(position / duration if duration else 0)
    provider = {'netease': '网易云', 'qq': 'QQ音乐', 'qqmusic': 'QQ音乐', 'bilibili': 'Bilibili'}.get(extra.get('provider'), '网易云')
    mode_label = {'order': '顺序播放', 'repeat-one': '单曲循环', 'shuffle': '随机播放'}.get(mode, '顺序播放')
    detail = f'音源: {provider}  |  {mode_label}  |  音量: {round(volume * 100)}%\n{timestamp(position)}  {progress}  {timestamp(duration)}'
    return [{'type': 'card', 'theme': 'info', 'size': 'sm', 'modules': [{
        'type': 'section', 'mode': 'right',
        'text': {'type': 'plain-text', 'content': f'♫ 互联网垃圾桶 · {status}'},
        'accessory': {'type': 'button', 'theme': 'secondary', 'click': 'link',
                      'value': public_url.rstrip('/') + '/' + quote(str(channel), safe=''),
                      'text': {'type': 'plain-text', 'content': '网页面板 ↗'}},
    }, top, {'type': 'context', 'elements': [{'type': 'plain-text', 'content': detail}]}]}]


class KookAPI:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bot {token}'

    def call(self, method, path, data):
        response = self.session.request(method, 'https://www.kookapp.cn/api/v3/' + path,
                                        params=data if method == 'GET' else None,
                                        json=data if method != 'GET' else None, timeout=5)
        response.raise_for_status()
        payload = response.json()
        if payload.get('code') != 0:
            # Never log request headers, tokens, or full user/message payloads.
            raise RuntimeError(f'KOOK {path}: code={payload.get("code")}')
        return payload.get('data')


class ChannelCompanion:
    def __init__(self, token, public_url, api=None, clock=time.monotonic):
        self.api = api or KookAPI(token)
        self.public_url = public_url
        self.clock = clock
        self.sessions = {}
        self.closed = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self.run, name='music-channel-companion', daemon=True)
        self.thread.start()

    def stop(self):
        self.closed.set()

    def run(self):
        try:
            while not self.closed.is_set():
                try:
                    self.step()
                except Exception as error:
                    logger.warning('音乐频道后台任务失败: %s', error)
                self.closed.wait(1)
        finally:
            self.api.session.close()

    def step(self):
        now = self.clock()
        for guild, playlist in list(kookvoice.play_list.items()):
            channel = playlist.get('voice_channel')
            if not channel:
                continue
            old = self.sessions.get(guild)
            if old and old['playlist'] is not playlist:
                self.finish(old)
                self.sessions.pop(guild, None)
            state = self.sessions.setdefault(guild, dict(playlist=playlist, channel=channel,
                check_at=0, empty_since=None, card_at=0, msg_id=None, track=None, volume=0.4,
                nonce=uuid.uuid4().hex))
            if kookvoice.guild_status.get(guild) == kookvoice.Status.STOP:
                continue
            if now >= state['check_at']:
                state['check_at'] = now + 15
                try:
                    users = self.api.call('GET', 'channel/user-list', {'channel_id': channel})
                    if not isinstance(users, list) or any(not isinstance(user, dict) for user in users):
                        raise ValueError('频道成员响应格式异常')
                    if kookvoice.play_list.get(guild) is not playlist or playlist.get('voice_channel') != channel:
                        continue
                    # Missing bot flags are conservatively treated as human users.
                    if any(user.get('bot') not in (True, 1) for user in users):
                        state['empty_since'] = None
                    elif state['empty_since'] is None:
                        state['empty_since'] = now
                        state['check_at'] = now + 5
                    elif now - state['empty_since'] >= 5:
                        player = kookvoice.Player(guild)
                        player.clear()
                        player.stop()
                        logger.info('语音频道无人，已清空音乐并请求退出: %s', channel)
                        continue
                except Exception as error:
                    state['empty_since'] = None
                    logger.warning('检查语音频道成员失败，保持连接: %s', error)
            if kookvoice.play_list.get(guild) is not playlist:
                continue
            track = playlist.get('now_playing')
            status = kookvoice.guild_status.get(guild)
            if track and track.get('start') and status in (kookvoice.Status.PLAYING, kookvoice.Status.PAUSE):
                state['track'] = {**track, 'extra': dict(track.get('extra') or {})}
                state['volume'] = kookvoice.guild_volume.get(guild, 0.4)
                state['mode'] = kookvoice.guild_play_mode.get(guild, 'order')
                if now >= state['card_at']:
                    state['card_at'] = now + 10
                    self.publish(state, '已暂停' if status == kookvoice.Status.PAUSE else '正在播放')
        for guild, state in list(self.sessions.items()):
            if guild not in kookvoice.play_list:
                self.finish(state)
                self.sessions.pop(guild, None)

    def publish(self, state, status):
        try:
            content = json.dumps(music_card(state['track'], state['volume'], status,
                                           state['channel'], self.public_url, state.get('mode', 'order')), ensure_ascii=False)
            if state['msg_id']:
                self.api.call('POST', 'message/update', {'msg_id': state['msg_id'], 'content': content})
            else:
                result = self.api.call('POST', 'message/create', {
                    'type': 10, 'target_id': state['channel'], 'content': content, 'nonce': state['nonce']})
                state['msg_id'] = result['msg_id']
        except Exception as error:
            logger.warning('更新音乐卡片失败（请检查频道发消息权限）: %s', error)

    def finish(self, state):
        if state['msg_id'] and state['track'] and not state.get('finished'):
            self.publish(state, '已结束 · 已离开频道')
            state['finished'] = True
