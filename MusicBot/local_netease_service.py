"""管理 MusicBot 内置的 api-enhanced Node.js 子进程。"""

from __future__ import annotations

import atexit
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from config import (
    LOCAL_NETEASE_API_BASE,
    MUSIC_API_BASE,
    NETEASE_API_HOST,
    NETEASE_API_MANAGED,
    NETEASE_API_PORT,
)


logger = logging.getLogger(__name__)
MODULE_ROOT = Path(__file__).resolve().parent
SERVER_SCRIPT = MODULE_ROOT / "netease_api_server.cjs"
PACKAGE_JSON = (
    MODULE_ROOT
    / "node_modules"
    / "@neteasecloudmusicapienhanced"
    / "api"
    / "package.json"
)


class LocalNeteaseService:
    """启动、探活并在 MusicBot 退出时回收本地 Node 服务。"""

    def __init__(self) -> None:
        self.host = NETEASE_API_HOST
        self.port = NETEASE_API_PORT
        self.base_url = LOCAL_NETEASE_API_BASE
        self.enabled = NETEASE_API_MANAGED and MUSIC_API_BASE == LOCAL_NETEASE_API_BASE
        self.start_timeout = max(5.0, float(os.environ.get("NETEASE_API_START_TIMEOUT", "30")))
        self.process: subprocess.Popen[str] | None = None
        self._stopping = threading.Event()
        self._owns_process = False
        self._monitor_thread: threading.Thread | None = None

    def _health_version(self, timeout: float = 1.0) -> str:
        try:
            with urlopen(f"{self.base_url}/inner/version", timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if int(payload.get("code", 0)) != 200:
                return ""
            return str((payload.get("data") or {}).get("version") or "")
        except (OSError, ValueError, URLError):
            return ""

    def _installed_version(self) -> str:
        try:
            payload = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
            return str(payload.get("version") or "")
        except (OSError, ValueError):
            return ""

    def _verify_version(self, running_version: str) -> None:
        installed_version = self._installed_version()
        if installed_version and running_version != installed_version:
            raise RuntimeError(
                f"8005 已被不兼容的网易云 API v{running_version} 占用，"
                f"当前项目需要 v{installed_version}"
            )

    def _sanitized_environment(self) -> dict[str, str]:
        child_env = os.environ.copy()
        # sidecar 通过每个本机 HTTP 请求接收所需 Cookie，不需要继承其它机器人密钥。
        for secret_name in (
            "BOT_TOKEN",
            "MUSIC_BOT_TOKEN",
            "MUSIC_SETTINGS_TOKEN",
            "NETEASE_COOKIE",
            "QQ_MUSIC_CREDENTIAL_JSON",
            "SECRET_KEY",
        ):
            child_env.pop(secret_name, None)
        child_env["NETEASE_API_HOST"] = self.host
        child_env["NETEASE_API_PORT"] = str(self.port)
        child_env["NODE_ENV"] = "production"
        child_env["DOTENV_CONFIG_QUIET"] = "true"
        child_env["NO_COLOR"] = "1"
        child_env["FORCE_COLOR"] = "0"
        return child_env

    def _forward_output(self, process: subprocess.Popen[str]) -> None:
        if not process.stdout:
            return
        for line in process.stdout:
            message = line.rstrip()
            if message:
                logger.info("[netease-api] %s", message)

    def _spawn(self) -> None:
        node_binary = shutil.which("node")
        if not node_binary:
            raise RuntimeError("找不到 Node.js，无法启动内置网易云 API")
        if not SERVER_SCRIPT.is_file():
            raise RuntimeError(f"缺少内置网易云启动脚本: {SERVER_SCRIPT}")
        if not PACKAGE_JSON.is_file():
            raise RuntimeError("缺少 api-enhanced 依赖，请在 MusicBot 目录执行 npm install")

        self.process = subprocess.Popen(
            [node_binary, str(SERVER_SCRIPT)],
            cwd=str(MODULE_ROOT),
            env=self._sanitized_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._owns_process = True
        threading.Thread(
            target=self._forward_output,
            args=(self.process,),
            name="netease-api-log",
            daemon=True,
        ).start()

    def _wait_until_ready(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(f"内置网易云 API 提前退出，code={self.process.returncode}")
            version = self._health_version()
            if version:
                return version
            time.sleep(0.2)
        raise RuntimeError(f"等待内置网易云 API 就绪超时: {self.base_url}")

    def _monitor(self) -> None:
        """子进程意外退出时在后台渐进重启，不拖垮 MusicBot 主服务。"""
        restart_attempt = 0
        while not self._stopping.is_set():
            process = self.process
            if not process:
                return
            return_code = process.wait()
            if self._stopping.is_set():
                return

            logger.error("本地网易云 API 意外退出，code=%s", return_code)
            while not self._stopping.is_set():
                restart_attempt += 1
                delay = min(30.0, float(2 ** min(restart_attempt - 1, 5)))
                if self._stopping.wait(delay):
                    return
                try:
                    self._spawn()
                    version = self._wait_until_ready(min(self.start_timeout, 20.0))
                    self._verify_version(version)
                    logger.info(
                        "本地网易云 API v%s 已自动恢复（第 %s 次尝试）",
                        version,
                        restart_attempt,
                    )
                    restart_attempt = 0
                    break
                except Exception as exc:
                    logger.error("本地网易云 API 自动恢复失败: %s", exc)
                    failed_process = self.process
                    if failed_process and failed_process.poll() is None:
                        failed_process.terminate()
                        try:
                            failed_process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            failed_process.kill()

    def start(self) -> None:
        if not self.enabled:
            logger.info("内置网易云 API 管理已关闭，使用配置的外部地址")
            return
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("受管网易云 API 只能监听回环地址，拒绝暴露到公网")

        existing_version = self._health_version()
        if existing_version:
            self._verify_version(existing_version)
            logger.info("复用已运行的本地网易云 API v%s: %s", existing_version, self.base_url)
            return

        self._spawn()
        try:
            version = self._wait_until_ready(self.start_timeout)
            self._verify_version(version)
        except Exception:
            self.stop()
            raise
        logger.info("本地网易云 API v%s 已就绪: %s", version, self.base_url)
        self._monitor_thread = threading.Thread(
            target=self._monitor,
            name="netease-api-monitor",
            daemon=True,
        )
        self._monitor_thread.start()
        atexit.register(self.stop)

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        process = self.process
        if not self._owns_process or not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            process.kill()
            try:
                process.wait(timeout=1)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                pass
        logger.info("本地网易云 API 已停止")


local_netease_service = LocalNeteaseService()
