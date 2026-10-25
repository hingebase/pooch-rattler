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

__all__ = ["Progress", "RattlerDownloader", "ResumableDownloader", "install"]

import contextlib
import functools
import os
import pathlib
import types
import warnings
from collections.abc import Callable, Coroutine, Generator, Mapping
from typing import TYPE_CHECKING, BinaryIO, TypeVar, cast

import anyio.from_thread
import anyio.lowlevel
import pooch.downloaders  # pyright: ignore[reportMissingTypeStubs]
import rattler.networking.middleware
import rattler.package_streaming
from pooch.typing import Action, Downloader, Processor  # pyright: ignore[reportMissingTypeStubs]
from requests.structures import CaseInsensitiveDict
from typing_extensions import (
    Any,
    Protocol,
    Self,
    TypeIs,
    TypeVarTuple,
    Unpack,
    overload,
    override,
    runtime_checkable,
)

if TYPE_CHECKING:
    from _typeshed import StrPath

_BuiltInDownloader = (
    pooch.DOIDownloader
    | pooch.FTPDownloader
    | pooch.HTTPDownloader
    | pooch.SFTPDownloader
)
_T = TypeVar("_T")
_Ts = TypeVarTuple("_Ts")

_DEFAULT_USER_AGENT = f"py-rattler/{rattler.__version__}"


@runtime_checkable
class Progress(Protocol):
    def close(self) -> object: ...
    def reset(self) -> object: ...
    def update(self, n: int, /) -> object: ...
    # The `total` attribute is write-only and not checkable by
    # either static type checkers or `isinstance` / `issubclass`


class _BaseDownloader(Downloader):
    _token: anyio.lowlevel.EventLoopToken | None

    def __init__(self) -> None:
        try:
            self._token = anyio.lowlevel.current_token()
        except anyio.NoEventLoopError:
            self._token = None

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
        processor: Callable[[str, Action, pooch.Pooch | None], _T],
    ) -> _T: ...

    def fetch(
        self,
        fname: str,
        pooch: pooch.Pooch,
        processor: Processor | None = None,
    ) -> object:
        return pooch.fetch(fname, processor, downloader=self)

    @overload
    def retrieve(
        self,
        url: str,
        known_hash: str | None = ...,
        fname: str | None = ...,
        path: "StrPath | None" = ...,
        processor: None = ...,
    ) -> str: ...

    @overload
    def retrieve(
        self,
        url: str,
        known_hash: str | None = ...,
        fname: str | None = ...,
        path: "StrPath | None" = ...,
        *,
        processor: Callable[[str, Action, pooch.Pooch | None], _T],
    ) -> _T: ...

    @overload
    def retrieve(
        self,
        url: str,
        known_hash: str | None,
        fname: str | None,
        path: "StrPath | None",
        processor: Callable[[str, Action, pooch.Pooch | None], _T],
    ) -> _T: ...

    def retrieve(
        self,
        url: str,
        known_hash: str | None = None,
        fname: str | None = None,
        path: "StrPath | None" = None,
        processor: Processor | None = None,
    ) -> object:
        return pooch.retrieve(  # pyright: ignore[reportUnknownMemberType]
            url,
            known_hash,
            fname,
            path,
            processor,
            downloader=self,
        )

    def set_token(
        self,
        token: anyio.lowlevel.EventLoopToken | None = None,
    ) -> None:
        self._token = token


class RattlerDownloader(_BaseDownloader):
    @override
    def __init__(
        self,
        *middlewares: rattler.networking.AddHeadersMiddleware
            | rattler.networking.AuthenticationMiddleware
            | rattler.networking.GCSMiddleware
            | rattler.networking.MirrorMiddleware
            | rattler.networking.OciMiddleware
            | rattler.networking.RetryMiddleware
            | rattler.networking.S3Middleware,
        headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
        timeout: int | None = None,
    ) -> None:
        super().__init__()
        headers, user_agent = _ensure_ua(headers, user_agent)
        self._client = rattler.Client(
            list(middlewares) if middlewares else None,
            headers,
            user_agent,
            timeout,
        )

    @classmethod
    def from_config(
        cls,
        config: rattler.Config,
        max_retries: int = 3,
        headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
        timeout: int | None = None,
    ) -> Self:
        self = cls.__new__(cls)
        super(RattlerDownloader, self).__init__()
        headers, user_agent = _ensure_ua(headers, user_agent)
        self._client = rattler.Client.from_config(
            config, max_retries, headers, user_agent, timeout)
        return self

    @override
    def __call__(  # pyrefly: ignore[bad-override-param-name]  # ty: ignore[invalid-method-override]
        self,
        url: str,
        output_file: object,
        pooch: pooch.Pooch | None,
        *,
        check_only: bool | None = None,
    ) -> None:
        if check_only:
            # https://github.com/fatiando/pooch/blob/v1.9.0/pooch/core.py#L749
            raise TypeError
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


