"""TrashBox central session validation for the Music service.

Only the central session cookie crosses the server boundary. Music never stores
OAuth access tokens or accepts its former standalone Flask identity cookie.
"""
from __future__ import annotations

import hmac
from urllib.parse import urlencode, urlsplit, urlunsplit, unquote

import requests
from flask import g, request
from config import TRASHBOX_AUTH_SESSION_URL, TRASHBOX_LOGIN_URL, BOT_TOKEN

COOKIE_NAME = 'trashbox_session'

class AuthUnavailable(RuntimeError):
    pass


def read_session(cookie: str) -> dict | None:
    if not cookie:
        return None
    try:
        response = requests.get(
            TRASHBOX_AUTH_SESSION_URL,
            cookies={COOKIE_NAME: cookie},
            timeout=4,
            allow_redirects=False,
        )
        if response.status_code == 401:
            return None
        if response.status_code != 200:
            raise AuthUnavailable('统一登录服务暂时不可用')
        payload = response.json()
        user = payload.get('user') if isinstance(payload, dict) else None
        if not isinstance(payload, dict):
            raise AuthUnavailable('统一登录服务响应无效')
        if not payload.get('authenticated') or not isinstance(user, dict) or not user.get('id'):
            return None
        return payload
    except (requests.RequestException, ValueError):
        raise AuthUnavailable('统一登录服务暂时不可用') from None


def current_session() -> dict | None:
    if not hasattr(g, 'trashbox_auth'):
        g.trashbox_auth = read_session(request.cookies.get(COOKIE_NAME, ''))
    return g.trashbox_auth


def valid_csrf(payload: dict | None, supplied: str = '') -> bool:
    expected = str((payload or {}).get('csrf_token') or '')
    return bool(expected and supplied and hmac.compare_digest(expected, str(supplied)))


def music_return_to(value: str = '') -> str:
    parsed = urlsplit(str(value or '/Music/'))
    path = parsed.path
    decoded = unquote(path)
    if any(part == '..' for part in decoded.split('/')):
        return '/Music/'
    if parsed.scheme or parsed.netloc or '\\' in decoded or any(ord(char) < 32 for char in path):
        return '/Music/'
    if not (path == '/Music' or path.startswith('/Music/')):
        return '/Music/'
    return urlunsplit(('', '', path, parsed.query, ''))


def request_return_to() -> str:
    path = request.path
    if request.script_root:
        path = request.script_root.rstrip('/') + path
    if not (path == '/Music' or path.startswith('/Music/')):
        path = '/Music/' if path == '/' else '/Music' + path
    query = request.query_string.decode('utf-8', errors='replace')
    return music_return_to(path + ('?' + query if query else ''))


def login_url(return_to: str = '') -> str:
    parsed = urlsplit(TRASHBOX_LOGIN_URL)
    query = urlencode({'return_to': music_return_to(return_to)})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/login', query, ''))


def identity(payload: dict | None) -> dict | None:
    user = (payload or {}).get('user') or {}
    if not user.get('id'):
        return None
    return {
        'id': str(user['id']),
        'username': str(user.get('display_name') or ''),
        'nickname': str(user.get('display_name') or ''),
        'avatar': str(user.get('avatar_url') or ''),
    }


def verified_aliases(payload: dict) -> list[str]:
    aliases = {str(value) for value in payload['user'].get('alias_ids', []) if value}
    aliases.update(
        str(item['subject']) for item in payload.get('identities', [])
        if isinstance(item, dict) and item.get('provider') == 'kook' and item.get('subject')
    )
    aliases.discard(str(payload['user']['id']))
    return sorted(aliases)


def kook_subject(payload: dict | None) -> str:
    return next((
        str(item['subject']) for item in (payload or {}).get('identities', [])
        if isinstance(item, dict) and item.get('provider') == 'kook' and item.get('subject')
    ), '')


def guild_member(payload: dict, guild_id: str) -> bool:
    subject = kook_subject(payload)
    if not subject or not guild_id or not BOT_TOKEN:
        return False
    try:
        response = requests.get(
            'https://www.kookapp.cn/api/v3/guild/user-list',
            headers={'Authorization': f'Bot {BOT_TOKEN}'},
            params={'guild_id': guild_id, 'filter_user_id': subject},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if data.get('code') != 0:
            return False
        return any(str(item.get('id') or '') == subject for item in (data.get('data') or {}).get('items', []))
    except (requests.RequestException, ValueError):
        raise AuthUnavailable('暂时无法验证 KOOK 服务器成员身份') from None
