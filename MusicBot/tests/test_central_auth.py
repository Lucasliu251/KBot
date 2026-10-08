from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from flask import Flask
from flask_socketio import SocketIO
import central_auth
import recommendation_service as service
import routes


SESSION = {
    'authenticated': True,
    'user': {'id': 'central-user', 'display_name': 'Player', 'avatar_url': '', 'alias_ids': []},
    'identities': [{'provider': 'kook', 'subject': 'kook-user'}],
    'csrf_token': 'csrf-test',
}


class CentralAuthTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder='../templates')
        app.config.update(TESTING=True, SECRET_KEY='fixture')
        routes.register_routes(app, object())
        self.client = app.test_client()

    def login(self):
        self.client.set_cookie('localhost', 'trashbox_session', 'fixture-session')

    def test_pages_apis_and_legacy_flask_identity_require_central_session(self):
        with self.client.session_transaction() as old:
            old['recommendation_user'] = {'id': 'forged-old-user'}
        for path in ('/api/play', '/api/logs/clear', '/api/terminal/command'):
            response = self.client.post(path, json={})
            self.assertEqual(response.status_code, 401)
        response = self.client.get('/Music/123?source=card')
        self.assertEqual(response.status_code, 302)
        self.assertIn('return_to=%2FMusic%2F123%3Fsource%3Dcard', response.headers['Location'])
        self.assertEqual(self.client.get('/healthz').get_json(), {'status': 'ok', 'music_http_only': False})

    def test_sensitive_management_routes_require_existing_password_before_any_side_effect(self):
        self.login()
        endpoints = [('GET', '/api/logs'), ('POST', '/api/logs/clear'),
                     ('GET', '/api/terminal/output'), ('POST', '/api/terminal/command')]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'app.log'
            log.write_text('fixture log only\n')
            with patch.object(central_auth, 'read_session', return_value=SESSION), \
                    patch.object(routes, 'MUSIC_SETTINGS_TOKEN', 'fixture-password'), \
                    patch.object(routes, 'LOG_DIRECTORY', Path(directory)), \
                    patch.object(routes.subprocess, 'run') as command:
                for supplied in ('', 'wrong-password'):
                    for method, path in endpoints:
                        response = self.client.open(path, method=method,
                            json={'command': 'uptime', 'type': 'app'} if method == 'POST' else None,
                            headers={'X-CSRF-Token': 'csrf-test', 'X-Music-Settings-Token': supplied})
                        self.assertEqual(response.status_code, 403, path)
                        self.assertIn('管理密钥', response.get_json()['error'])
                command.assert_not_called()
                self.assertEqual(log.read_text(), 'fixture log only\n')
                self.assertEqual(self.client.get('/api/network/ping').status_code, 200)

    def test_sensitive_management_routes_accept_same_password_and_keep_login_and_csrf(self):
        self.login()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'app.log').write_text('fixture log only\n')
            with patch.object(central_auth, 'read_session', return_value=SESSION), \
                    patch.object(routes, 'MUSIC_SETTINGS_TOKEN', 'fixture-password'), \
                    patch.object(routes, 'LOG_DIRECTORY', Path(directory)), \
                    patch.object(routes.subprocess, 'run', return_value=Mock(stdout='mocked', stderr='', returncode=0)) as command:
                headers = {'X-Music-Settings-Token': 'fixture-password', 'X-CSRF-Token': 'csrf-test'}
                for path in ('/api/logs', '/api/terminal/output'):
                    self.assertTrue(self.client.get(path, headers=headers).get_json()['success'])
                self.assertEqual(self.client.post('/api/terminal/command', json={'command': 'uptime'},
                    headers={'X-Music-Settings-Token': 'fixture-password'}).status_code, 403)
                command.assert_not_called()
                executed = self.client.post('/api/terminal/command', json={'command': 'uptime'}, headers=headers)
                self.assertEqual(executed.status_code, 200)
                self.assertEqual(executed.get_json()['stdout'], 'mocked')
                command.assert_called_once()
                cleared = self.client.post('/api/logs/clear', json={'type': 'app'}, headers=headers)
                self.assertEqual(cleared.status_code, 200)
                self.assertEqual((Path(directory) / 'app.log').read_text(), '')
        anonymous = Flask(__name__)
        anonymous.config.update(TESTING=True, SECRET_KEY='fixture')
        routes.register_routes(anonymous, object())
        with patch.object(central_auth, 'read_session', return_value=None):
            for method, path in [('GET', '/api/logs'), ('GET', '/api/terminal/output'),
                                 ('POST', '/api/logs/clear'), ('POST', '/api/terminal/command')]:
                self.assertEqual(anonymous.test_client().open(path, method=method, headers=headers).status_code, 401)

    def test_empty_expected_management_password_fails_closed(self):
        self.login()
        with patch.object(central_auth, 'read_session', return_value=SESSION), \
                patch.object(routes, 'MUSIC_SETTINGS_TOKEN', ''), \
                patch.object(routes.subprocess, 'run') as command:
            for method, path in [('GET', '/api/logs'), ('GET', '/api/terminal/output'),
                                 ('POST', '/api/logs/clear'), ('POST', '/api/terminal/command')]:
                self.assertEqual(self.client.open(path, method=method,
                    json={'command': 'uptime'} if method == 'POST' else None,
                    headers={'X-CSRF-Token': 'csrf-test', 'X-Music-Settings-Token': 'anything'}).status_code, 403)
            command.assert_not_called()

    def test_valid_session_allows_non_kook_accounts_and_csrf_is_required(self):
        self.login()
        with patch.object(central_auth, 'read_session', return_value={**SESSION, 'identities': []}):
            self.assertEqual(self.client.get('/api/network/ping').status_code, 200)
            self.assertEqual(self.client.post('/api/pause', json={}).status_code, 403)
            accepted = self.client.post('/api/pause', json={}, headers={'X-CSRF-Token': 'csrf-test'})
            self.assertNotEqual(accepted.status_code, 401)
            self.assertNotEqual(accepted.status_code, 403)

    def test_http_only_mode_keeps_auth_gates_and_blocks_voice_side_effects(self):
        self.login()
        with patch.object(central_auth, 'read_session', return_value=SESSION):
            with patch.object(routes, 'MUSIC_HTTP_ONLY', True), patch.object(routes.kookvoice, 'Player') as player:
                self.assertEqual(self.client.get('/api/network/ping').status_code, 200)
                self.assertTrue(self.client.get('/healthz').get_json()['music_http_only'])
                self.assertEqual(self.client.post('/api/play', json={}).status_code, 403)
                self.assertEqual(self.client.post('/api/play', json={}, headers={'X-CSRF-Token': 'csrf-test'}).status_code, 503)
                player.assert_not_called()

    def test_session_errors_fail_closed_without_secret_details(self):
        self.login()
        with patch.object(central_auth.requests, 'get', side_effect=requests.Timeout('private-cookie-must-not-appear')):
            response = self.client.get('/api/network/ping')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-cookie', response.get_data(as_text=True))

    def test_validation_forwards_only_central_cookie_and_never_activity(self):
        self.login()
        self.client.set_cookie('localhost', 'other-service-cookie', 'unrelated-value')
        response = Mock(status_code=200)
        response.json.return_value = SESSION
        with patch.object(central_auth.requests, 'get', return_value=response) as call:
            with patch.object(central_auth.requests, 'post') as post:
                self.assertEqual(self.client.get('/api/network/ping').status_code, 200)
                post.assert_not_called()
        self.assertEqual(call.call_args.kwargs['cookies'], {'trashbox_session': 'fixture-session'})
        self.assertFalse(call.call_args.kwargs['allow_redirects'])

    def test_local_auth_proxy_forwards_only_the_auth_cookie_whitelist(self):
        from urllib3._collections import HTTPHeaderDict
        response = Mock(status_code=200, content=b'{}')
        response.headers = {'Content-Type': 'application/json'}
        response.raw.headers = HTTPHeaderDict({'Set-Cookie': 'trashbox_oauth=fixture; Path=/; HttpOnly'})
        for name in ('trashbox_session', 'trashbox_oauth', 'trashbox_qr', 'unrelated'):
            self.client.set_cookie('localhost', name, 'fixture-' + name)
        with patch.object(routes, 'TRASHBOX_AUTH_FRONTEND_ORIGIN', 'http://127.0.0.1:5175'):
            with patch.object(routes.requests, 'request', return_value=response) as call:
                proxied = self.client.get('/api/v1/auth/kook/callback?state=fixture')
        self.assertEqual(proxied.status_code, 200)
        self.assertEqual(set(call.call_args.kwargs['cookies']), {'trashbox_session', 'trashbox_oauth', 'trashbox_qr'})
        self.assertIn('trashbox_oauth=fixture', proxied.headers['Set-Cookie'])
        with patch.object(routes, 'TRASHBOX_AUTH_FRONTEND_ORIGIN', 'http://127.0.0.1:5175'):
            with patch.object(routes.requests, 'request', return_value=response) as call:
                anonymous = self.client.post('/api/v1/web-auth/challenges', json={})
                self.assertEqual(anonymous.status_code, 200)
                self.assertTrue(call.call_args.args[1].endswith('/api/v1/web-auth/challenges'))
                polled = self.client.get('/api/v1/web-auth/challenges/dummy-challenge')
                self.assertEqual(polled.status_code, 200)

    def test_activity_requires_csrf_and_only_explicit_post_touches_central_service(self):
        self.login()
        with patch.object(central_auth, 'read_session', return_value=SESSION):
            with patch.object(routes.requests, 'post', return_value=Mock(status_code=204)) as activity:
                self.assertEqual(self.client.get('/api/network/ping').status_code, 200)
                self.assertEqual(self.client.post('/api/auth/activity').status_code, 403)
                activity.assert_not_called()
                self.assertEqual(self.client.post('/api/auth/activity', headers={'X-CSRF-Token': 'csrf-test'}).status_code, 204)
                self.assertTrue(activity.call_args.args[0].endswith('/activity'))
                self.assertEqual(activity.call_args.kwargs['cookies'], {'trashbox_session': 'fixture-session'})

    def test_kook_membership_uses_verified_subject_and_exact_filter(self):
        response = Mock(status_code=200)
        response.json.return_value = {'code': 0, 'data': {'items': [{'id': 'kook-user'}]}}
        with patch.object(central_auth, 'BOT_TOKEN', 'dummy-music-token'):
            with patch.object(central_auth.requests, 'get', return_value=response) as call:
                self.assertTrue(central_auth.guild_member(SESSION, 'guild-1'))
                self.assertEqual(call.call_args.kwargs['params'], {'guild_id': 'guild-1', 'filter_user_id': 'kook-user'})
                response.json.return_value = {'code': 0, 'data': {'items': [{'id': 'different-user'}]}}
                self.assertFalse(central_auth.guild_member(SESSION, 'guild-1'))


class IdentityHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original = service.DB_PATH
        service.DB_PATH = Path(self.temporary.name) / 'recommendations.sqlite3'
        service.initialize()
        self.track = {'provider': 'netease', 'id': 'song-1', 'name': 'Song'}

    def tearDown(self):
        service.DB_PATH = self.original
        self.temporary.cleanup()

    def test_exact_kook_claim_keeps_records_and_deduplicates_count_and_withdrawal(self):
        service.toggle('guild-1', {'id': 'kook-user', 'nickname': 'Legacy'}, self.track, active=True)
        service.toggle('guild-1', {'id': 'central-user', 'nickname': 'Canonical'}, self.track, active=True)
        service.claim_identity({'id': 'central-user', 'nickname': 'Canonical'}, ['kook-user'])
        board = service.list_board('guild-1', viewer_user_id='central-user')
        self.assertEqual(board['items'][0]['recommendation_count'], 1)
        self.assertEqual(len(board['items'][0]['recommenders']), 1)
        self.assertTrue(board['items'][0]['viewer_recommended'])
        service.toggle('guild-1', {'id': 'central-user'}, self.track, active=False)
        self.assertEqual(service.list_board('guild-1')['items'], [])
        with sqlite3.connect(service.DB_PATH) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recommendations WHERE active=1').fetchone()[0], 0)

    def test_account_merge_reparents_exact_aliases_and_preserves_notes(self):
        service.toggle('guild-1', {'id': 'kook-user'}, self.track, note='first note', active=True)
        service.toggle('guild-1', {'id': 'old-central'}, self.track, note='second note', active=False)
        service.claim_identity({'id': 'old-central'}, ['kook-user'])
        conflicts = service.claim_identity({'id': 'new-central'}, ['old-central'])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(service.list_board('guild-1', 'new-central')['items'][0]['recommendation_count'], 1)
        with sqlite3.connect(service.DB_PATH) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0], 2)
            self.assertEqual(set(row[0] for row in db.execute('SELECT note FROM recommendations')), {'first note', 'second note'})
            self.assertEqual(db.execute('SELECT canonical_user_id FROM recommendation_aliases WHERE alias_id=?', ('kook-user',)).fetchone()[0], 'new-central')

    def test_claim_conflicts_abort_transaction_and_never_match_nickname(self):
        service.toggle('guild-1', {'id': 'kook-user', 'nickname': 'Same'}, self.track, active=True)
        service.claim_identity({'id': 'owner', 'nickname': 'Same'}, ['kook-user'])
        with self.assertRaises(service.IdentityConflict):
            service.claim_identity({'id': 'stranger', 'nickname': 'Same'}, ['kook-user'])
        with sqlite3.connect(service.DB_PATH) as db:
            self.assertIsNone(db.execute('SELECT * FROM users WHERE user_id=?', ('stranger',)).fetchone())
        service.claim_identity({'id': 'stranger', 'nickname': 'Same'}, [])
        self.assertFalse(service.list_board('guild-1', 'stranger')['items'][0]['viewer_recommended'])


