from __future__ import annotations

import pytest

from sandbox_ctl.isolation.filesystem import FilesystemLayout, to_pod_volumes_and_mounts


def test_scratch_and_code() -> None:
    layout = FilesystemLayout(scratch_mb=128, code_secret_name="run-123-code")
    volumes, mounts = to_pod_volumes_and_mounts(layout)
    assert any(v["name"] == "scratch" for v in volumes)
    assert any(v["name"] == "code" for v in volumes)
    paths = {m["mountPath"] for m in mounts}
    assert paths == {"/scratch", "/work"}
    code_mount = next(m for m in mounts if m["name"] == "code")
    assert code_mount["readOnly"] is True


def test_warm_pod_has_no_code_volume() -> None:
    layout = FilesystemLayout(scratch_mb=128, code_secret_name=None)
    volumes, mounts = to_pod_volumes_and_mounts(layout)
    assert all(v["name"] != "code" for v in volumes)
    assert all(m["name"] != "code" for m in mounts)


def test_scratch_must_be_positive() -> None:
    with pytest.raises(ValueError):
        FilesystemLayout(scratch_mb=0, code_secret_name=None)
