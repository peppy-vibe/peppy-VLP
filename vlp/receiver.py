"""Receiver role: capture loop, feedback QR, file assembly."""

from __future__ import annotations

import hashlib
import logging
import struct
import threading
import time
from typing import TYPE_CHECKING

from vlp.bitmask import Bitmask
from vlp.constants import CtrlID
from vlp.exceptions import HashMismatchError, RemoteAbortError, TotalFramesMismatchError
from vlp.packet import (
    FileMetadata,
    decode_control_packet,
    decode_data_packet,
    encode_control_packet,
)
from vlp.qr_renderer import render_control_frame

if TYPE_CHECKING:
    from vlp.cache import SessionCache
    from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
    from vlp.display import VLPDisplay
    from vlp.qr_scanner import QRScanner

log = logging.getLogger("vlp.receiver")


class ReceiverRole:
    """Drives the Receiver side of a VLP session."""

    def __init__(
        self,
        opposing_sid: int,
        opposing_file_meta: FileMetadata,
        opposing_sender_cfg: "SenderConfig",
        receiver_cfg: "ReceiverConfig",
        output_path: str,
        display: "VLPDisplay",
        scanner: "QRScanner",
        cache: "SessionCache",
        bitmask: Bitmask,
        timeout_cfg: "TimeoutConfig",
        abort_event: threading.Event,
    ) -> None:
        self._opposing_sid = opposing_sid
        self._file_meta = opposing_file_meta
        self._sender_cfg = opposing_sender_cfg
        self._receiver_cfg = receiver_cfg
        self._output_path = output_path
        self._display = display
        self._scanner = scanner
        self._cache = cache
        self._bitmask = bitmask
        self._timeout_cfg = timeout_cfg
        self._abort = abort_event

        self._bitmask_lock = threading.Lock()
        self._completion_flag = threading.Event()
        self._capture_error: Exception | None = None  # propagated from capture thread
        self.status: str = "IDLE"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.status = "STREAMING"
        capture_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="vlp-capture",
        )
        feedback_thread = threading.Thread(
            target=self._feedback_loop,
            daemon=True,
            name="vlp-feedback",
        )

        capture_thread.start()
        feedback_thread.start()

        capture_thread.join()
        feedback_thread.join(timeout=2)

        # Re-raise any exception captured from the capture thread
        if self._capture_error is not None:
            raise self._capture_error

        if self._abort.is_set():
            return

        if self._completion_flag.is_set():
            self._assembly_phase()
        self.status = "DONE"

    # ------------------------------------------------------------------
    # Capture loop
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        anchor = "UNKNOWN"
        while not self._abort.is_set():
            try:
                raw, anchor = self._scanner.scan_for_packet(
                    anchor,
                    opposing_box_size=self._sender_cfg.stream_qr_box_size,
                    opposing_border=self._sender_cfg.stream_qr_border,
                )
            except Exception:
                time.sleep(0.01)
                continue

            if raw is None:
                time.sleep(0.005)
                continue

            # --- Try as data packet first (CRC32 proves authenticity) ---
            try:
                pkt = decode_data_packet(raw, self._sender_cfg.payload_encoding)

                # Validate SID
                if pkt.sid != self._opposing_sid:
                    continue

                # Validate total_frames consistency
                if pkt.total_frames != self._file_meta.total_frames:
                    self._abort.set()
                    self._capture_error = TotalFramesMismatchError(
                        f"total_frames mismatch: expected {self._file_meta.total_frames}, "
                        f"got {pkt.total_frames}"
                    )
                    return  # exit thread; run() will re-raise _capture_error

                # Store frame
                seq_id = pkt.seq_id
                if 0 <= seq_id < self._file_meta.total_frames:
                    self._cache.write_frame(seq_id, pkt.payload)
                    with self._bitmask_lock:
                        self._bitmask.mark_received(seq_id)
                    log.debug(
                        "Frame %d/%d received",
                        seq_id + 1, self._file_meta.total_frames,
                    )

                # Auto-complete when all frames received
                with self._bitmask_lock:
                    if self._bitmask.all_received():
                        self._completion_flag.set()
                        break
                continue

            except TotalFramesMismatchError:
                return  # _capture_error already set above
            except Exception:
                pass  # CRC fail or malformed → fall through to control check

            # --- Try as control packet ---
            try:
                ctrl = decode_control_packet(raw)
                if ctrl.ctrl_id == CtrlID.SESSION_COMPLETE:
                    self._completion_flag.set()
                    break
                if ctrl.ctrl_id == CtrlID.SESSION_ABORT:
                    raise RemoteAbortError("Remote endpoint sent SESSION_ABORT")
            except RemoteAbortError:
                self._abort.set()
                return
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Feedback loop
    # ------------------------------------------------------------------

    def _feedback_loop(self) -> None:
        """Periodically refresh the feedback STATUS QR with the current bitmask."""
        local_sid = self._opposing_sid  # use opposing SID in control packet per spec
        while not self._abort.is_set() and not self._completion_flag.is_set():
            with self._bitmask_lock:
                bitmask_bytes = self._bitmask.to_bytes()
                total = self._file_meta.total_frames

            payload = struct.pack(">QI", local_sid, total) + bitmask_bytes
            pkt = encode_control_packet(local_sid, CtrlID.STATUS, payload)
            img = render_control_frame(pkt, self._receiver_cfg)
            self._display.show_feedback_qr(img)

            time.sleep(self._receiver_cfg.feedback_interval_ms / 1000.0)

        self._display.clear_feedback_qr()

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def _assembly_phase(self) -> None:
        self.status = "ASSEMBLING"
        self._cache.assemble_file(self._file_meta.total_frames, self._output_path)

        # SHA-256 verification
        sha256 = _sha256_file(self._output_path)
        if sha256 != self._file_meta.sha256:
            raise HashMismatchError(
                f"SHA-256 mismatch: expected {self._file_meta.sha256}, got {sha256}"
            )

        # Display SESSION_ACK
        ack_pkt = encode_control_packet(self._opposing_sid, CtrlID.SESSION_ACK)
        ack_img = render_control_frame(ack_pkt, self._receiver_cfg)
        self._display.show_feedback_qr(ack_img)

        # Hold ACK for a few seconds so the Sender can read it
        time.sleep(3.0)
        self._display.clear_feedback_qr()
        self._cache.cleanup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()
