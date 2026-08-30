"""KOOK OAuth helper for recommendation identities."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests

from config import (
    KOOK_OAUTH_AUTHORIZE_URL,
    KOOK_OAUTH_CLIENT_ID,
    KOOK_OAUTH_CLIENT_SECRET,
    KOOK_OAUTH_REDIRECT_URI,
    KOOK_OAUTH_SCOPES,
)


KOOK_API_ROOT = 'https://www.kookapp.cn/api'


class KookOAuthError(RuntimeError):
    pass


def oauth_configured() -> bool:
    return bool(KOOK_OAUTH_CLIENT_ID and KOOK_OAUTH_CLIENT_SECRET and KOOK_OAUTH_REDIRECT_URI)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def authorization_url(state: str) -> str:
    if not oauth_configured():
        raise KookOAuthError('服务器尚未配置 KOOK OAuth，请在 .env 填写 OAuth 客户端信息')
    return f'{KOOK_OAUTH_AUTHORIZE_URL}?{urlencode({
        "client_id": KOOK_OAUTH_CLIENT_ID,
        "redirect_uri": KOOK_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": KOOK_OAUTH_SCOPES,
        "state": state,
    })}'


def exchange_code(code: str) -> str:
    if not oauth_configured():
        raise KookOAuthError('KOOK OAuth 未配置')
    response = requests.post(
        f'{KOOK_API_ROOT}/oauth2/token',
        data={
            'grant_type': 'authorization_code',
            'client_id': KOOK_OAUTH_CLIENT_ID,
            'client_secret': KOOK_OAUTH_CLIENT_SECRET,
            'code': code,
            'redirect_uri': KOOK_OAUTH_REDIRECT_URI,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    token = str((data or {}).get('access_token') or '')
    if not token:
        raise KookOAuthError(payload.get('message') or 'KOOK 没有返回 AccessToken')
    return token


def _oauth_get(path: str, token: str, params: dict | None = None) -> dict:
    response = requests.get(
        f'{KOOK_API_ROOT}{path}',
        headers={'Authorization': f'Bearer {token}'},
        params=params,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if int(payload.get('code', 0)) != 0:
        raise KookOAuthError(payload.get('message') or f'KOOK OAuth API 异常: {path}')
    return payload.get('data') or {}


def fetch_identity(token: str) -> tuple[dict, list[str]]:
    user = _oauth_get('/v3/user/me', token)
    user_id = str(user.get('id') or '')
    if not user_id:
        raise KookOAuthError('KOOK 用户信息缺少用户 ID')
    identity = {
        'id': user_id,
        'username': str(user.get('username') or ''),
        'nickname': str(user.get('nickname') or user.get('username') or ''),
        'avatar': str(user.get('avatar') or user.get('vip_avatar') or ''),
    }
    guild_ids = []
    page = 1
    while True:
        guild_data = _oauth_get('/v3/guild/list', token, {'page': page, 'page_size': 50})
        guild_ids.extend(
            str(item.get('id'))
            for item in (guild_data.get('items') or [])
            if item.get('id')
        )
        meta = guild_data.get('meta') or {}
        page_total = max(1, min(int(meta.get('page_total') or 1), 100))
        if page >= page_total:
            break
        page += 1
    return identity, guild_ids
