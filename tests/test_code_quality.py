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

"""Type checking and linting."""

import contextlib
import os
import runpy
import subprocess  # noqa: S404
import sys
from collections.abc import Generator
from typing import NoReturn

import pytest

if sys.platform == "win32":
    from contextlib import (
        nullcontext as _astral_context,  # pyright: ignore[reportAssignmentType]
    )
else:
    @contextlib.contextmanager
    def _astral_context(monkeypatch: pytest.MonkeyPatch) -> Generator[object]:
        def execvp(executable: str, args: list[str]) -> NoReturn:
            nonlocal patched
            patched = True
            sys.exit(subprocess.call(args, executable=executable))  # noqa: S603
        patched = False
        monkeypatch.setattr(os, "execvp", execvp)
        try:
            yield
        finally:
            assert patched


def test_basedpyright(monkeypatch: pytest.MonkeyPatch) -> None:
    """Type checking with basedpyright."""
    argv = ["basedpyright", "--pythonpath", sys.executable]
    monkeypatch.setattr(sys, "argv", argv)
    _run_module("basedpyright")


def test_pyrefly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Type checking with pyrefly."""
    monkeypatch.setattr(sys, "argv", ["pyrefly", "check"])
    _run_module("pyrefly")


@pytest.mark.skipif(
    os.getenv("PIXI_PROJECT_NAME") == "pooch-rattler"
        and os.getenv("PIXI_ENVIRONMENT_NAME", "default") != "default",
    reason="It's unnecessary to run Ruff for each Python environment",
)
def test_ruff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Linting with Ruff."""
    monkeypatch.setattr(sys, "argv", ["ruff", "check"])
    with _astral_context(monkeypatch):
        _run_module("ruff")


def test_ty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Type checking with ty."""
    argv = ["ty", "check", "--python", sys.executable]
    monkeypatch.setattr(sys, "argv", argv)
    with _astral_context(monkeypatch):
        _run_module("ty")


def _run_module(module_name: str) -> None:
    try:
        runpy.run_module(module_name, run_name="__main__")
    except SystemExit as e:
        code = e.code
    else:
        return
    assert code == 0
