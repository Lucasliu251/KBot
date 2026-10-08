from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import recommendation_service
import central_auth
import routes
from routes import register_routes


class RecommendationRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_db_path = recommendation_service.DB_PATH
        recommendation_service.DB_PATH = Path(self.temp_directory.name) / 'recommendations.sqlite3'
        recommendation_service.initialize()

        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='recommendation-test-secret')
        register_routes(app, object())
        self.client = app.test_client()
        self.auth = None
        self.patcher = patch.object(central_auth, 'read_session', side_effect=lambda cookie: self.auth if cookie else None)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.member = patch.object(central_auth, 'guild_member', side_effect=lambda payload, guild_id: guild_id == 'guild-1')
        self.member.start()
        self.addCleanup(self.member.stop)

    def tearDown(self) -> None:
        recommendation_service.DB_PATH = self.original_db_path
        self.temp_directory.cleanup()

    def _login(self) -> None:
        self.auth = {
            'authenticated': True,
            'user': {'id': 'user-1', 'display_name': 'Lucas', 'avatar_url': '', 'alias_ids': []},
            'identities': [{'provider': 'kook', 'subject': 'platform-user-1'}],
            'csrf_token': 'test-csrf',
        }
        self.client.set_cookie('localhost', 'trashbox_session', 'test-session')
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = 'test-csrf'

    def test_login_membership_idempotency_and_withdrawal(self) -> None:
        track = {
            'id': '12345',
            'provider': 'netease',
            'name': '测试歌曲',
            'artist': '测试艺术家',
            'album': '测试专辑',
            'cover': 'https://example.com/cover.jpg',
            'duration': 240,
        }
        unauthenticated = self.client.post('/api/recommendations/toggle', json={
            'guild_id': 'guild-1',
            'track': track,
            'active': True,
        })
        self.assertEqual(unauthenticated.status_code, 401)

        self._login()
        forbidden = self.client.post('/api/recommendations/toggle', json={
            'guild_id': 'guild-2',
            'track': track,
            'active': True,
        })
        self.assertEqual(forbidden.status_code, 403)

        first = self.client.post('/api/recommendations/toggle', json={
            'guild_id': 'guild-1',
            'track': track,
            'active': True,
        })
        second = self.client.post('/api/recommendations/toggle', json={
            'guild_id': 'guild-1',
            'track': track,
            'active': True,
        })
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.get_json()['recommendation_count'], 1)

        board = self.client.get('/api/recommendations?guild_id=guild-1&sort=popular')
        self.assertEqual(board.status_code, 200)
        self.assertEqual(board.get_json()['total'], 1)
        self.assertTrue(board.get_json()['items'][0]['viewer_recommended'])

        withdrawn = self.client.post('/api/recommendations/toggle', json={
            'guild_id': 'guild-1',
            'track': track,
            'active': False,
        })
        self.assertFalse(withdrawn.get_json()['active'])
        empty_board = self.client.get('/api/recommendations?guild_id=guild-1')
        self.assertEqual(empty_board.get_json()['items'], [])

    def test_legacy_oauth_urls_use_central_login(self) -> None:
        start = self.client.get('/api/auth/kook/url?return_to=/Music/123')
        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.get_json()['authorization_url'], '/login?return_to=%2FMusic%2F123')
        callback = self.client.get('/api/auth/kook/callback?code=old-code&state=old-state')
        self.assertEqual(callback.status_code, 302)
        self.assertTrue(callback.headers['Location'].endswith('/login?return_to=%2FMusic%2F'))
        with self.client.session_transaction() as session:
            self.assertNotIn('recommendation_user', session)
            self.assertNotIn('kook_oauth_state', session)

    def test_login_redirect_restricts_return_to_to_music(self) -> None:
        for value in ('https://evil.example/steal', '//evil.example/', '/account'):
            response = self.client.get('/api/auth/kook/url', query_string={'return_to': value})
            self.assertEqual(response.get_json()['authorization_url'], '/login?return_to=%2FMusic%2F')

    def test_network_latency_segments_are_independent(self) -> None:
        self._login()
        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {'code': 0, 'data': {'id': 'bot'}}

        ping = self.client.get('/api/network/ping')
        self.assertEqual(ping.status_code, 200)

        transport = {
            'rtp_ip': '127.0.0.1',
            'actual_fps': 49.98,
            'target_fps': 50.0,
            'late_frames': 2,
            'resyncs': 1,
            'max_lateness_ms': 8.4,
        }
        with (
            patch.object(routes, 'BOT_TOKEN', 'test-token'),
            patch.object(routes.KOOK_LATENCY_SESSION, 'get', return_value=Response()),
            patch.object(routes, 'measure_icmp_latency', return_value=7.2),
            patch.object(routes.kookvoice, 'get_voice_transport_metrics', return_value=transport),
        ):
            response = self.client.get('/api/network/latency?guild_id=guild-1')

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['online'])
        self.assertEqual(payload['voice_gateway_ms'], 7.2)
        self.assertEqual(payload['transport']['actual_fps'], 49.98)
        self.assertEqual(payload['transport']['target_fps'], 50.0)


if __name__ == '__main__':
    unittest.main()
