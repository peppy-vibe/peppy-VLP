"""Binary packet encode/decode for all VLP packet types."""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib
from dataclasses import dataclass

from vlp.constants import MAGIC_BYTES, PACKET_OVERHEAD_BYTES, VLP_VERSION
from vlp.exceptions import CRCFailError, MagicInvalidError, VLPError

# Header sizes derived from struct format strings — avoids bare integer offsets.
# Data packet:    MAGIC(2) + SID(8) + SEQ_ID(4) + TOTAL_FRAMES(4) = 18 bytes
# Control packet: MAGIC(2) + SID(8) + CTRL_ID(1)                  = 11 bytes
_DATA_HEADER_SIZE: int = struct.calcsize(">2sQII")   # == 18
_CTRL_HEADER_SIZE: int = struct.calcsize(">2sQB")    # == 11

# ---------------------------------------------------------------------------
# QR capacity table  (version, ec_level) → max binary bytes (byte/binary mode)
# ---------------------------------------------------------------------------
QR_CAPACITY: dict[tuple[int, str], int] = {
    # Versions 1–9 (smaller codes; useful for tests and control frames)
    (1, "L"): 17,  (1, "M"): 14,  (1, "Q"): 11,  (1, "H"): 7,
    (2, "L"): 32,  (2, "M"): 26,  (2, "Q"): 20,  (2, "H"): 14,
    (3, "L"): 53,  (3, "M"): 42,  (3, "Q"): 32,  (3, "H"): 24,
    (4, "L"): 78,  (4, "M"): 62,  (4, "Q"): 46,  (4, "H"): 34,
    (5, "L"): 106, (5, "M"): 84,  (5, "Q"): 60,  (5, "H"): 46,
    (6, "L"): 134, (6, "M"): 106, (6, "Q"): 74,  (6, "H"): 60,
    (7, "L"): 154, (7, "M"): 122, (7, "Q"): 86,  (7, "H"): 66,
    (8, "L"): 192, (8, "M"): 154, (8, "Q"): 108, (8, "H"): 86,
    (9, "L"): 230, (9, "M"): 182, (9, "Q"): 130, (9, "H"): 100,
    # Versions 10–40 (spec §5.1 reference table)
    (10, "L"): 271, (10, "M"): 213, (10, "Q"): 151, (10, "H"): 117,
    (15, "L"): 520, (15, "M"): 412, (15, "Q"): 290, (15, "H"): 223,
    (20, "L"): 858, (20, "M"): 666, (20, "Q"): 474, (20, "H"): 365,
    (25, "L"): 1273, (25, "M"): 1000, (25, "Q"): 706, (25, "H"): 544,
    (30, "L"): 1732, (30, "M"): 1362, (30, "Q"): 966, (30, "H"): 745,
    (40, "L"): 2953, (40, "M"): 2331, (40, "Q"): 1663, (40, "H"): 1273,
}


def max_raw_bytes_per_frame(qr_version: int, ec_level: str, encoding: str) -> int:
    """Return max raw binary bytes that fit in one data frame."""
    capacity = QR_CAPACITY[(qr_version, ec_level)]
    available = capacity - PACKET_OVERHEAD_BYTES
    if encoding == "BASE64":
        return (available * 3) // 4
    return available


# ---------------------------------------------------------------------------
# Payload encode / decode
# ---------------------------------------------------------------------------

def encode_payload(raw_chunk: bytes, encoding: str) -> bytes:
    """Encode raw bytes per payload_encoding setting."""
    if encoding == "BASE64":
        return base64.b64encode(raw_chunk)
    return raw_chunk


def decode_payload(encoded: bytes, encoding: str) -> bytes:
    """Decode payload bytes per payload_encoding setting."""
    if encoding == "BASE64":
        return base64.b64decode(encoded)
    return encoded


# ---------------------------------------------------------------------------
# Data packets
# ---------------------------------------------------------------------------

@dataclass
class DataPacket:
    sid: int
    seq_id: int
    total_frames: int
    payload: bytes  # decoded (raw) payload


def encode_data_packet(
    sid: int,
    seq_id: int,
    total_frames: int,
    encoded_payload: bytes,
) -> bytes:
    """Pack: MAGIC(2) + SID(8) + SEQ_ID(4) + TOTAL_FRAMES(4) + PAYLOAD(var) + CRC32(4).

    *encoded_payload* is already Base64/raw — CRC32 is computed over it.
    """
    crc = zlib.crc32(encoded_payload) & 0xFFFFFFFF
    header = struct.pack(">2sQII", MAGIC_BYTES, sid, seq_id, total_frames)
    return header + encoded_payload + struct.pack(">I", crc)


