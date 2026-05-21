"""VLP exception hierarchy — one class per fatal error code."""

from vlp.constants import ErrorCode


class VLPError(Exception):
    """Base exception for all VLP protocol errors."""

    error_code: int = 0xFF

    def __init__(self, message: str = "", error_code: int | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class VersionMismatchError(VLPError):
    error_code = ErrorCode.VERSION_MISMATCH


class ConfigIncompatibleError(VLPError):
    error_code = ErrorCode.CONFIG_INCOMPATIBLE


class HandshakeTimeoutError(VLPError):
    error_code = ErrorCode.HANDSHAKE_TIMEOUT


class SIDMismatchError(VLPError):
    error_code = ErrorCode.SID_MISMATCH


class MagicInvalidError(VLPError):
    error_code = ErrorCode.MAGIC_INVALID


class CRCFailError(VLPError):
    error_code = ErrorCode.CRC_FAIL


class ACKTimeoutError(VLPError):
    error_code = ErrorCode.ACK_TIMEOUT


class FeedbackTimeoutError(VLPError):
    error_code = ErrorCode.FEEDBACK_TIMEOUT


class MaxRecoveryExceededError(VLPError):
    error_code = ErrorCode.MAX_RECOVERY_EXCEEDED


class CacheFullError(VLPError):
    error_code = ErrorCode.CACHE_FULL


class CacheWriteFailError(VLPError):
    error_code = ErrorCode.CACHE_WRITE_FAIL


class HashMismatchError(VLPError):
    error_code = ErrorCode.HASH_MISMATCH


class TotalFramesMismatchError(VLPError):
    error_code = ErrorCode.TOTAL_FRAMES_MISMATCH


class RemoteAbortError(VLPError):
    error_code = ErrorCode.REMOTE_ABORT


# Map error code byte → exception class for convenient lookup
ERROR_CODE_MAP: dict[int, type[VLPError]] = {
    ErrorCode.VERSION_MISMATCH: VersionMismatchError,
    ErrorCode.CONFIG_INCOMPATIBLE: ConfigIncompatibleError,
    ErrorCode.HANDSHAKE_TIMEOUT: HandshakeTimeoutError,
    ErrorCode.SID_MISMATCH: SIDMismatchError,
    ErrorCode.MAGIC_INVALID: MagicInvalidError,
    ErrorCode.CRC_FAIL: CRCFailError,
    ErrorCode.ACK_TIMEOUT: ACKTimeoutError,
    ErrorCode.FEEDBACK_TIMEOUT: FeedbackTimeoutError,
    ErrorCode.MAX_RECOVERY_EXCEEDED: MaxRecoveryExceededError,
    ErrorCode.CACHE_FULL: CacheFullError,
    ErrorCode.CACHE_WRITE_FAIL: CacheWriteFailError,
    ErrorCode.HASH_MISMATCH: HashMismatchError,
    ErrorCode.TOTAL_FRAMES_MISMATCH: TotalFramesMismatchError,
    ErrorCode.REMOTE_ABORT: RemoteAbortError,
}


def raise_for_code(code: int, message: str = "") -> None:
    """Raise the appropriate VLPError subclass for *code*."""
    exc_cls = ERROR_CODE_MAP.get(code, VLPError)
    raise exc_cls(message, error_code=code)
