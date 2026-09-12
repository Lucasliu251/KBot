"""Load local KOOK credentials without embedding or logging secret values."""
import configparser
from pathlib import Path


def load_ini_token(path: Path, section: str = 'kook') -> str:
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