def decode_data_packet(raw: bytes, encoding: str = "BASE64") -> DataPacket:
    """Validate and unpack a data packet.

    Raises :class:`MagicInvalidError` or :class:`CRCFailError` on failure.
    """
    _check_magic(raw)
    if len(raw) < PACKET_OVERHEAD_BYTES:
        raise VLPError("Data packet too short")

    # header prefix: MAGIC(2) + SID(8) + SEQ_ID(4) + TOTAL_FRAMES(4)
    _, sid, seq_id, total_frames = struct.unpack_from(">2sQII", raw, 0)
    encoded_payload = raw[_DATA_HEADER_SIZE:-4]
    expected_crc = struct.unpack_from(">I", raw, len(raw) - 4)[0]
    actual_crc = zlib.crc32(encoded_payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise CRCFailError(
            f"CRC mismatch: expected {expected_crc:#010x}, got {actual_crc:#010x}"
        )
    return DataPacket(
        sid=sid,
        seq_id=seq_id,
        total_frames=total_frames,
        payload=decode_payload(encoded_payload, encoding),
    )


# ---------------------------------------------------------------------------
# Control packets
# ---------------------------------------------------------------------------

@dataclass
class ControlPacket:
    sid: int
    ctrl_id: int
    payload: bytes


def encode_control_packet(sid: int, ctrl_id: int, payload: bytes = b"") -> bytes:
    """Pack: MAGIC(2) + SID(8) + CTRL_ID(1) + PAYLOAD(var)."""
    return struct.pack(">2sQB", MAGIC_BYTES, sid, ctrl_id) + payload


def decode_control_packet(raw: bytes) -> ControlPacket:
    """Unpack a control packet.  Raises :class:`MagicInvalidError` on bad magic."""
    _check_magic(raw)
    if len(raw) < _CTRL_HEADER_SIZE:  # MAGIC(2) + SID(8) + CTRL_ID(1)
        raise VLPError("Control packet too short")
    _, sid, ctrl_id = struct.unpack_from(">2sQB", raw, 0)
    return ControlPacket(sid=sid, ctrl_id=ctrl_id, payload=raw[_CTRL_HEADER_SIZE:])


# ---------------------------------------------------------------------------
# Handshake packet helpers
# ---------------------------------------------------------------------------

def encode_handshake_ready(
    sid: int,
    file_meta: "FileMetadata",
    sender_cfg: "SenderConfig",
    receiver_cfg: "ReceiverConfig",
) -> bytes:
    """Encode a HANDSHAKE_READY control packet with JSON payload."""
    from vlp.constants import CtrlID  # local import to avoid circularity

    body = {
        "vlp_version": VLP_VERSION,
        "sid": format(sid, "016X"),
        "file": {
            "name": file_meta.name,
            "size_bytes": file_meta.size_bytes,
            "sha256": file_meta.sha256,
            "total_frames": file_meta.total_frames,
        },
        "sender_config": sender_cfg.to_dict(),
        "receiver_config": receiver_cfg.to_dict(),  # cache_directory excluded by to_dict()
    }
    payload = json.dumps(body, separators=(",", ":")).encode()
    return encode_control_packet(sid, CtrlID.HANDSHAKE_READY, payload)


def encode_handshake_ack(
    local_sid: int,
    opposing_sid: int,
    total_frames: int,
) -> bytes:
    """Encode a HANDSHAKE_ACK control packet with JSON payload."""
    from vlp.constants import CtrlID

    body = {
        "vlp_version": VLP_VERSION,
        "opposing_sid": format(opposing_sid, "016X"),
        "frame_buffer_allocated": total_frames,
    }
    payload = json.dumps(body, separators=(",", ":")).encode()
    return encode_control_packet(local_sid, CtrlID.HANDSHAKE_ACK, payload)


def decode_handshake_json(payload: bytes) -> dict:
    """UTF-8 decode + parse JSON.  Raises VLPError on malformed input."""
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VLPError(f"Malformed handshake JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_magic(raw: bytes) -> None:
    if len(raw) < 2 or raw[:2] != MAGIC_BYTES:
        raise MagicInvalidError(
            f"Invalid magic bytes: {raw[:2]!r}; expected {MAGIC_BYTES!r}"
        )


# ---------------------------------------------------------------------------
# FileMetadata (used across modules)
# ---------------------------------------------------------------------------

@dataclass
class FileMetadata:
    name: str
    size_bytes: int
    sha256: str
    total_frames: int
