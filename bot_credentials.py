"""Load local KOOK credentials without embedding or logging secret values."""
import configparser
import os
from pathlib import Path


def load_role_environment() -> None:
    path = Path(os.environ.get('KBOT_ENV_FILE', Path(__file__).resolve().with_name('.env')))
    if not path.is_file():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name = name.strip().removeprefix('export ').strip()
        if not name.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(name, value)


load_role_environment()


def role_token(env_name: str, fallback: str = '') -> str:
    token = str(os.environ.get(env_name) or fallback).strip()
    if not token or token.startswith(('your_', 'replace_', 'REPLACE_')):
        raise RuntimeError(f'{env_name} 未配置')
    return token


def load_ini_token(path: Path, section: str = 'kook', env_name: str = '') -> str:
    if env_name and os.environ.get(env_name):
        return role_token(env_name)

    path = Path(path)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding='utf-8') as stream:
            parser.read_file(stream)
        token = parser.get(section, 'token', fallback='').strip()
    except (OSError, configparser.Error):
        raise RuntimeError(f'无法读取机器人配置 {path}，请复制对应 .example 文件并填写 Token') from None
    if not token or token.startswith(('your_', 'replace_', 'REPLACE_')):
        raise RuntimeError(f'{path} 的 [{section}] Token 未配置')
    return token
