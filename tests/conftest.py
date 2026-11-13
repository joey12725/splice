from __future__ import annotations

import os

import pytest

from splice.sandbox import (
    BubblewrapSandbox,
    ContainerSandbox,
    PodmanSandbox,
    ProcessSandbox,
    Sandbox,
    SeatbeltSandbox,
)

# Local backends run on every machine where they are available. Container
# backends need an image pull, so they only run when explicitly requested.
_LOCAL = [ProcessSandbox, SeatbeltSandbox, BubblewrapSandbox]
_CONTAINER = [ContainerSandbox, PodmanSandbox]


def _backend_params() -> list[object]:
    params: list[object] = []
    for cls in _LOCAL:
        params.append(
            pytest.param(
                cls,
                id=cls.name,
                marks=pytest.mark.skipif(
                    not cls.is_available(), reason=f"{cls.name} backend not available"
                ),
            )
        )
    want_containers = os.getenv("SPLICE_TEST_CONTAINERS") == "1"
    for cls in _CONTAINER:
        params.append(
            pytest.param(
                cls,
                id=cls.name,
                marks=pytest.mark.skipif(
                    not (want_containers and cls.is_available()),
                    reason="set SPLICE_TEST_CONTAINERS=1 with a working runtime",
                ),
            )
        )
    return params


@pytest.fixture(params=_backend_params())
def backend(request: pytest.FixtureRequest) -> Sandbox:
    cls = request.param
    sandbox: Sandbox = cls()
    return sandbox


@pytest.fixture(
    params=[
        pytest.param(
            cls,
            id=cls.name,
            marks=pytest.mark.skipif(not cls.is_available(), reason=f"{cls.name} unavailable"),
        )
        for cls in (SeatbeltSandbox, BubblewrapSandbox)
    ]
)
def os_backend(request: pytest.FixtureRequest) -> ProcessSandbox:
    """Backends that add a kernel-enforced layer on top of the process sandbox."""

    sandbox: ProcessSandbox = request.param()
    return sandbox
