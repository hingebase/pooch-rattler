# pooch-rattler

[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/hingebase/pooch-rattler/publish-pypi.yml?label=ci&logo=github)](https://github.com/hingebase/pooch-rattler/actions)
[![PyPI - Version](https://img.shields.io/pypi/v/pooch-rattler)](https://pypi.org/project/pooch-rattler)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/pooch-rattler)
![BSD-3-Clause License](https://img.shields.io/pypi/l/pooch-rattler)  
![basedpyright](https://img.shields.io/endpoint?url=https://docs.basedpyright.com/latest/badge.json)
![pyrefly](https://img.shields.io/endpoint?url=https://pyrefly.org/badge.json)
![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)
![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)
![Pixi](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prefix-dev/pixi/main/assets/badge/v0.json)

[Pooch downloader][1] powered by [Rattler][2].
## Features
- Native Rust performance
- Work with `asyncio`
- Drop-in replacement of the global default Pooch downloader
- [Reqwest middlewares][3] which bring the missing [GCS][4], [S3][5] and
  [retry][6] support in Pooch

## Get started
``` py
import asyncio

import pooch
import pooch_rattler

# Synchronous download
pooch_rattler.install()  # Register global default
downloaded_file = pooch.retrieve("https://example.com/index.html")

# Asynchronous download
async def async_download():
    # Explicit initialization is recommended, in which case the download
    # task is executed within the main thread and the running event loop
    downloader = pooch_rattler.Downloader()
    # We still need a worker thread to look for existing cache,
    # validate checksums and decompress downloaded files
    return await asyncio.to_thread(
        downloader.retrieve, "https://example.com/index.html")

cached_file = asyncio.run(async_download())
assert cached_file == downloaded_file
```

More examples can be found in the [unit tests][7].

[1]: https://www.fatiando.org/pooch/latest/downloaders.html
[2]: https://github.com/conda/rattler
[3]: https://rattler.prefix.dev/py-rattler/client/
[4]: https://github.com/fatiando/pooch/issues/398
[5]: https://github.com/fatiando/pooch/issues/363
[6]: https://github.com/fatiando/pooch/issues/464
[7]: https://github.com/hingebase/pooch-rattler/tree/main/tests
