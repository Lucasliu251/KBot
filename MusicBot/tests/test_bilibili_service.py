from __future__ import annotations

import unittest
from unittest.mock import patch

import bilibili_service


class BilibiliServiceTest(unittest.TestCase):
    def test_playurl_is_primary_audio_path_and_preserves_cover(self) -> None:
        locator = bilibili_service._encode_locator({
            'bvid': 'BV1TEST123',
            'cid': 9988,
            'page': 1,
        })

        def request_json(path, params):
            if path == '/x/web-interface/view':
                return {
                    'code': 0,
                    'data': {
                        'bvid': 'BV1TEST123',
                        'title': '测试视频',
                        'pic': 'http://i1.hdslb.com/test-cover.jpg',
                        'owner': {'name': '测试UP主'},
                        'duration': 180,
                        'pages': [{'page': 1, 'cid': 9988, 'duration': 180}],
                    },
                }
            if path == '/x/player/playurl':
                return {
                    'code': 0,
                    'data': {
                        'dash': {
                            'audio': [
                                {
                                    'id': 30280,
                                    'bandwidth': 192000,
                                    'codecs': 'ec-3',
                                    'baseUrl': 'https://media.example/dolby.m4s?deadline=2000000000',
                                },
                                {
                                    'id': 30232,
                                    'bandwidth': 132000,
                                    'codecs': 'mp4a.40.2',
                                    'baseUrl': 'https://media.example/aac.m4s?deadline=2000000000',
                                },
                            ],
                        },
                    },
                }
            raise AssertionError(path)

        with (
            patch.object(bilibili_service, '_new_session'),
            patch.object(bilibili_service, '_request_json', side_effect=request_json),
            patch.object(bilibili_service.yt_dlp, 'YoutubeDL') as youtube_dl,
        ):
            result = bilibili_service._extract_audio(locator)

        self.assertEqual(result['url'], 'https://media.example/aac.m4s?deadline=2000000000')
        self.assertEqual(result['title'], '测试视频')
        self.assertEqual(result['artist'], '测试UP主')
        self.assertEqual(result['cover'], 'https://i1.hdslb.com/test-cover.jpg')
        self.assertEqual(result['duration'], 180)
        self.assertEqual(result['headers']['Referer'], 'https://www.bilibili.com/video/BV1TEST123')
        youtube_dl.assert_not_called()

    def test_search_cover_is_upgraded_to_https(self) -> None:
        result = bilibili_service._track_from_search({
            'bvid': 'BV1TEST123',
            'title': '标题',
            'author': '作者',
            'typename': '音乐',
            'duration': '03:10',
            'pic': '//i2.hdslb.com/test.jpg',
        })
        self.assertEqual(result['al']['picUrl'], 'https://i2.hdslb.com/test.jpg')
        self.assertTrue(result['playable'])


if __name__ == '__main__':
    unittest.main()
