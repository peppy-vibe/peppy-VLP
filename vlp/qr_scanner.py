"""Camera capture, screen region detection, and QR decoding."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from vlp.image_processor import (
    anchor_changed,
    binarize_otsu,
    detect_screen_region,
    perspective_transform,
    read_anchor_color,
)

if TYPE_CHECKING:
    pass

_WARMUP_FRAMES = 10
_DEFAULT_OUTPUT_SIZE = (800, 800)


class QRScanner:
    """Manages a camera capture loop and QR-code decoding pipeline."""

    def __init__(self, camera_index: int = 0) -> None:
        self._camera_index = camera_index
        self._cap: cv2.VideoCapture | None = None
        self._last_anchor_color: str = "UNKNOWN"
        self._decoder = _build_decoder()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the camera and discard warm-up frames."""
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera at index {self._camera_index}"
            )
        for _ in range(_WARMUP_FRAMES):
            self._cap.read()

    def close(self) -> None:
        """Release camera resources."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # ------------------------------------------------------------------
    # Frame capture
    # ------------------------------------------------------------------

    def capture_frame(self) -> np.ndarray:
        """Read one raw frame from the camera."""
        if self._cap is None:
            raise RuntimeError("QRScanner not opened; call open() first")
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("Failed to read frame from camera")
        return frame

    # ------------------------------------------------------------------
    # Packet scanning
    # ------------------------------------------------------------------

    def scan_for_packet(
        self,
        last_anchor_color: str,
        opposing_box_size: int,
        opposing_border: int,
        output_size: tuple[int, int] = _DEFAULT_OUTPUT_SIZE,
    ) -> tuple[bytes | None, str]:
        """Full pipeline: capture → detect → transform → binarise → anchor → decode.

        Returns (packet_bytes_or_None, new_anchor_color).
        Skips QR decode when anchor colour is unchanged (same frame still displayed).
        """
        frame = self.capture_frame()

        corners = detect_screen_region(frame)
        if corners is not None:
            frame = perspective_transform(frame, corners, output_size)

        binary = binarize_otsu(frame)
        curr_color = read_anchor_color(binary, opposing_box_size, opposing_border)

        if not anchor_changed(last_anchor_color, curr_color):
            return None, curr_color

        packet_bytes = self._decode_qr(binary)
        return packet_bytes, curr_color

    def scan_blocking(self, timeout_ms: int) -> bytes | None:
        """Loop until a valid raw packet is returned or *timeout_ms* elapses.

        Does NOT validate packet content — returns raw bytes only.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        anchor_color = "UNKNOWN"
        while time.monotonic() < deadline:
            packet, anchor_color = self.scan_for_packet(
                anchor_color,
                opposing_box_size=10,  # default; caller should use scan_for_packet directly
                opposing_border=4,
            )
            if packet is not None:
                return packet
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decode_qr(self, binary_frame: np.ndarray) -> bytes | None:
        """Attempt QR decode with the available backend."""
        return self._decoder(binary_frame)

    def __enter__(self) -> "QRScanner":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Decoder backends (zxingcpp with pyzbar fallback)
# ---------------------------------------------------------------------------

def _build_decoder():
    """Return the best available QR decoding callable."""
    try:
        import zxingcpp  # noqa: F401  (zxing-cpp installs as zxingcpp)

        def _zxing_decode(frame: np.ndarray) -> bytes | None:
            import zxingcpp as zx

            results = zx.read_barcodes(frame)
            for r in results:
                raw = getattr(r, "raw_bytes", None)
                if raw:
                    return bytes(raw)
                text = getattr(r, "text", None)
                if text:
                    return text.encode("latin-1")
            return None

        return _zxing_decode

    except ImportError:
        pass

    try:
        from pyzbar import pyzbar  # noqa: F401

        def _pyzbar_decode(frame: np.ndarray) -> bytes | None:
            from pyzbar import pyzbar as pz

            results = pz.decode(frame)
            for r in results:
                return r.data
            return None

        return _pyzbar_decode

    except ImportError:
        pass

    raise ImportError(
        "No QR decoder available. Install zxingcpp or pyzbar."
    )
