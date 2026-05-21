"""Tests for vlp.sender — frame chunking and paced mode (mocked I/O)."""

from __future__ import annotations

import math
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
from vlp.packet import FileMetadata, max_raw_bytes_per_frame
from vlp.sender import SenderRole


@pytest.fixture
def sender_cfg():
    return SenderConfig(
        stream_qr_version=5,
        stream_qr_error_correction="M",
        stream_qr_box_size=5,
        stream_qr_border=4,
        frame_interval_ms=80,
    )


@pytest.fixture
def receiver_cfg(tmp_path):
    return ReceiverConfig(cache_directory=str(tmp_path))


@pytest.fixture
def small_file(tmp_path):
    p = tmp_path / "data.bin"
    p.write_bytes(b"A" * 300)
    return str(p)


def _make_sender(file_path, sender_cfg, receiver_cfg, abort_event=None):
    chunk = max_raw_bytes_per_frame(
        sender_cfg.stream_qr_version,
        sender_cfg.stream_qr_error_correction,
        sender_cfg.payload_encoding,
    )
    size = os.path.getsize(file_path)
    total = math.ceil(size / chunk)
    meta = FileMetadata("data.bin", size, "sha", total)

    display = MagicMock()
    scanner = MagicMock()
    scanner.scan_blocking.return_value = None  # no ack by default
    timeout_cfg = TimeoutConfig()
    abort_event = abort_event or threading.Event()

    return SenderRole(
        file_path=file_path,
        file_meta=meta,
        sid=0xDEAD,
        sender_cfg=sender_cfg,
        receiver_cfg=receiver_cfg,
        display=display,
        scanner=scanner,
        timeout_cfg=timeout_cfg,
        abort_event=abort_event,
    ), display, scanner


def test_paced_mode_displays_each_frame(small_file, sender_cfg, receiver_cfg):
    sender, display, _ = _make_sender(small_file, sender_cfg, receiver_cfg)

    # Intercept so recovery/completing don't hang — patch scanner to return bitmask
    # that says all received after streaming
    import struct as _s
    from vlp.bitmask import Bitmask
    from vlp.constants import CtrlID
    from vlp.packet import encode_control_packet

    bm = Bitmask(sender._total_frames)
    for i in range(sender._total_frames):
        bm.mark_received(i)
    payload = _s.pack(">QI", 0, sender._total_frames) + bm.to_bytes()
    status_pkt = encode_control_packet(0, CtrlID.STATUS, payload)

    display.show_main_qr.return_value = None
    call_count = [0]

    def fake_scan(timeout_ms, **kwargs):
        call_count[0] += 1
        return status_pkt

    sender._scanner.scan_blocking.side_effect = fake_scan

    sender.run()

    # Every frame should have been rendered
    assert display.show_main_qr.call_count >= sender._total_frames


def test_frame_chunking_correct_seq_order(small_file, sender_cfg, receiver_cfg):
    """Frames are read in ascending seq_id order."""
    sender, display, _ = _make_sender(small_file, sender_cfg, receiver_cfg)

    seq_ids = []
    original_render = sender._render_frame

    def capture_seq(seq_id):
        seq_ids.append(seq_id)
        return original_render(seq_id)

    sender._render_frame = capture_seq

    # Only run _streaming_phase
    sender._streaming_phase()

    assert seq_ids == list(range(sender._total_frames))


def test_abort_stops_streaming(small_file, sender_cfg, receiver_cfg):
    abort = threading.Event()
    sender, display, _ = _make_sender(small_file, sender_cfg, receiver_cfg, abort)

    abort.set()  # abort immediately
    sender._streaming_phase()

    # No frames displayed after abort
    assert display.show_main_qr.call_count == 0
