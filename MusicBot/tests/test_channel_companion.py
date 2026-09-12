import json
import unittest
from unittest.mock import patch, Mock

import channel_companion as module


class FakeAPI:
    def __init__(self):
        self.users = [{'bot': True}, {'bot': False}]
        self.calls = []
        self.error = False
        self.on_users = None

    def call(self, method, path, data):
        self.calls.append((path, data))
        if path == 'channel/user-list':
            if self.error:
                raise RuntimeError('timeout')
            if self.on_users:
                self.on_users()
            return self.users
        return {'msg_id': 'card-1'}


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.track = {'start': 100, 'ss': 30, 'extra': {
            'title': '歌曲', 'artist': '艺术家', 'album': '专辑', 'duration': 180,
            'cover': 'https://example.com/cover.png'}}
        self.playlist = {'voice_channel': 'voice-1', 'now_playing': self.track, 'play_list': []}
        self.playlists = {'guild-1': self.playlist}
        self.statuses = {'guild-1': module.kookvoice.Status.PLAYING}
        self.player = Mock()
        for name, value in [('play_list', self.playlists), ('guild_status', self.statuses),
                            ('guild_volume', {'guild-1': 0.4}), ('Player', Mock(return_value=self.player))]:
            patcher = patch.object(module.kookvoice, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.api = FakeAPI()
        self.service = module.ChannelCompanion('', 'https://trashbox.tech/Music', self.api, lambda: self.now)

    def test_no_humans_requires_two_observations(self):
        self.api.users = [{'bot': True}]
        self.service.step()
        self.player.stop.assert_not_called()
        self.now += 5
        self.service.step()
        self.player.clear.assert_called_once()
        self.player.stop.assert_called_once()

    def test_unknown_bot_flag_counts_as_human(self):
        self.api.users = [{'id': 'unknown'}]
        self.service.step()
        self.now += 30
        self.service.step()
        self.player.stop.assert_not_called()

    def test_human_returns_during_grace(self):
        self.api.users = []
        self.service.step()
        self.api.users = [{'bot': False}]
        self.now += 5
        self.service.step()
        self.player.stop.assert_not_called()
        self.assertIsNone(self.service.sessions['guild-1']['empty_since'])

    def test_idle_connection_also_exits_without_creating_card(self):
        self.playlist['now_playing'] = None
        self.statuses['guild-1'] = module.kookvoice.Status.WAIT
        self.api.users = []
        self.service.step()
        self.now += 5
        self.service.step()
        self.player.stop.assert_called_once()
        self.assertFalse(any(path.startswith('message/') for path, _ in self.api.calls))

    def test_failure_breaks_empty_confirmation(self):
        self.api.users = []
        self.service.step()
        self.now += 5
        self.api.error = True
        self.service.step()
        self.now += 15
        self.api.error = False
        self.service.step()
        self.player.stop.assert_not_called()
        self.now += 5
        self.service.step()
        self.player.stop.assert_called_once()

    def test_stale_session_never_stops_new_connection(self):
        self.api.users = []
        self.service.step()
        self.now += 5
        self.api.on_users = lambda: self.playlists.update({'guild-1': dict(self.playlist)})
        self.service.step()
        self.player.stop.assert_not_called()

    def test_card_updates_same_message_and_freezes_when_paused(self):
        self.service.step()
        self.now += 10
        self.statuses['guild-1'] = module.kookvoice.Status.PAUSE
        self.service.step()
        messages = [(path, data) for path, data in self.api.calls if path.startswith('message/')]
        self.assertEqual([path for path, _ in messages], ['message/create', 'message/update'])
        self.assertEqual(messages[0][1]['target_id'], 'voice-1')
        self.assertEqual(messages[1][1]['msg_id'], 'card-1')
        card = json.loads(messages[1][1]['content'])[0]
        section = card['modules'][0]
        self.assertIn('已暂停', section['text']['content'])
        detail = card['modules'][2]['elements'][0]['content']
        self.assertIn('0:30', detail)
        self.assertIn('3:00', detail)
        self.assertIn('40%', detail)
        self.assertEqual(section['accessory']['value'], 'https://trashbox.tech/Music/voice-1')
        self.assertEqual(section['accessory']['type'], 'button')
        self.assertEqual(len(card['modules']), 3)

    def test_disconnection_finishes_card_once(self):
        self.service.step()
        self.playlists.clear()
        self.service.step()
        self.service.step()
        updates = [data for path, data in self.api.calls if path == 'message/update']
        self.assertEqual(len(updates), 1)
        self.assertIn('已离开频道', updates[0]['content'])

    def test_malformed_member_response_does_not_stop(self):
        self.api.users = {}
        self.service.step()
        self.now += 20
        self.service.step()
        self.player.stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
