from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

import routes
from routes import register_routes


class BilibiliRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='bilibili-route-test')
        register_routes(app, object())
        self.client = app.test_client()

    def test_play_adds_resolved_bilibili_track_with_cover(self) -> None:
        captured = {}

        class Player:
            def __init__(self, guild_id, channel_id, token):
                captured['guild_id'] = guild_id
                captured['channel_id'] = channel_id

            def add_music(self, source, extra):
                captured['source'] = source
                captured['extra'] = extra

        resolved = {
            'url': 'https://media.example/audio.m4s?deadline=2000000000',
            'expires_at': 2000000000,
            'duration': 223,
            'title': '测试视频',
            'artist': '测试UP主',
            'cover': 'https://i1.hdslb.com/test-cover.jpg',
            'webpage_url': 'https://www.bilibili.com/video/BV1TEST123',
            'headers': {
                'User-Agent': 'test-agent',
                'Referer': 'https://www.bilibili.com/video/BV1TEST123',
            },
        }
        with (
            patch.object(routes.bilibili, 'resolve_audio', return_value=resolved),
            patch.object(routes.kookvoice, 'Player', Player),
        ):
            response = self.client.post('/api/play', json={
                'guild_id': 'guild-1',
                'channel_id': 'channel-1',
                'song_id': 'encoded-locator',
                'song_name': '测试视频',
                'artist_name': '测试UP主',
                'album_name': 'Bilibili 视频',
                'cover_url': '',
                'duration': 223,
                'provider': 'bilibili',
            })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        self.assertEqual(captured['source'], 'MUSIC_SOURCE:bilibili:encoded-locator')
        self.assertEqual(captured['extra']['cover'], 'https://i1.hdslb.com/test-cover.jpg')
        self.assertIn('Referer: https://www.bilibili.com/video/BV1TEST123', captured['extra']['header'])


if __name__ == '__main__':
    unittest.main()
