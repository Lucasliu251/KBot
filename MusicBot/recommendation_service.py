"""Small-community recommendation board backed by SQLite."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config import RECOMMENDATION_DB_PATH


DB_PATH = Path(RECOMMENDATION_DB_PATH)
_db_lock = threading.RLock()
ALLOWED_PROVIDERS = {'netease', 'bilibili', 'qqmusic'}


class RecommendationError(RuntimeError):
    pass


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA journal_mode = WAL')
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize() -> None:
    with _db_lock, _database() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                nickname TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                provider_track_id TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL DEFAULT '',
                album TEXT NOT NULL DEFAULT '',
                cover TEXT NOT NULL DEFAULT '',
                duration REAL NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(guild_id, provider, provider_track_id)
            );

            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                note TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(guild_id, track_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_recommendations_board
                ON recommendations(guild_id, active, updated_at DESC);
        ''')
        try:
            os.chmod(DB_PATH, 0o600)
        except OSError:
            pass


def _text(value: Any, maximum: int) -> str:
    return str(value or '').strip()[:maximum]


def _normalize_track(track: dict[str, Any]) -> dict[str, Any]:
    provider = _text(track.get('provider'), 32).lower()
    provider_track_id = _text(track.get('id'), 2048)
    title = _text(track.get('name') or track.get('title'), 300)
    if provider not in ALLOWED_PROVIDERS:
        raise RecommendationError('不支持的推荐音源')
    if not provider_track_id or not title:
        raise RecommendationError('推荐歌曲缺少 ID 或标题')
    try:
        duration = max(0.0, min(float(track.get('duration') or 0), 86400.0))
    except (TypeError, ValueError):
        duration = 0.0
    return {
        'provider': provider,
        'provider_track_id': provider_track_id,
        'title': title,
        'artist': _text(track.get('artist'), 300),
        'album': _text(track.get('album'), 300),
        'cover': _text(track.get('cover'), 2048),
        'duration': duration,
    }


def upsert_user(identity: dict[str, Any]) -> None:
    now = int(time.time())
    with _db_lock, _database() as db:
        db.execute('''
            INSERT INTO users(user_id, username, nickname, avatar, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                nickname=excluded.nickname,
                avatar=excluded.avatar,
                updated_at=excluded.updated_at
        ''', (
            _text(identity.get('id'), 64),
            _text(identity.get('username'), 128),
            _text(identity.get('nickname'), 128),
            _text(identity.get('avatar'), 2048),
            now,
        ))


def toggle(
    guild_id: str,
    identity: dict[str, Any],
    track: dict[str, Any],
    note: str = '',
    active: bool | None = None,
) -> dict[str, Any]:
    guild_id = _text(guild_id, 64)
    if not guild_id:
        raise RecommendationError('缺少 KOOK 服务器 ID')
    normalized = _normalize_track(track)
    user_id = _text(identity.get('id'), 64)
    if not user_id:
        raise RecommendationError('推荐用户身份无效')
    note = _text(note, 40)
    now = int(time.time())

    with _db_lock, _database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''
            INSERT INTO users(user_id, username, nickname, avatar, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                nickname=excluded.nickname,
                avatar=excluded.avatar,
                updated_at=excluded.updated_at
        ''', (
            user_id,
            _text(identity.get('username'), 128),
            _text(identity.get('nickname'), 128),
            _text(identity.get('avatar'), 2048),
            now,
        ))
        db.execute('''
            INSERT INTO tracks(
                guild_id, provider, provider_track_id, title, artist, album,
                cover, duration, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, provider, provider_track_id) DO UPDATE SET
                title=excluded.title,
                artist=excluded.artist,
                album=excluded.album,
                cover=excluded.cover,
                duration=excluded.duration,
                updated_at=excluded.updated_at
        ''', (
            guild_id,
            normalized['provider'],
            normalized['provider_track_id'],
            normalized['title'],
            normalized['artist'],
            normalized['album'],
            normalized['cover'],
            normalized['duration'],
            now,
            now,
        ))
        track_id = db.execute('''
            SELECT id FROM tracks
            WHERE guild_id=? AND provider=? AND provider_track_id=?
        ''', (guild_id, normalized['provider'], normalized['provider_track_id'])).fetchone()['id']
        existing = db.execute('''
            SELECT active FROM recommendations
            WHERE guild_id=? AND track_id=? AND user_id=?
        ''', (guild_id, track_id, user_id)).fetchone()
        next_active = bool(active) if active is not None else not bool(existing and existing['active'])
        db.execute('''
            INSERT INTO recommendations(
                guild_id, track_id, user_id, note, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, track_id, user_id) DO UPDATE SET
                note=CASE WHEN excluded.note != '' THEN excluded.note ELSE recommendations.note END,
                active=excluded.active,
                updated_at=excluded.updated_at
        ''', (guild_id, track_id, user_id, note, int(next_active), now, now))
        count = db.execute('''
            SELECT COUNT(*) AS count FROM recommendations
            WHERE guild_id=? AND track_id=? AND active=1
        ''', (guild_id, track_id)).fetchone()['count']
        return {
            'active': next_active,
            'recommendation_count': int(count),
            'key': f'{normalized["provider"]}:{normalized["provider_track_id"]}',
        }


def list_board(
    guild_id: str,
    viewer_user_id: str = '',
    sort: str = 'latest',
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    guild_id = _text(guild_id, 64)
    sort = 'popular' if sort == 'popular' else 'latest'
    limit = max(1, min(50, int(limit)))
    offset = max(0, int(offset))
    order_sql = 'recommendation_count DESC, latest_at DESC' if sort == 'popular' else 'latest_at DESC'

    with _db_lock, _database() as db:
        total = db.execute('''
            SELECT COUNT(*) AS count FROM (
                SELECT track_id FROM recommendations
                WHERE guild_id=? AND active=1 GROUP BY track_id
            )
        ''', (guild_id,)).fetchone()['count']
        rows = db.execute(f'''
            SELECT
                t.*,
                COUNT(r.id) AS recommendation_count,
                MAX(r.updated_at) AS latest_at,
                MAX(CASE WHEN r.user_id=? AND r.active=1 THEN 1 ELSE 0 END) AS viewer_recommended
            FROM tracks t
            JOIN recommendations r ON r.track_id=t.id AND r.guild_id=t.guild_id AND r.active=1
            WHERE t.guild_id=?
            GROUP BY t.id
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        ''', (viewer_user_id, guild_id, limit, offset)).fetchall()

        items = []
        for row in rows:
            recommenders = db.execute('''
                SELECT u.user_id, u.username, u.nickname, u.avatar, r.note, r.updated_at
                FROM recommendations r
                JOIN users u ON u.user_id=r.user_id
                WHERE r.guild_id=? AND r.track_id=? AND r.active=1
                ORDER BY r.updated_at DESC
            ''', (guild_id, row['id'])).fetchall()
            people = [dict(person) for person in recommenders]
            note = next((person['note'] for person in people if person.get('note')), '')
            items.append({
                'id': str(row['provider_track_id']),
                'provider': row['provider'],
                'name': row['title'],
                'artist': row['artist'],
                'album': row['album'],
                'cover': row['cover'],
                'duration': float(row['duration']),
                'recommendation_count': int(row['recommendation_count']),
                'latest_at': int(row['latest_at']),
                'viewer_recommended': bool(row['viewer_recommended']),
                'note': note,
                'recommenders': people,
            })
        return {
            'items': items,
            'total': int(total),
            'offset': offset,
            'limit': limit,
            'has_more': offset + len(items) < int(total),
            'sort': sort,
        }


initialize()
