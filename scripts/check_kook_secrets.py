"""Check tracked worktree files (or --staged) without printing credential values."""
import argparse
import base64
import re
import subprocess
from pathlib import Path

TOKEN_PATTERN = re.compile(rb'\b1/([A-Za-z0-9+=]+)/[A-Za-z0-9+/=]{16,}')
ROOT = Path(__file__).resolve().parents[1]


def token_lines(content):
    for match in TOKEN_PATTERN.finditer(content):
        try:
            identity = base64.b64decode(match[1], validate=True)
        except ValueError:
            continue
        if identity.isdigit():
            yield content[:match.start()].count(b'\n') + 1


def check(staged=False):
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    findings = []
    for raw in files:
        if not raw:
            continue
        path = raw.decode('utf-8')
        if staged:
            content = subprocess.check_output(['git', 'show', ':' + path], cwd=ROOT)
        else:
            file = ROOT / path
            if not file.is_file() or file.is_symlink():
                continue
            content = file.read_bytes()
        findings.extend((path, line) for line in token_lines(content))
    for path, line in findings:
        print(f'{path}:{line}: 检测到 KOOK Token，请移至 Git 忽略的本地配置')
    print('KOOK 密钥检查：' + ('未通过' if findings else '通过'))
    return bool(findings)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--staged', action='store_true', help='检查提交索引，适合提交前使用')
    raise SystemExit(check(parser.parse_args().staged))
