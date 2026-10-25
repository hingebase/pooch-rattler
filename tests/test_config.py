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

"""Test configuring Rattler and built-in downloaders."""

import hashlib
import json
import pathlib
from typing import cast

import pooch  # pyright: ignore[reportMissingTypeStubs]
import pytest
import rattler
from typing_extensions import Any, override

import pooch_rattler

_OK = hashlib.sha256(b"OK").hexdigest()
_TEMPLATE = """
authentication-override-file = %s

[s3-options.test-s3-compatible]
endpoint-url = "http://127.0.0.1:%d"
region = "eu-central-1"
addressing_style = "path"
"""


def test_regular_downloader(server_port: int, tmp_path: pathlib.Path) -> None:
    """Test configuring the regular downloader.

    This test is the same as `test_s3_compatible` in `test_auth.py`
    but the configurations are read from files instead of hard-coded.
    """
    credentials = {
        "s3://test-s3-compatible/api": {
            "S3Credentials": {
                "access_key_id": "test-access-key-id",
                "secret_access_key": "test-secret-access-key",
            },
        },
    }
    config = _temp_auth_file(credentials, server_port, tmp_path)
    with pooch_rattler.install(config):
        pooch.retrieve(  # pyright: ignore[reportUnknownMemberType]
            "s3://test-s3-compatible/api",
            known_hash=_OK,
            path=tmp_path,
        )


def test_resumable_downloader(
    server_port: int,
    tmp_path: pathlib.Path,
) -> None:
    """Test configuring the resumable downloader."""
    config = rattler.Config.from_toml("mirrors.'http://foo/'=['https://foo/']")
    with pytest.warns(UserWarning, match="mirrors"):
        pooch_rattler.ResumableDownloader.from_config(config)

    credentials = {
        "s3://test-s3-compatible/resumable": {
            "S3Credentials": {
                "access_key_id": "test-access-key-id",
                "secret_access_key": "test-secret-access-key",
            },
        },
    }
    config = _temp_auth_file(credentials, server_port, tmp_path)
    pooch_rattler.ResumableDownloader.from_config(config).retrieve(
        "s3://test-s3-compatible/resumable",
        known_hash=_OK,
        path=tmp_path,
    )


def test_built_in_downloader(server_port: int, tmp_path: pathlib.Path) -> None:
    """Test configuring built-in downloaders."""
    prog = _Progress()
    with pooch_rattler.install(headers={
        "Test-Dynamic": "overwritten",
        "Test-Static": "OK",
    }):
        pooch.retrieve(  # pyright: ignore[reportUnknownMemberType]
            f"http://127.0.0.1:{server_port}/test-headers",
            known_hash=_OK,
            path=tmp_path,
            progressbar=cast("Any", prog),
        )
    expected = [
        1024,  # https://github.com/fatiando/pooch/blob/v1.9.0/pooch/downloaders.py#L260
        "reset",
        2,
        "close",
    ]
    assert prog.total == expected[2]
    assert prog.updates == expected


class _Progress(pooch_rattler.Progress):
    def __init__(self) -> None:
        self.total = 0
        self.updates: list[int | str] = []

    @override
    def close(self) -> None:
        self.updates.append("close")

    @override
    def reset(self) -> None:
        self.updates.append("reset")

    @override
    def update(self, n: int, /) -> None:
        self.updates.append(n)


def _temp_auth_file(
    credentials: dict[str, Any],
    server_port: int,
    tmp_path: pathlib.Path,
) -> rattler.Config:
    authentication_override_file = tmp_path / "credentials.json"
    with authentication_override_file.open("x", encoding="utf-8") as f:
        json.dump(credentials, f)
    quoted = json.dumps(str(authentication_override_file))
    toml_string = _TEMPLATE % (quoted, server_port)
    return rattler.Config.from_toml(toml_string)
