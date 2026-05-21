"""Integration test — loopback session using pre-rendered frames (no camera)."""

from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from vlp.bitmask import Bitmask
from vlp.cache import SessionCache
from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
from vlp.constants import CtrlID
from vlp.packet import (
    FileMetadata,
    encode_control_packet,
    encode_data_packet,
    encode_payload,
    max_raw_bytes_per_frame,
)
from vlp.receiver import ReceiverRole
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


def test_sender_receiver_loopback(tmp_path, sender_cfg, receiver_cfg):
    """
    Loopback test: SenderRole renders frames in-memory;
    ReceiverRole decodes them from the mock scanner.
    No real camera or display required.
    """
    data = b"The quick brown fox jumps over the lazy dog. " * 5
    sha256 = hashlib.sha256(data).hexdigest()

    src = tmp_path / "source.bin"
    src.write_bytes(data)

    chunk = max_raw_bytes_per_frame(
        sender_cfg.stream_qr_version,
        sender_cfg.stream_qr_error_correction,
        sender_cfg.payload_encoding,
    )
    total = math.ceil(len(data) / chunk)
    meta = FileMetadata("source.bin", len(data), sha256, total)

    sid = 0xABCDEF0123456789
    abort = threading.Event()

    # Pre-render all data packets (the Sender role would normally do this)
    packets = []
    for i in range(total):
        chunk_bytes = data[i * chunk: (i + 1) * chunk]
        enc = encode_payload(chunk_bytes, sender_cfg.payload_encoding)
        pkt = encode_data_packet(sid, i, total, enc)
        packets.append(pkt)

    complete_pkt = encode_control_packet(sid, CtrlID.SESSION_COMPLETE)
    packets.append(complete_pkt)

    # Feed packets to the mock scanner
    call_idx = [0]

    def fake_scan(last_color, opposing_box_size, opposing_border):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(packets):
            color = "BLACK" if idx % 2 == 0 else "WHITE"
            return packets[idx], color
        return None, "BLACK"

    scanner = MagicMock()
    scanner.scan_for_packet.side_effect = fake_scan
    display = MagicMock()

    cache = SessionCache(str(tmp_path), format(sid, "016X"))
    cache.initialize({"state": "STREAMING"})
    bitmask = Bitmask(total)
    output_path = str(tmp_path / "received.bin")

    receiver = ReceiverRole(
        opposing_sid=sid,
        opposing_file_meta=meta,
        opposing_sender_cfg=sender_cfg,
        receiver_cfg=receiver_cfg,
        output_path=output_path,
        display=display,
        scanner=scanner,
        cache=cache,
        bitmask=bitmask,
        timeout_cfg=TimeoutConfig(),
        abort_event=abort,
    )

    receiver.run()

    assert os.path.isfile(output_path)
    with open(output_path, "rb") as fh:
        received = fh.read()
    assert received == data
    assert hashlib.sha256(received).hexdigest() == sha256