class SocketAuthTests(unittest.TestCase):
    def test_socket_connect_and_room_events_revalidate_central_session(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='socket-fixture')
        sockets = SocketIO(app, async_mode='threading')
        routes.register_routes(app, object(), sockets)
        flask_client = app.test_client()
        with patch.object(central_auth, 'read_session', return_value=None):
            missing = sockets.test_client(app, flask_test_client=flask_client, auth={'csrf_token': 'csrf-test'})
            self.assertFalse(missing.is_connected())
        flask_client.set_cookie('localhost', 'trashbox_session', 'socket-session')
        with patch.object(sockets, 'start_background_task'):
            with patch.object(central_auth, 'read_session', return_value=SESSION):
                wrong_csrf = sockets.test_client(app, flask_test_client=flask_client, auth={'csrf_token': 'wrong'})
                self.assertFalse(wrong_csrf.is_connected())
                accepted = sockets.test_client(app, flask_test_client=flask_client, auth={'csrf_token': 'csrf-test'})
                self.assertTrue(accepted.is_connected())
                accepted.emit('join_room', {'guild_id': 'guild-1'})
            with patch.object(central_auth, 'read_session', return_value=None):
                accepted.emit('join_room', {'guild_id': 'guild-2'})
                self.assertFalse(accepted.is_connected())


if __name__ == '__main__':
    unittest.main()
