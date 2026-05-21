"""Tests for vlp.packet."""

import struct
import zlib

import pytest

from vlp.constants import MAGIC_BYTES, CtrlID
from vlp.exceptions import CRCFailError, MagicInvalidError
from vlp.packet import (
    DataPacket,
    decode_control_packet,
    decode_data_packet,
    encode_control_packet,
    encode_data_packet,
    encode_handshake_ack,
    encode_payload,
    decode_payload,
    max_raw_bytes_per_frame,
)


# ---------------------------------------------------------------------------
# Payload encode/decode
# ---------------------------------------------------------------------------

def test_base64_roundtrip():
    raw = b"\x00\xFF\xAB\xCD" * 50
    encoded = encode_payload(raw, "BASE64")
    assert decode_payload(encoded, "BASE64") == raw


def test_raw_bytes_roundtrip():
    raw = b"\x01\x02\x03"
    assert decode_payload(encode_payload(raw, "RAW_BYTES"), "RAW_BYTES") == raw


# ---------------------------------------------------------------------------
# Data packet encode / decode
# ---------------------------------------------------------------------------

def test_data_packet_roundtrip():
    sid, seq_id, total = 0xDEADBEEFCAFEBABE, 42, 100
    payload = b"hello world"
    encoded = encode_payload(payload, "BASE64")
    raw = encode_data_packet(sid, seq_id, total, encoded)

    pkt = decode_data_packet(raw, "BASE64")
    assert pkt.sid == sid
    assert pkt.seq_id == seq_id
    assert pkt.total_frames == total
    assert pkt.payload == payload


def test_data_packet_big_endian():
    """Verify big-endian byte order in the wire format."""
    sid = 0x0102030405060708
    seq_id = 0x00000001
    total = 0x00000064
    payload = b"x"
    encoded = encode_payload(payload, "RAW_BYTES")
    raw = encode_data_packet(sid, seq_id, total, encoded)

    # Magic
    assert raw[:2] == b"VL"
    # SID big-endian
    assert struct.unpack_from(">Q", raw, 2)[0] == sid
    # Seq ID big-endian
    assert struct.unpack_from(">I", raw, 10)[0] == seq_id
    # Total frames big-endian
    assert struct.unpack_from(">I", raw, 14)[0] == total


def test_crc32_validation():
    sid, seq_id, total = 1, 0, 1
    encoded = encode_payload(b"data", "BASE64")
    raw = bytearray(encode_data_packet(sid, seq_id, total, encoded))
    # Corrupt last byte (CRC)
    raw[-1] ^= 0xFF
    with pytest.raises(CRCFailError):
        decode_data_packet(bytes(raw), "BASE64")


def test_magic_bytes_rejected():
    raw = b"\x00\x00" + b"\x00" * 20
    with pytest.raises(MagicInvalidError):
        decode_data_packet(raw)


# ---------------------------------------------------------------------------
# Control packet
# ---------------------------------------------------------------------------

def test_control_packet_roundtrip():
    sid = 0xAABBCCDDEEFF0011
    ctrl = encode_control_packet(sid, CtrlID.STATUS, b"\xDE\xAD")
    pkt = decode_control_packet(ctrl)
    assert pkt.sid == sid
    assert pkt.ctrl_id == CtrlID.STATUS
    assert pkt.payload == b"\xDE\xAD"


def test_control_packet_empty_payload():
    pkt = decode_control_packet(encode_control_packet(1, CtrlID.SESSION_ACK))
    assert pkt.payload == b""


def test_control_magic_rejected():
    with pytest.raises(MagicInvalidError):
        decode_control_packet(b"\xFF\xFF" + b"\x00" * 9)


# ---------------------------------------------------------------------------
# max_raw_bytes_per_frame
# ---------------------------------------------------------------------------

def test_max_raw_bytes_base64():
    # version 10, M: capacity 213 bytes; available = 213 - 22 = 191; base64 = (191*3)//4 = 143
    assert max_raw_bytes_per_frame(10, "M", "BASE64") == 143


def test_max_raw_bytes_raw():
    assert max_raw_bytes_per_frame(10, "M", "RAW_BYTES") == 213 - 22
