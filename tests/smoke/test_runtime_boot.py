from __future__ import annotations

import os
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from tests.integration.helpers import valid_env


def test_uvicorn_boots_with_src_pythonpath() -> None:
    port = reserve_port()
    env = os.environ.copy()
    env.update({key: str(value) for key, value in valid_env().items()})
    env["PYTHONPATH"] = "src"

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        wait_for_healthcheck(process=process, port=port, timeout_seconds=8)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_healthcheck(
    *, process: subprocess.Popen[bytes], port: int, timeout_seconds: int
) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://127.0.0.1:{port}/health/live"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"uvicorn exited before becoming healthy with code {process.returncode}")
        try:
            with urlopen(url, timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    pytest.fail("uvicorn did not become healthy before timeout")
