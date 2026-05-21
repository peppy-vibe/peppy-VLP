"""Tests for vlp.constants."""

from vlp.constants import CtrlID, ErrorCode, SessionState, MAGIC_BYTES, VLP_VERSION


def test_magic_bytes():
    assert MAGIC_BYTES == b"\x56\x4C"
    assert MAGIC_BYTES == b"VL"


def test_vlp_version():
    assert VLP_VERSION == "1.0"


def test_ctrl_ids_unique():
    ids = [
        CtrlID.HANDSHAKE_READY,
        CtrlID.HANDSHAKE_ACK,
        CtrlID.FRAME_ACK,
        CtrlID.STATUS,
        CtrlID.RETRANSMIT_DONE,
        CtrlID.SESSION_COMPLETE,
        CtrlID.SESSION_ACK,
        CtrlID.SESSION_ABORT,
    ]
    assert len(ids) == len(set(ids))


def test_error_codes_unique():
    codes = [
        ErrorCode.VERSION_MISMATCH,
        ErrorCode.CONFIG_INCOMPATIBLE,
        ErrorCode.HANDSHAKE_TIMEOUT,
        ErrorCode.SID_MISMATCH,
        ErrorCode.MAGIC_INVALID,
        ErrorCode.CRC_FAIL,
        ErrorCode.ACK_TIMEOUT,
        ErrorCode.FEEDBACK_TIMEOUT,
        ErrorCode.MAX_RECOVERY_EXCEEDED,
        ErrorCode.CACHE_FULL,
        ErrorCode.CACHE_WRITE_FAIL,
        ErrorCode.HASH_MISMATCH,
        ErrorCode.TOTAL_FRAMES_MISMATCH,
        ErrorCode.REMOTE_ABORT,
    ]
    assert len(codes) == len(set(codes))


def test_session_states():
    states = [
        SessionState.IDLE,
        SessionState.HANDSHAKING,
        SessionState.CONFIRMING,
        SessionState.STREAMING,
        SessionState.RECOVERING,
        SessionState.COMPLETING,
        SessionState.DONE,
        SessionState.ABORTED,
    ]
    assert len(states) == len(set(states))
