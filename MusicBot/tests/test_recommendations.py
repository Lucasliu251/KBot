from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import recommendation_service
import recommendation_auth
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

    def tearDown(self) -> None:
        recommendation_service.DB_PATH = self.original_db_path
        self.temp_directory.cleanup()

    def _login(self) -> None:
        with self.client.session_transaction() as session:
            session['recommendation_user'] = {
                'id': 'user-1',
                'username': 'lucas',
                'nickname': 'Lucas',
                'avatar': '',
            }
            session['recommendation_guild_ids'] = ['guild-1']

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

    def test_oauth_state_return_path_and_session_identity(self) -> None:
        with patch.object(recommendation_auth, 'authorization_url', return_value='https://www.kookapp.cn/oauth-test'):
            start = self.client.get('/api/auth/kook/url?return_to=/Music/123')
        self.assertEqual(start.status_code, 200)
        with self.client.session_transaction() as session:
            state = session['kook_oauth_state']
            self.assertEqual(session['kook_oauth_return_to'], '/Music/123')

        identity = {'id': 'oauth-user', 'username': 'OAuth', 'nickname': 'OAuth', 'avatar': ''}
        with (
            patch.object(recommendation_auth, 'exchange_code', return_value='short-lived-token'),
            patch.object(recommendation_auth, 'fetch_identity', return_value=(identity, ['guild-1'])),
        ):
            callback = self.client.get(f'/api/auth/kook/callback?code=valid-code&state={state}')
        self.assertEqual(callback.status_code, 302)
        self.assertTrue(callback.headers['Location'].endswith('/Music/123?oauth=success'))
        with self.client.session_transaction() as session:
            self.assertEqual(session['recommendation_user']['id'], 'oauth-user')
            self.assertNotIn('short-lived-token', str(dict(session)))

    def test_oauth_rejects_external_return_and_invalid_state(self) -> None:
        with patch.object(recommendation_auth, 'authorization_url', return_value='https://www.kookapp.cn/oauth-test'):
            self.client.get('/api/auth/kook/url?return_to=https://evil.example/steal')
        with self.client.session_transaction() as session:
            self.assertEqual(session['kook_oauth_return_to'], '/')

        with patch.object(recommendation_auth, 'exchange_code') as exchange_code:
            callback = self.client.get('/api/auth/kook/callback?code=valid-code&state=wrong-state')
        self.assertEqual(callback.status_code, 302)
        self.assertIn('/?oauth=error', callback.headers['Location'])
        exchange_code.assert_not_called()

    def test_network_latency_segments_are_independent(self) -> None:
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