class ResumableDownloader(_BaseDownloader):
    _rattler_auth_file: str | None

    @override
    def __init__(
        self,
        *middlewares: rattler.networking.AddHeadersMiddleware
            | rattler.networking.AuthenticationMiddleware
            | rattler.networking.GCSMiddleware
            | rattler.networking.OciMiddleware
            | rattler.networking.S3Middleware,
        max_retries: int = 3,
        headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
        timeout: int | None = None,
    ) -> None:
        super().__init__()
        self._middlewares = middlewares
        self._max_retries = max(max_retries, 0)
        self._headers = _ensure_ua(headers, user_agent)
        self._timeout = timeout
        self._rattler_auth_file = None

    @classmethod
    def from_config(
        cls,
        config: rattler.Config,
        max_retries: int = 3,
        headers: Mapping[str, str] | None = None,
        user_agent: str | None = None,
        timeout: int | None = None,
    ) -> Self:
        if config.mirrors:
            warnings.warn(
                "Using mirrors with resumable downloaders is unsupported. "
                "Ignoring the mirrors, and if you have trouble downloading a "
                "file, consider constructing the mirrored URL yourself or"
                "switching to the regular downloader.",
                stacklevel=2,
            )
        self = cls(
            _middlewares["http://", "https://"],
            _middlewares["oci://"],
            _middlewares["gcs://"],
            rattler.networking.S3Middleware({
                k: rattler.networking.middleware.S3Config(
                    v.get("endpoint-url"),
                    v.get("region"),
                    v.get("addressing-style", "virtual-host"),
                )
                for k, v in config.s3_options.items()
            }),
            max_retries=max_retries,
            headers=headers,
            user_agent=user_agent,
            timeout=timeout,
        )
        if authentication_override_file := config.authentication_override_file:
            self._rattler_auth_file = str(authentication_override_file)
        return self

    @override
    def __call__(  # pyrefly: ignore[bad-override-param-name]  # ty: ignore[invalid-method-override]
        self,
        url: str,
        output_file: object,
        pooch: pooch.Pooch | None,
        *,
        check_only: bool | None = None,
    ) -> None:
        if check_only:
            raise TypeError
        last_exc = None
        with _open_output_file(output_file) as f:
            headers, user_agent = self._headers
            with self._authentication_override():
                client = rattler.Client(
                    [*self._middlewares, _add_range_header(f)],
                    headers,
                    user_agent,
                    self._timeout,
                )
            for _ in range(self._max_retries + 1):
                try:
                    _syncify(
                        rattler.package_streaming.download_to_writer,
                        client,
                        url,
                        f,
                        token=self._token,
                    )
                except BaseException as e:  # ruff: ignore[try-except-in-loop]
                    e.__context__ = last_exc
                    if not isinstance(e, Exception):
                        raise
                    last_exc = e
                else:
                    return
        if last_exc:
            raise last_exc
        message = "Unreachable"
        raise AssertionError(message)

    @contextlib.contextmanager
    def _authentication_override(self) -> Generator[None]:
        if rattler_auth_file := self._rattler_auth_file:
            backup = os.getenv("RATTLER_AUTH_FILE")
            os.environ["RATTLER_AUTH_FILE"] = rattler_auth_file
            try:
                yield
            finally:
                if backup:
                    os.environ["RATTLER_AUTH_FILE"] = backup
                else:
                    del os.environ["RATTLER_AUTH_FILE"]
        else:
            yield


class _Uninstall(contextlib.AbstractContextManager[None, None]):
    @override
    def __enter__(self) -> None:
        pass

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
        /,
    ) -> None:
        pooch.core.choose_downloader = pooch.downloaders.choose_downloader  # pyright: ignore[reportUnknownMemberType]


# Neither `py-rattler` nor `requests` supports sending multiple header
# lines with the same name. Input headers are collapsed through
# `CaseInsensitiveDict` in both cases. Use comma-separated header
# values instead.
def install(
    config: rattler.Config | None = None,
    max_retries: int = 3,
    headers: Mapping[str, str] | None = None,
    user_agent: str | None = None,
    timeout: int | None = None,
) -> _Uninstall:
    @functools.wraps(pooch.downloaders.choose_downloader, updated=())  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
    def wrapper(
        url: str,
        progressbar: bool | Progress = False,  # ruff: ignore[boolean-default-value-positional-argument, boolean-type-hint-positional-argument]
    ) -> RattlerDownloader | _BuiltInDownloader:
        if not progressbar and url.startswith(
            ("gcs://", "http://", "https://", "oci://", "s3://"),
        ):
            if config:
                return RattlerDownloader.from_config(
                    config, max_retries, headers, user_agent, timeout)
            for key, value in _middlewares.items():
                if url.startswith(key):
                    return RattlerDownloader(
                        value,
                        rattler.networking.RetryMiddleware(max_retries),
                        headers=headers,
                        user_agent=user_agent,
                        timeout=timeout,
                    )
        downloader = pooch.downloaders.choose_downloader(  # pyright: ignore[reportUnknownMemberType]
            url,
            cast("bool", progressbar),
        )
        _customize(downloader, headers, user_agent, timeout)
        return downloader  # ty: ignore[unsound-return-statement]
    pooch.core.choose_downloader = wrapper  # ty: ignore[invalid-assignment]
    return _Uninstall()


