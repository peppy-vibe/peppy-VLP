"""Tests for vlp.handshake packet helpers."""

import json

import pytest

from vlp.constants import CtrlID, VLP_VERSION
from vlp.exceptions import VersionMismatchError
from vlp.packet import (
    FileMetadata,
    decode_control_packet,
    decode_handshake_json,
    encode_handshake_ack,
    encode_handshake_ready,
)
from vlp.config import ReceiverConfig, SenderConfig


@pytest.fixture
def sender_cfg():
    return SenderConfig()


@pytest.fixture
def receiver_cfg(tmp_path):
    return ReceiverConfig(cache_directory=str(tmp_path))


@pytest.fixture
def file_meta():
    return FileMetadata(
        name="test.bin",
        size_bytes=1024,
        sha256="abc123",
        total_frames=8,
    )


def test_ready_packet_structure(sender_cfg, receiver_cfg, file_meta):
    sid = 0xDEADBEEFCAFEBABE
    raw = encode_handshake_ready(sid, file_meta, sender_cfg, receiver_cfg)
    ctrl = decode_control_packet(raw)

    assert ctrl.ctrl_id == CtrlID.HANDSHAKE_READY
    body = decode_handshake_json(ctrl.payload)
    assert body["vlp_version"] == VLP_VERSION
    assert body["sid"] == format(sid, "016X")
    assert body["file"]["name"] == "test.bin"
    assert body["file"]["total_frames"] == 8
    assert "sender_config" in body
    assert "receiver_config" in body
    # cache_directory must NOT be transmitted
    assert "cache_directory" not in body["receiver_config"]


def test_ack_packet_structure():
    local_sid = 0x1111111111111111
    opposing_sid = 0x2222222222222222
    raw = encode_handshake_ack(local_sid, opposing_sid, total_frames=42)
    ctrl = decode_control_packet(raw)

    assert ctrl.ctrl_id == CtrlID.HANDSHAKE_ACK
    body = decode_handshake_json(ctrl.payload)
    assert body["vlp_version"] == VLP_VERSION
    assert int(body["opposing_sid"], 16) == opposing_sid
    assert body["frame_buffer_allocated"] == 42


def test_handshake_json_malformed():
    from vlp.exceptions import VLPError

    with pytest.raises(VLPError):
        decode_handshake_json(b"not json {{{")
