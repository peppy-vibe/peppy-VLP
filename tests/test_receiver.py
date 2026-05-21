"""Tests for vlp.receiver — capture loop bitmask, CRC rejection, hash verification."""

from __future__ import annotations

import hashlib
import math
import struct
import threading
import time
import zlib
from unittest.mock import MagicMock

import pytest

from vlp.bitmask import Bitmask
from vlp.cache import SessionCache
from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
from vlp.constants import CtrlID
from vlp.exceptions import HashMismatchError
from vlp.packet import (
    FileMetadata,
    encode_control_packet,
    encode_data_packet,
    encode_payload,
    max_raw_bytes_per_frame,
)
from vlp.receiver import ReceiverRole


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


def _build_data_pkt(sid, seq_id, total, payload_bytes, encoding="BASE64"):
    enc = encode_payload(payload_bytes, encoding)
    return encode_data_packet(sid, seq_id, total, enc)


def _make_receiver(
    tmp_path, sender_cfg, receiver_cfg,
    data_bytes=b"ABCDEFGH" * 10,
    abort_event=None,
):
    chunk = max_raw_bytes_per_frame(
        sender_cfg.stream_qr_version,
        sender_cfg.stream_qr_error_correction,
        sender_cfg.payload_encoding,
    )
    total = math.ceil(len(data_bytes) / chunk)
    sha256 = hashlib.sha256(data_bytes).hexdigest()
    meta = FileMetadata("out.bin", len(data_bytes), sha256, total)

    opposing_sid = 0xCAFEBABEDEAD0001
    cache = SessionCache(str(tmp_path), format(opposing_sid, "016X"))
    cache.initialize({"state": "STREAMING"})
    bitmask = Bitmask(total)

    display = MagicMock()
    scanner = MagicMock()
    abort = abort_event or threading.Event()
    timeout_cfg = TimeoutConfig()
    output_path = str(tmp_path / "received.bin")

    receiver = ReceiverRole(
        opposing_sid=opposing_sid,
        opposing_file_meta=meta,
        opposing_sender_cfg=sender_cfg,
        receiver_cfg=receiver_cfg,
        output_path=output_path,
        display=display,
        scanner=scanner,
        cache=cache,
        bitmask=bitmask,
        timeout_cfg=timeout_cfg,
        abort_event=abort,
    )
    return receiver, opposing_sid, data_bytes, chunk, total, cache, bitmask, output_path


def test_capture_loop_marks_bitmask(tmp_path, sender_cfg, receiver_cfg):
    data = b"X" * 50
    receiver, sid, data_bytes, chunk, total, cache, bitmask, _ = _make_receiver(
        tmp_path, sender_cfg, receiver_cfg, data_bytes=data
    )

    packets = [
        _build_data_pkt(sid, i, total, data_bytes[i * chunk: (i + 1) * chunk])
        for i in range(total)
    ]
    # append SESSION_COMPLETE after all data
    complete_pkt = encode_control_packet(sid, CtrlID.SESSION_COMPLETE)
    packets.append(complete_pkt)

    call_idx = [0]
    anchor = ["UNKNOWN"]

    def fake_scan(last_color, opposing_box_size, opposing_border):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(packets):
            color = "BLACK" if idx % 2 == 0 else "WHITE"
            return packets[idx], color
        return None, anchor[0]

    receiver._scanner.scan_for_packet.side_effect = fake_scan

    receiver._capture_loop()

    assert bitmask.all_received()


def test_corrupt_crc_not_written(tmp_path, sender_cfg, receiver_cfg):
    data = b"Y" * 50
    receiver, sid, data_bytes, chunk, total, cache, bitmask, _ = _make_receiver(
        tmp_path, sender_cfg, receiver_cfg, data_bytes=data
    )

    good_pkt = _build_data_pkt(sid, 0, total, data_bytes[:chunk])
    # Corrupt the CRC
    bad_pkt = bytearray(good_pkt)
    bad_pkt[-1] ^= 0xFF
    bad_pkt = bytes(bad_pkt)

    complete_pkt = encode_control_packet(sid, CtrlID.SESSION_COMPLETE)

    packets = [bad_pkt, complete_pkt]
    call_idx = [0]

    def fake_scan(last_color, opposing_box_size, opposing_border):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(packets):
            return packets[idx], "BLACK" if idx % 2 == 0 else "WHITE"
        return None, "BLACK"

    receiver._scanner.scan_for_packet.side_effect = fake_scan
    receiver._capture_loop()

    assert not cache.frame_exists(0)


def test_assembly_sha256_mismatch(tmp_path, sender_cfg, receiver_cfg):
    data = b"Z" * 30
    receiver, sid, data_bytes, chunk, total, cache, bitmask, output_path = (
        _make_receiver(tmp_path, sender_cfg, receiver_cfg, data_bytes=data)
    )

    # Write correct frames to cache but then corrupt the meta sha256
    for i in range(total):
        cache.write_frame(i, data_bytes[i * chunk: (i + 1) * chunk])

    receiver._file_meta = FileMetadata(
        "out.bin", len(data), "wronghash000", total
    )

    with pytest.raises(HashMismatchError):
        receiver._assembly_phase()
