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

"""Local test server."""

import base64
import contextlib
import multiprocessing as mp
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, TypeVar, cast

import bustapi
import pytest

_F = TypeVar("_F", bound=Callable[..., Any])

_BASE64 = base64.b64encode(b"test-user:test-password").decode("ascii")


@pytest.fixture(scope="package")
def test_server() -> Iterator[None]:
    """Set up the test server."""
    # https://github.com/RUSTxPY/BustAPI/blob/main/tests/test_examples.py
    with contextlib.closing(mp.Process(target=_main)) as proc:
        proc.start()
        time.sleep(2)
        yield
        proc.kill()
        proc.join()


def _auth(*requirements: bool) -> str:
    if not all(requirements):
        bustapi.abort(403)  # pyright: ignore[reportUnknownMemberType]
    return "OK"


def _get_headers() -> Mapping[str, str]:
    return bustapi.request.headers


def _main() -> None:
    app = bustapi.BustAPI()
    route = _route(app)
    turbo_route = _turbo_route(app, route)
    turbo_route("/200")(lambda: "OK")
    turbo_route("/503")(lambda: bustapi.abort(503))  # pyright: ignore[reportUnknownMemberType]
    turbo_route("/sleep")(lambda: time.sleep(2))
    for path in "/sleep1", "/sleep2":
        turbo_route(path)(_sleep)
    route("/test-basic-http")(lambda: _auth(
        _get_headers()["Authorization"] == f"Basic {_BASE64}",
    ))
    route("/test-bearer-token")(lambda: _auth(
        _get_headers()["Authorization"] == "Bearer test-bearer-token",
    ))
    route("/test-headers")(_test_headers)
    route("/test-s3-compatible/api")(lambda: _auth(
        b"X-Amz-Credential=test-access-key-id" in bustapi.request.query_string,
    ))
    app.run(load_dotenv=False)  # pyright: ignore[reportUnknownMemberType]


def _route(app: bustapi.BustAPI) -> Callable[[str], Callable[[_F], _F]]:
    return cast("Callable[[str], Any]", app.route)


def _sleep() -> str:
    time.sleep(1)
    return "OK"


def _test_headers() -> str:
    headers = _get_headers()
    return _auth(
        headers["Test-Static"] == "OK",
        headers["Test-Dynamic"] == "overwritten",
    )


def _turbo_route(app: bustapi.BustAPI, route: _F) -> _F:
    return getattr(app, "turbo_route", route)
