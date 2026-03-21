# Copyright 2026 hingebase

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:

# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.

# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the
#    distribution.

# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Basic examples."""

import asyncio
import hashlib
import math
import pathlib
import sys
import time
from typing import Optional

import pytest
import rattler.networking
import tqdm

import pooch_rattler

_OK = hashlib.sha256(b"OK").hexdigest()

pytestmark = pytest.mark.usefixtures("test_server")


def test_headers(tmp_path: pathlib.Path) -> None:
    """Test sending HTTP headers."""
    pooch_rattler.Downloader(
        rattler.networking.AddHeadersMiddleware(_add_headers),
        headers={
            "Test-Static": "OK",
            "Test-Dynamic": "static",
        },
    ).retrieve(
        "http://127.0.0.1:5000/test-headers",
        known_hash=_OK,
        path=tmp_path,
    )


def test_parallel(tmp_path: pathlib.Path) -> None:
    """Download tasks should run concurrently."""
    asyncio.run(_test_parallel_main(tmp_path))


def test_progress() -> None:
    """Test the progress bar protocol."""
    assert issubclass(tqdm.tqdm, pooch_rattler.Progress)
    assert issubclass(_MinimalProgressDisplay, pooch_rattler.Progress)


def test_retry_with_different_mirrors(tmp_path: pathlib.Path) -> None:
    """The mirror URLs should be accessed in sequence."""
    pooch_rattler.Downloader(
        rattler.networking.RetryMiddleware(max_retries=2),
        rattler.networking.MirrorMiddleware({
            "http://127.0.0.1:5000/test-retry": [
                "http://127.0.0.1:5000/503/",
                "http://127.0.0.1:5000/sleep/",
                "http://127.0.0.1:5000/200/",
            ],
        }),
        rattler.networking.AddHeadersMiddleware(_EnsureRequestPath()),
        timeout=1,
    ).retrieve(
        "http://127.0.0.1:5000/test-retry",
        known_hash=_OK,
        path=tmp_path,
    )


class _EnsureRequestPath:
    def __init__(self) -> None:
        self._path = "/503/"

    def __call__(self, host: str, path: str) -> None:
        assert path == self._path
        if path == "/503/":
            self._path = "/sleep/"
        elif path == "/sleep/":
            self._path = "/200/"
        elif path == "/200/":
            del host, self._path


# Taken from https://www.fatiando.org/pooch/latest/progressbars.html#using-custom-progress-bars
# with annotations added
class _MinimalProgressDisplay:
    def __init__(self, total: Optional[int]) -> None:  # noqa: FA100
        self.count = 0
        self.total = total

    def __repr__(self) -> str:
        return str(self.count) + "/" + str(self.total)

    def render(self) -> None:
        print(f"\r{self}", file=sys.stderr, end="")  # noqa: T201

    def update(self, i: int) -> None:
        self.count = i
        self.render()

    def reset(self) -> None:
        self.count = 0

    def close(self) -> None:  # noqa: PLR6301
        print("", file=sys.stderr)  # noqa: FURB105, T201


def _add_headers(host: str, path: str) -> dict[str, str]:
    del host, path
    return {"Test-Dynamic": "overwritten"}


async def _test_parallel_main(path: pathlib.Path) -> None:
    downloader = pooch_rattler.Downloader()
    coro1 = asyncio.to_thread(
        downloader.retrieve,
        "http://127.0.0.1:5000/sleep1",
        known_hash=_OK,
        path=path,
    )
    coro2 = asyncio.to_thread(
        downloader.retrieve,
        "http://127.0.0.1:5000/sleep2",
        known_hash=_OK,
        path=path,
    )
    # According to the documentation, `asyncio.wait_for` may exceed its
    # timeout. Timing the tasks manually.
    tic = time.monotonic()
    await asyncio.gather(coro1, coro2)
    toc = time.monotonic()
    eps = toc - math.nextafter(toc, -math.inf)
    assert 1-eps < toc-tic < 2-eps  # noqa: E226
