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

__all__ = ["Progress", "RattlerDownloader", "choose_downloader", "install"]

import functools
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Optional, TypeVar, Union, cast

import anyio.from_thread
import anyio.lowlevel
import pooch.downloaders  # pyright: ignore[reportMissingTypeStubs]
import rattler.networking
import rattler.package_streaming
from pooch.typing import (  # pyright: ignore[reportMissingTypeStubs]
    Action,
    Downloader,
    Processor,
)
from typing_extensions import (
    Literal,
    Protocol,
    TypeIs,
    TypeVarTuple,
    Unpack,
    overload,
    override,
    runtime_checkable,
)

if TYPE_CHECKING:
    from _typeshed import StrPath

_T = TypeVar("_T")
_Ts = TypeVarTuple("_Ts")


@runtime_checkable
class Progress(Protocol):
    def close(self) -> object: ...
    def reset(self) -> object: ...
    def update(self, n: int, /) -> object: ...
    # The `total` attribute is write-only and not checkable by
    # either static type checkers or `isinstance` / `issubclass`


class RattlerDownloader(Downloader):
    _token: Optional[anyio.lowlevel.EventLoopToken]

    def __init__(
        self,
        *middlewares: Union[
            rattler.networking.AddHeadersMiddleware,
            rattler.networking.AuthenticationMiddleware,
            rattler.networking.GCSMiddleware,
            rattler.networking.MirrorMiddleware,
            rattler.networking.OciMiddleware,
            rattler.networking.RetryMiddleware,
            rattler.networking.S3Middleware,
        ],
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[int] = pooch.downloaders.DEFAULT_TIMEOUT,
    ) -> None:
        self._client = rattler.Client(
            list(middlewares) if middlewares else None,
            dict(headers) if headers else None,
            timeout,
        )
        try:
            self._token = anyio.lowlevel.current_token()
        except anyio.NoEventLoopError:
            self._token = None

    @override
    def __call__(  # ty: ignore[invalid-method-override]
        self,
        url: str,
        output_file: object,
        pooch: Optional[pooch.Pooch],
        *,
        check_only: Optional[bool] = None,
    ) -> None:
        if check_only:
            raise NotImplementedError
        if _is_path_like(output_file):
            _syncify(
                rattler.package_streaming.download_to_path,
                self._client,
                url,
                output_file,
                token=self._token,
            )
        else:
            _syncify(
                rattler.package_streaming.download_to_writer,
                self._client,
                url,
                output_file,
                token=self._token,
            )

    @overload
    def fetch(
        self,
        fname: str,
        pooch: pooch.Pooch,
        processor: None = ...,
    ) -> str: ...

    @overload
    def fetch(
        self,
        fname: str,
        pooch: pooch.Pooch,
        processor: Callable[[str, Action, Optional[pooch.Pooch]], _T],
    ) -> _T: ...

    def fetch(
        self,
        fname: str,
        pooch: pooch.Pooch,
        processor: Optional[Processor] = None,
    ) -> object:
        return pooch.fetch(
            fname,
            processor,
            downloader=self,  # pyrefly: ignore[bad-argument-type]
        )

    @overload
    def retrieve(
        self,
        url: str,
        known_hash: Optional[str] = ...,
        fname: Optional[str] = ...,
        path: "Optional[StrPath]" = ...,
        processor: None = ...,
    ) -> str: ...

    @overload
    def retrieve(
        self,
        url: str,
        known_hash: Optional[str] = ...,
        fname: Optional[str] = ...,
        path: "Optional[StrPath]" = ...,
        *,
        processor: Callable[[str, Action, Optional[pooch.Pooch]], _T],
    ) -> _T: ...

    @overload
    def retrieve(
        self,
        url: str,
        known_hash: Optional[str],
        fname: Optional[str],
        path: "Optional[StrPath]",
        processor: Callable[[str, Action, Optional[pooch.Pooch]], _T],
    ) -> _T: ...

    def retrieve(
        self,
        url: str,
        known_hash: Optional[str] = None,
        fname: Optional[str] = None,
        path: "Optional[StrPath]" = None,
        processor: Optional[Processor] = None,
    ) -> object:
        return pooch.retrieve(  # pyright: ignore[reportUnknownMemberType]
            url,
            known_hash,
            fname,
            path,
            processor,
            downloader=self,  # pyrefly: ignore[bad-argument-type]
        )

    def set_token(
        self,
        token: Optional[anyio.lowlevel.EventLoopToken] = None,
    ) -> None:
        self._token = token


@overload
def choose_downloader(url: str, progressbar: Literal[False] = ...) -> Union[
    RattlerDownloader,
    pooch.DOIDownloader,
    pooch.FTPDownloader,
    pooch.SFTPDownloader,
]: ...

@overload
def choose_downloader(url: str, progressbar: Union[bool, Progress]) -> Union[  # noqa: FBT001
    RattlerDownloader,
    pooch.DOIDownloader,
    pooch.FTPDownloader,
    pooch.HTTPDownloader,
    pooch.SFTPDownloader,
]: ...


@functools.wraps(
    pooch.downloaders.choose_downloader,  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
    assigned=["__doc__"],
    updated=(),
)
def choose_downloader(
    url: str,
    progressbar: Union[bool, Progress] = False,  # noqa: FBT001, FBT002
) -> Union[
    RattlerDownloader,
    pooch.DOIDownloader,
    pooch.FTPDownloader,
    pooch.HTTPDownloader,
    pooch.SFTPDownloader,
]:
    if not progressbar and url.startswith(
        ("gcs://", "http://", "https://", "oci://", "s3://"),
    ):
        for key, value in _middlewares.items():
            if url.startswith(key):
                # Always create a new Rattler client which reflect
                # environment changes
                return RattlerDownloader(value, _retry)
    return pooch.downloaders.choose_downloader(  # pyright: ignore[reportUnknownMemberType]
        url,
        cast("bool", progressbar),
    )


def install() -> None:
    pooch.core.choose_downloader = (  # ty: ignore[invalid-assignment]
        choose_downloader  # pyrefly: ignore[bad-assignment]
    )


def _is_path_like(output_file: object) -> TypeIs[os.PathLike[str]]:
    return not hasattr(output_file, "write")


def _syncify(
    func: Callable[[Unpack[_Ts]], Awaitable[None]],
    *args: Unpack[_Ts],
    token: Optional[anyio.lowlevel.EventLoopToken],
) -> None:
    try:
        anyio.from_thread.run(func, *args, token=token)
    except anyio.NoEventLoopError:
        anyio.run(func, *args, backend_options={"use_uvloop": True})


# The FFI objects don't touch environment variables or filesystems
# and thus can be cached safely
_middlewares = {
    "gcs://": rattler.networking.GCSMiddleware(),
    "https://": rattler.networking.AuthenticationMiddleware(),
    "oci://": rattler.networking.OciMiddleware(),
    "s3://": rattler.networking.S3Middleware(),
}
_middlewares["http://"] = _middlewares["https://"]
_retry = rattler.networking.RetryMiddleware()
