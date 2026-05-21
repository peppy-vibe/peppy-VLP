"""Configuration dataclasses for VLP v1.0."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

_VALID_EC = {"M", "Q", "H"}
_VALID_FEEDBACK_POSITIONS = {"BOTTOM_RIGHT", "BOTTOM_LEFT", "TOP_RIGHT", "TOP_LEFT"}
_VALID_STREAMING_MODES = {"PACED", "ACKNOWLEDGED"}
_VALID_ENCODINGS = {"BASE64", "RAW_BYTES"}


@dataclass(frozen=True)
class SenderConfig:
    """Parameters that govern the Sender role's QR rendering and streaming behaviour."""

    stream_qr_version: int = 10
    stream_qr_error_correction: str = "M"
    stream_qr_box_size: int = 10
    stream_qr_border: int = 4
    streaming_mode: str = "PACED"
    frame_interval_ms: int = 150
    ack_timeout_ms: int = 3000
    max_ack_retries: int = 5
    payload_encoding: str = "BASE64"

    def __post_init__(self) -> None:
        if self.stream_qr_error_correction not in _VALID_EC:
            raise ValueError(
                f"stream_qr_error_correction must be one of {_VALID_EC}; "
                f"got {self.stream_qr_error_correction!r}"
            )
        if self.stream_qr_box_size < 5:
            raise ValueError("stream_qr_box_size must be >= 5")
        if self.stream_qr_border < 4:
            raise ValueError("stream_qr_border must be >= 4")
        if not (80 <= self.frame_interval_ms <= 5000):
            raise ValueError("frame_interval_ms must be in [80, 5000]")
        if self.ack_timeout_ms < 500:
            raise ValueError("ack_timeout_ms must be >= 500")
        if self.streaming_mode not in _VALID_STREAMING_MODES:
            raise ValueError(
                f"streaming_mode must be one of {_VALID_STREAMING_MODES}; "
                f"got {self.streaming_mode!r}"
            )
        if self.payload_encoding not in _VALID_ENCODINGS:
            raise ValueError(
                f"payload_encoding must be one of {_VALID_ENCODINGS}; "
                f"got {self.payload_encoding!r}"
            )

    def to_dict(self) -> dict:
        return {
            "stream_qr_version": self.stream_qr_version,
            "stream_qr_error_correction": self.stream_qr_error_correction,
            "stream_qr_box_size": self.stream_qr_box_size,
            "stream_qr_border": self.stream_qr_border,
            "streaming_mode": self.streaming_mode,
            "frame_interval_ms": self.frame_interval_ms,
            "ack_timeout_ms": self.ack_timeout_ms,
            "max_ack_retries": self.max_ack_retries,
            "payload_encoding": self.payload_encoding,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SenderConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ReceiverConfig:
    """Parameters that govern the Receiver role's control QR rendering and cache."""

    control_qr_version: int = 5
    control_qr_error_correction: str = "Q"
    control_qr_box_size: int = 8
    control_qr_border: int = 4
    feedback_position: str = "BOTTOM_RIGHT"
    feedback_interval_ms: int = 500
    cache_directory: str = ""
    max_cache_size_mb: int = 512

    def __post_init__(self) -> None:
        if self.control_qr_box_size < 5:
            raise ValueError("control_qr_box_size must be >= 5")
        if self.control_qr_border < 4:
            raise ValueError("control_qr_border must be >= 4")
        if self.feedback_position not in _VALID_FEEDBACK_POSITIONS:
            raise ValueError(
                f"feedback_position must be one of {_VALID_FEEDBACK_POSITIONS}; "
                f"got {self.feedback_position!r}"
            )
        if not self.cache_directory:
            raise ValueError("cache_directory is required")
        if not os.path.isdir(self.cache_directory):
            raise ValueError(
                f"cache_directory does not exist: {self.cache_directory!r}"
            )
        if not os.access(self.cache_directory, os.W_OK):
            raise ValueError(
                f"cache_directory is not writable: {self.cache_directory!r}"
            )

    def to_dict(self) -> dict:
        return {
            "control_qr_version": self.control_qr_version,
            "control_qr_error_correction": self.control_qr_error_correction,
            "control_qr_box_size": self.control_qr_box_size,
            "control_qr_border": self.control_qr_border,
            "feedback_position": self.feedback_position,
            "feedback_interval_ms": self.feedback_interval_ms,
            "cache_directory": self.cache_directory,
            "max_cache_size_mb": self.max_cache_size_mb,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReceiverConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class TimeoutConfig:
    """Session-wide timeout and retry policy (not exchanged over the wire)."""

    handshake_timeout_ms: int = 30_000
    feedback_scan_timeout_ms: int = 10_000
    max_recovery_rounds: int = 10
    completion_timeout_ms: int = 15_000

    def __post_init__(self) -> None:
        if self.handshake_timeout_ms < 5_000:
            raise ValueError("handshake_timeout_ms must be >= 5000")
        if self.completion_timeout_ms < 5_000:
            raise ValueError("completion_timeout_ms must be >= 5000")
