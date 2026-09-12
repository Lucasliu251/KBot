"""Persisted music transition preferences and sample-clock gain envelope."""
import json
import os
import tempfile
import threading
from pathlib import Path

PATH = Path(__file__).resolve().parent / 'data' / 'playback-settings.json'
DEFAULTS = {'enabled': True, 'seconds': 4, 'crossfade': True}
_lock = threading.Lock()

def _load():
    try:
        value = json.loads(PATH.read_text())
        if type(value['enabled']) is bool and type(value['seconds']) is int and 1 <= value['seconds'] <= 12:
            return {**DEFAULTS, **{key: value[key] for key in DEFAULTS if key in value and type(value[key]) is type(DEFAULTS[key])}}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(DEFAULTS)

_settings = _load()

def get_transition_settings():
    return dict(_settings)

def save_transition_settings(value):
    global _settings
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool or type(value.get('seconds')) is not int or not 1 <= value['seconds'] <= 12:
        raise ValueError('渐入渐出时长必须为1–12秒，开关必须为布尔值')
    if 'crossfade' in value and type(value['crossfade']) is not bool:
        raise ValueError('交叉切歌开关必须为布尔值')
    next_value = {**_settings, **{key: value[key] for key in DEFAULTS if key in value}}
    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.playback-', dir=PATH.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(next_value, stream)
            os.replace(temporary, PATH)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        _settings = next_value
    return dict(next_value)

class TrackFade:
    def __init__(self, seconds, length):
        self.seconds = max(0.0, min(float(seconds), max(0.0, length) / 2))
        self.length = length
        self.skip_start = None
        self.skip_gain = 1.0

    def gain(self, elapsed):
        if not self.seconds:
            return 1.0
        if self.skip_start is not None:
            return self.skip_gain * max(0.0, 1 - (elapsed - self.skip_start) / self.seconds)
        return max(0.0, min(1.0, elapsed / self.seconds, (self.length - elapsed) / self.seconds))

    def request_skip(self, elapsed):
        if self.skip_start is None:
            self.skip_gain = self.gain(elapsed)
            self.skip_start = elapsed
            self.seconds = min(self.seconds, max(0.0, self.length - elapsed))

    def finished(self, elapsed):
        return self.skip_start is not None and elapsed - self.skip_start >= self.seconds