def _add_range_header(f: BinaryIO) -> rattler.networking.AddHeadersMiddleware:
    def callback(host: str, path: str) -> dict[str, str] | None:
        if partial := f.tell() - initial:
            if partial > 0:
                return {"Range": f"bytes={partial}-"}
            del host, path
            message = "File corrupted"
            raise AssertionError(message)
        return None
    initial = f.tell()
    return rattler.networking.AddHeadersMiddleware(callback)


@functools.singledispatch
def _customize(
    downloader: object,
    headers: Mapping[str, str] | None,
    user_agent: str | None,
    timeout: int | None,
) -> None:
    raise NotImplementedError


@_customize.register
def _(
    downloader: pooch.DOIDownloader,
    headers: Mapping[str, str] | None,
    user_agent: str | None,
    timeout: int | None,
) -> None:
    if headers:
        downloader.headers = merged = CaseInsensitiveDict(downloader.headers)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        merged.update(headers)
        if user_agent:
            merged["User-Agent"] = user_agent
    elif user_agent:
        downloader.headers = {"User-Agent": user_agent}
    if timeout:
        downloader.timeout = timeout


@_customize.register(pooch.FTPDownloader)
@_customize.register(pooch.SFTPDownloader)
def _(
    downloader: pooch.FTPDownloader | pooch.SFTPDownloader,
    headers: Mapping[str, str] | None,
    user_agent: str | None,
    timeout: int | None,
) -> None:
    del headers, user_agent
    if timeout:
        downloader.timeout = timeout


@_customize.register
def _(
    downloader: pooch.HTTPDownloader,
    headers: Mapping[str, str] | None,
    user_agent: str | None,
    timeout: int | None,
) -> None:
    if headers:
        downloader.kwargs["headers"] = merged = CaseInsensitiveDict(headers)  # pyright: ignore[reportUnknownMemberType]
        if user_agent:
            merged["User-Agent"] = user_agent
    elif user_agent:
        downloader.kwargs["headers"] = {"User-Agent": user_agent}  # pyright: ignore[reportUnknownMemberType]
    if timeout:
        downloader.kwargs["timeout"] = timeout  # pyright: ignore[reportUnknownMemberType]


# https://github.com/conda/rattler/blob/py-rattler-v0.28.0/py-rattler/src/networking/client.rs#L47-L48
def _ensure_ua(
    headers: Mapping[str, str] | None,
    user_agent: str | None,
) -> tuple[dict[str, str] | None, str | None]:
    if not headers:
        return None, user_agent
    d = CaseInsensitiveDict(headers)
    if user_agent:
        d.pop("User-Agent", None)
    else:
        user_agent = d.pop("User-Agent", _DEFAULT_USER_AGENT)
    return dict(d), user_agent


def _is_path_like(output_file: object) -> TypeIs[os.PathLike[str]]:
    return not hasattr(output_file, "write")


def _open_output_file(
    output_file: object,
) -> contextlib.AbstractContextManager[BinaryIO]:
    if _is_path_like(output_file):
        return pathlib.Path(output_file).open("w+b")
    return contextlib.nullcontext(cast("BinaryIO", output_file))


def _syncify(
    func: Callable[[Unpack[_Ts]], Coroutine[Any, Any, None]],
    *args: Unpack[_Ts],
    token: anyio.lowlevel.EventLoopToken | None,
) -> None:
    try:
        anyio.from_thread.run(func, *args, token=token)
    except anyio.NoEventLoopError:
        anyio.run(func, *args, backend_options={"use_uvloop": True})


# The FFI objects don't touch environment variables or filesystems
# and thus can be cached safely
_middlewares = {
    "gcs://": rattler.networking.GCSMiddleware(),
    ("http://", "https://"): rattler.networking.AuthenticationMiddleware(),
    "oci://": rattler.networking.OciMiddleware(),
    "s3://": rattler.networking.S3Middleware(),
}
_retry = rattler.networking.RetryMiddleware()
