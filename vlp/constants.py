"""Protocol-level constants for VLP v1.0."""

import enum

MAGIC_BYTES: bytes = b"\x56\x4C"
VLP_VERSION: str = "1.0"

# Fixed overhead: Header(2) + SID(8) + SeqID(4) + TotalFrames(4) + CRC32(4)
PACKET_OVERHEAD_BYTES: int = 22


class CtrlID:
    """Control packet type identifiers."""

    HANDSHAKE_READY: int = 0x01
    HANDSHAKE_ACK: int = 0x02
    FRAME_ACK: int = 0x03
    STATUS: int = 0x04
    RETRANSMIT_DONE: int = 0x05
    SESSION_COMPLETE: int = 0x06
    SESSION_ACK: int = 0x07
    SESSION_ABORT: int = 0x08


class ErrorCode:
    """Abort error codes."""

    VERSION_MISMATCH: int = 0x01
    CONFIG_INCOMPATIBLE: int = 0x02
    HANDSHAKE_TIMEOUT: int = 0x03
    SID_MISMATCH: int = 0x04
    MAGIC_INVALID: int = 0x05
    CRC_FAIL: int = 0x06
    ACK_TIMEOUT: int = 0x07
    FEEDBACK_TIMEOUT: int = 0x08
    MAX_RECOVERY_EXCEEDED: int = 0x09
    CACHE_FULL: int = 0x0A
    CACHE_WRITE_FAIL: int = 0x0B
    HASH_MISMATCH: int = 0x0C
    TOTAL_FRAMES_MISMATCH: int = 0x0D
    REMOTE_ABORT: int = 0x0E


class SessionState(str, enum.Enum):
    """Session state machine states.

    Inherits from ``str`` so values serialise correctly in JSON
    (``json.dumps({"state": SessionState.STREAMING})`` → ``"STREAMING"``).
    """

    IDLE = "IDLE"
    HANDSHAKING = "HANDSHAKING"
    CONFIRMING = "CONFIRMING"
    STREAMING = "STREAMING"
    RECOVERING = "RECOVERING"
    COMPLETING = "COMPLETING"
    DONE = "DONE"
    ABORTED = "ABORTED"
