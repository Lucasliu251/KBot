import asyncio
import importlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from flask import Flask
import playback_settings as settings
import routes

voice = importlib.import_module('kookvoice.kookvoice')

class TransitionTests(unittest.TestCase):
    def test_envelope_skip_and_short_track(self):
        fade = settings.TrackFade(4, 100)
        self.assertEqual([fade.gain(t) for t in [0, 2, 4, 50, 98, 100]], [0, .5, 1, 1, .5, 0])
        fade.request_skip(2)
        self.assertEqual(fade.gain(2), .5)
        self.assertEqual(fade.gain(4), .25)
        self.assertTrue(fade.finished(6))
        short = settings.TrackFade(4, 2)
        self.assertEqual(short.gain(1), 1)
        self.assertEqual(settings.TrackFade(0, 100).gain(0), 1)

    def test_persistence_and_admin_validation(self):
        app = Flask(__name__)
        routes.register_routes(app, object())
        client = app.test_client()
        with tempfile.TemporaryDirectory() as tmp, patch.object(settings, 'PATH', Path(tmp) / 'settings.json'), patch.object(settings, '_settings', dict(settings.DEFAULTS)), patch.object(routes, 'MUSIC_SETTINGS_TOKEN', 'test-only'):
            self.assertEqual(client.post('/api/music/transitions', json={'enabled':False,'seconds':12}).status_code,403)
            headers={'X-Music-Settings-Token':'test-only'}
            self.assertEqual(client.post('/api/music/transitions',headers=headers,json={'enabled':True,'seconds':13}).status_code,400)
            response=client.post('/api/music/transitions',headers=headers,json={'enabled':False,'seconds':12})
            self.assertEqual(response.status_code,200)
            self.assertEqual(settings._load(), {'enabled':False,'seconds':12,'crossfade':True})
            self.assertEqual(client.get('/api/music/transitions').json['transition'],settings._load())

class PlaybackFadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_fades_and_manual_skip_moves_to_next_track(self):
        await self.check_playback(False)

    async def test_crossfade_overlaps_and_resumes_without_replaying_prefix(self):
        await self.check_playback(True)

    async def check_playback(self, crossfade):
        guild='fade-test'
        frame=struct.pack('<h',10000)*(voice.PCM_FRAME_BYTES//2)
        first={'file':'first','ss':0,'extra':{'duration':4 if crossfade else 2}}
        second={'file':'second','ss':0,'extra':{'duration':4 if crossfade else .2}}
        captured={'first':[],'second':[]}
        voice.play_list[guild]={'token':'unused','voice_channel':'local','now_playing':None,'play_list':[first,second]}
        voice.guild_status[guild]=voice.Status.END
        voice.guild_volume[guild]=1
        for song,count in [(first,200 if crossfade else 100),(second,200 if crossfade else 10)]:
            voice.audio_cache[voice.get_queue_item_cache_key(guild,song)]={'data':frame*count,'complete':True,'duration':count*.02,'owner_guild':guild}

        class Sink:
            def write(self,data):
                current=voice.play_list[guild]['now_playing']
                if current:
                    samples=captured[current['file']]
                    samples.append(struct.unpack_from('<h',data)[0])
                    if not crossfade and current is first and len(samples)==10:
                        voice.Player(guild).skip()
            async def drain(self): pass
        class Encoder:
            returncode=None
            stdin=Sink()
            stderr=None
            def kill(self): self.returncode=0
            async def wait(self): return self.returncode

        handler=voice.PlayHandler(guild,'unused')
        handler.requestor.join=AsyncMock(return_value={'ip':'127.0.0.1','port':1,'rtcp_port':2,'bitrate':64000})
        handler.requestor.leave=AsyncMock()
        try:
            with patch.object(voice.asyncio,'create_subprocess_shell',AsyncMock(return_value=Encoder())), patch.object(voice,'schedule_next_preload'), patch.object(voice,'get_transition_settings',return_value={'enabled':True,'seconds':1,'crossfade':crossfade}), patch.object(voice,'idle_disconnect_seconds',0):
                await asyncio.wait_for(handler.push(),12)
            if crossfade:
                self.assertEqual(len(captured['first']),200)
                self.assertEqual(len(captured['second']),175)
                self.assertAlmostEqual(captured['second'][0],5000,delta=2)
                self.assertAlmostEqual(captured['first'][-1],5000,delta=2)
                self.assertNotIn('_crossfade_bytes', second)
                return
            self.assertEqual(captured['first'][0],0)
            self.assertGreater(captured['first'][9],0)
            self.assertLess(captured['first'][-1],captured['first'][9])
            self.assertLess(len(captured['first']),100)
            self.assertEqual(captured['second'][0],0)
            self.assertGreater(max(captured['second']),captured['second'][-1])
            self.assertEqual(len(voice.play_history[guild]),2)
        finally:
            for mapping in [voice.play_list,voice.guild_status,voice.guild_volume,voice.play_history,voice.playlist_handle_status,voice.guild_transport_metrics,voice.song_play_count]: mapping.pop(guild,None)
            for key in list(voice.audio_cache):
                if voice.audio_cache[key].get('owner_guild')==guild: del voice.audio_cache[key]
