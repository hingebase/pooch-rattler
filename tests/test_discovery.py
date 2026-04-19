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

"""Event loop discovery examples."""

import asyncio
import inspect

import anyio.to_thread
import pytest
import rattler.networking
import trio
from anyio.lowlevel import current_token

import pooch_rattler


def test_bare_asyncio() -> None:
    """Test event loop discovery in bare asyncio.

    Downloaders MUST be created inside the running event loop.
    """
    asyncio.run(_test_bare_asyncio())


def test_bare_trio() -> None:
    """Test event loop discovery in bare trio.

    Downloaders MUST be created inside the running event loop.
    """
    trio.run(_test_bare_trio)


def test_anyio_asyncio() -> None:
    """Test event loop discovery in anyio with asyncio backend.

    Downloaders MAY be created outside the running event loop.
    """
    downloader = pooch_rattler.Downloader(_middleware)
    anyio.run(_test_anyio_asyncio, downloader, backend="asyncio")


def test_anyio_trio() -> None:
    """Test event loop discovery in anyio with trio backend.

    Downloaders MAY be created outside the running event loop.
    """
    downloader = pooch_rattler.Downloader(_middleware)
    anyio.run(_test_anyio_trio, downloader, backend="trio")


class _InternalError(Exception):
    pass


@rattler.networking.AddHeadersMiddleware
def _middleware(host: str, path: str) -> None:
    del host, path
    # This thread is managed by pyo3 rather than (any|async|tr)io
    # No way to retrieve the running event loop directly
    raise _InternalError  # Will be replaced with a RuntimeError by pyo3


async def _test_anyio_asyncio(downloader: pooch_rattler.Downloader) -> None:
    try:
        await anyio.to_thread.run_sync(  # pyrefly: ignore[bad-argument-type]
            downloader.retrieve,
            "https://example.com/index.html",
        )
    except RuntimeError as e:
        if tb := e.__traceback__:
            for info in reversed(inspect.getinnerframes(tb, context=0)):
                if task := info.frame.f_locals.get("task"):
                    assert isinstance(task, asyncio.Task)
                    assert task.get_loop() is current_token().native_token
                    return
    pytest.fail("asyncio.Task not found")  # ty: ignore[invalid-argument-type]


async def _test_anyio_trio(downloader: pooch_rattler.Downloader) -> None:
    try:
        await anyio.to_thread.run_sync(  # pyrefly: ignore[bad-argument-type]
            downloader.retrieve,
            "https://example.com/index.html",
        )
    except RuntimeError as e:
        if tb := e.__traceback__:
            for info in reversed(inspect.getinnerframes(tb, context=0)):
                if token := info.frame.f_locals.get("trio_token"):
                    assert token is current_token().native_token
                    return
    pytest.fail("TrioToken not found")  # ty: ignore[invalid-argument-type]


async def _test_bare_asyncio() -> None:
    try:
        await asyncio.to_thread(
            pooch_rattler.Downloader(_middleware).retrieve,
            "https://example.com/index.html",
        )
    except RuntimeError as e:
        if tb := e.__traceback__:
            for info in reversed(inspect.getinnerframes(tb, context=0)):
                if loop := info.frame.f_locals.get("loop"):
                    assert loop is asyncio.get_running_loop()
                    return
    pytest.fail("asyncio loop not found")  # ty: ignore[invalid-argument-type]


async def _test_bare_trio() -> None:
    try:
        await trio.to_thread.run_sync(  # pyrefly: ignore[bad-argument-type]
            pooch_rattler.Downloader(_middleware).retrieve,
            "https://example.com/index.html",
        )
    except RuntimeError as e:
        if tb := e.__traceback__:
            for info in reversed(inspect.getinnerframes(tb, context=0)):
                if token := info.frame.f_locals.get("trio_token"):
                    assert token is trio.lowlevel.current_trio_token()
                    return
    pytest.fail("TrioToken not found")  # ty: ignore[invalid-argument-type]
