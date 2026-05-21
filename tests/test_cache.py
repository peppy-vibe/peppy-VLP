"""Tests for vlp.cache."""

import json
import os

import pytest

from vlp.cache import SessionCache
from vlp.exceptions import CacheFullError


@pytest.fixture
def cache(tmp_path):
    c = SessionCache(
        cache_directory=str(tmp_path),
        opposing_sid="AABBCCDDEEFF0011",
        max_cache_size_mb=10,
    )
    c.initialize({"state": "STREAMING", "vlp_version": "1.0"})
    return c


def test_initialize_creates_dirs(tmp_path):
    c = SessionCache(str(tmp_path), "DEADBEEF00000001")
    c.initialize({"state": "STREAMING"})
    assert os.path.isdir(os.path.join(str(tmp_path), "vlp_DEADBEEF00000001", "frames"))
    assert os.path.isfile(os.path.join(str(tmp_path), "vlp_DEADBEEF00000001", "session.json"))


def test_write_and_read_frame(cache):
    cache.write_frame(0, b"hello")
    assert cache.read_frame(0) == b"hello"


def test_frame_exists(cache):
    assert not cache.frame_exists(5)
    cache.write_frame(5, b"data")
    assert cache.frame_exists(5)


def test_atomic_write_no_tmp_left(cache, tmp_path):
    cache.write_frame(1, b"atomic")
    frames_dir = os.path.join(str(tmp_path), "vlp_AABBCCDDEEFF0011", "frames")
    tmp_files = [f for f in os.listdir(frames_dir) if f.endswith(".tmp")]
    assert tmp_files == []


def test_overwrite_existing_frame(cache):
    cache.write_frame(0, b"first")
    cache.write_frame(0, b"second")
    assert cache.read_frame(0) == b"second"


def test_assemble_file(cache, tmp_path):
    for i in range(3):
        cache.write_frame(i, bytes([i] * 4))
    out = str(tmp_path / "out.bin")
    cache.assemble_file(3, out)
    with open(out, "rb") as fh:
        data = fh.read()
    assert data == bytes([0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2])


def test_cleanup(cache, tmp_path):
    cache.write_frame(0, b"data")
    cache.cleanup()
    assert not os.path.exists(os.path.join(str(tmp_path), "vlp_AABBCCDDEEFF0011"))


def test_update_session_json(cache):
    cache.update_session_json({"state": "RECOVERING"})
    data = cache.read_session_json()
    assert data["state"] == "RECOVERING"


def test_find_resumable_sessions(tmp_path):
    # Create a fake incomplete session
    d = tmp_path / "vlp_DEADBEEF11111111"
    d.mkdir()
    sj = d / "session.json"
    sj.write_text(json.dumps({"state": "STREAMING", "opposing_sid": "DEAD"}))

    # Create a completed session (should be excluded)
    d2 = tmp_path / "vlp_DEADBEEF22222222"
    d2.mkdir()
    sj2 = d2 / "session.json"
    sj2.write_text(json.dumps({"state": "DONE", "opposing_sid": "BEEF"}))

    results = SessionCache.find_resumable_sessions(str(tmp_path))
    assert len(results) == 1
    assert results[0]["opposing_sid"] == "DEAD"


def test_cache_full_raises(tmp_path):
    c = SessionCache(str(tmp_path), "FFFFFFFFFFFFFFFF", max_cache_size_mb=0)
    c.initialize({"state": "STREAMING"})
    with pytest.raises(CacheFullError):
        c.write_frame(0, b"x" * 1024)
