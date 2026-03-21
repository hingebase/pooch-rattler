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

"""Authentication examples."""

import hashlib
import json
import pathlib
import time
from typing import Any, TypedDict

import pytest
import rattler.networking.middleware

import pooch_rattler

_OK = hashlib.sha256(b"OK").hexdigest()

pytestmark = pytest.mark.usefixtures("test_server")


def test_basic_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Test basic HTTP authentication."""
    credentials = {
        "127.0.0.1": {
            "BasicHTTP": {
                "username": "test-user",
                "password": "test-password",
            },
        },
    }
    _temp_auth_file(credentials, monkeypatch, tmp_path)
    pooch_rattler.Downloader(
        rattler.networking.AuthenticationMiddleware(),
    ).retrieve(
        "http://127.0.0.1:5000/test-basic-http",
        known_hash=_OK,
        path=tmp_path,
    )


def test_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Test authentication with Bearer token."""
    credentials = {
        "127.0.0.1": {
            "BearerToken": "test-bearer-token",
        },
    }
    _temp_auth_file(credentials, monkeypatch, tmp_path)
    pooch_rattler.Downloader(
        rattler.networking.AuthenticationMiddleware(),
    ).retrieve(
        "http://127.0.0.1:5000/test-bearer-token",
        known_hash=_OK,
        path=tmp_path,
    )


def test_gcs(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """Fetch some data from Google Cloud Storage.

    Keep in mind that public storages can be directly accessed via
    https://storage.googleapis.com/ and don't require a GCSMiddleware.
    """
    credentials = {
        "type": "authorized_user",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "refresh_token": "test-refresh-token",
        "token_uri": "http://127.0.0.1:5000/test-gcs/token",
        "quota_project_id": "test-project",
    }
    adc_path = tmp_path / "application_default_credentials.json"
    with adc_path.open("x", encoding="utf-8") as f:
        json.dump(credentials, f)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(adc_path))
    monkeypatch.delenv("GOOGLE_CLOUD_QUOTA_PROJECT", raising=False)
    pooch_rattler.Downloader(
        rattler.networking.GCSMiddleware(),
        # Redirect the request to avoid Internet access
        rattler.networking.MirrorMiddleware({
            "https://storage.googleapis.com": [
                "http://127.0.0.1:5000",
            ],
        }),
    ).retrieve(
        "gcs://test-gcs/api",
        known_hash=_OK,
        path=tmp_path,
    )


def test_oauth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Test authentication with OAuth."""
    credentials = {
        "127.0.0.1": {
            "OAuth": {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "expires_at": int(time.time()) - 300,
                "token_endpoint": "http://127.0.0.1:5000/test-oauth/token",
                "client_id": "test-client-id",
            },
        },
    }
    rattler_auth_file = _temp_auth_file(credentials, monkeypatch, tmp_path)
    pooch_rattler.Downloader(
        rattler.networking.AuthenticationMiddleware(),
    ).retrieve(
        "http://127.0.0.1:5000/test-oauth/api",
        known_hash=_OK,
        path=tmp_path,
    )
    with rattler_auth_file.open(encoding="utf-8") as f:
        refreshed: dict[str, dict[str, _OAuth]] = json.load(f)
    oauth = refreshed["127.0.0.1"]["OAuth"]
    assert oauth["access_token"] == "refreshed-access-token"  # noqa: S105
    assert oauth["refresh_token"] == "refreshed-refresh-token"  # noqa: S105
    assert oauth["expires_at"] > time.time()


def test_s3_compatible(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Fetch some data from AWS S3-compatible cloud storage.

    A non-exhaustive list of compatible storage APIs can be found at
    https://pixi.prefix.dev/latest/deployment/s3/#s3-compatible-storage
    """
    credentials = {
        "s3://test-s3-compatible/api": {
            "S3Credentials": {
                "access_key_id": "test-access-key-id",
                "secret_access_key": "test-secret-access-key",
            },
        },
    }
    _temp_auth_file(credentials, monkeypatch, tmp_path)
    pooch_rattler.Downloader(
        rattler.networking.S3Middleware({
            "test-s3-compatible": rattler.networking.middleware.S3Config(
                endpoint_url="http://127.0.0.1:5000",
                region="eu-central-1",
                force_path_style=True,
            ),
        }),
    ).retrieve(
        "s3://test-s3-compatible/api",
        known_hash=_OK,
        path=tmp_path,
    )


class _OAuth(TypedDict):
    access_token: str
    refresh_token: str
    expires_at: int


def _temp_auth_file(
    credentials: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> pathlib.Path:
    rattler_auth_file = tmp_path / "credentials.json"
    with rattler_auth_file.open("x", encoding="utf-8") as f:
        json.dump(credentials, f)
    monkeypatch.setenv("RATTLER_AUTH_FILE", str(rattler_auth_file))
    return rattler_auth_file
