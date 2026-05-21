"""Sender role: streaming, recovery, and session completion."""

from __future__ import annotations

import logging
import math
import os
import struct
import time
import threading
from typing import TYPE_CHECKING

from PIL import Image

from vlp.bitmask import Bitmask
from vlp.constants import CtrlID
from vlp.exceptions import (
    ACKTimeoutError,
    FeedbackTimeoutError,
    MaxRecoveryExceededError,
)
from vlp.packet import (
    FileMetadata,
    decode_control_packet,
    encode_control_packet,
    encode_data_packet,
    encode_payload,
    max_raw_bytes_per_frame,
)
from vlp.qr_renderer import render_control_frame, render_data_frame

if TYPE_CHECKING:
    from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
    from vlp.display import VLPDisplay
    from vlp.qr_scanner import QRScanner

log = logging.getLogger("vlp.sender")


class SenderRole:
    """Drives the Sender side of a VLP session."""

    def __init__(
        self,
        file_path: str,
        file_meta: FileMetadata,
        sid: int,
        sender_cfg: "SenderConfig",
        receiver_cfg: "ReceiverConfig",
        display: "VLPDisplay",
        scanner: "QRScanner",
        timeout_cfg: "TimeoutConfig",
        abort_event: threading.Event,
    ) -> None:
        self._file_path = file_path
        self._file_meta = file_meta
        self._sid = sid
        self._cfg = sender_cfg
        self._receiver_cfg = receiver_cfg
        self._display = display
        self._scanner = scanner
        self._timeout_cfg = timeout_cfg
        self._abort = abort_event
        self._total_frames = file_meta.total_frames
        self._chunk_size = max_raw_bytes_per_frame(
            sender_cfg.stream_qr_version,
            sender_cfg.stream_qr_error_correction,
            sender_cfg.payload_encoding,
        )
        self.status: str = "IDLE"
        self._fh = None  # file handle opened once in run() for all render operations

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        with open(self._file_path, "rb") as fh:
            self._fh = fh
            self.status = "STREAMING"
            log.info("Streaming phase: %d frames total", self._total_frames)
            self._streaming_phase()
            if self._abort.is_set():
                return

            self.status = "RECOVERING"
            log.info("Recovery phase")
            self._recovering_phase()
            if self._abort.is_set():
                return

            self.status = "COMPLETING"
            log.info("Completion phase")
            self._completing_phase()
            if self.status != "DONE_UNCONFIRMED":
                self.status = "DONE"
        self._fh = None

    # ------------------------------------------------------------------
    # Phase 2: streaming
    # ------------------------------------------------------------------

    def _streaming_phase(self) -> None:
        for seq_id in range(self._total_frames):
            if self._abort.is_set():
                return
            img = self._render_frame(seq_id)
            self._display.show_main_qr(img)
            log.debug("Sent frame %d/%d", seq_id + 1, self._total_frames)

            if self._cfg.streaming_mode == "PACED":
                time.sleep(self._cfg.frame_interval_ms / 1000.0)
            else:
                self._wait_for_frame_ack(seq_id)

    def _wait_for_frame_ack(self, seq_id: int) -> None:
        """Acknowledged Mode: wait for FRAME_ACK(seq_id) with retry logic."""
        retries = 0
        while retries <= self._cfg.max_ack_retries:
            if self._abort.is_set():
                return
            raw = self._scanner.scan_blocking(
                self._cfg.ack_timeout_ms,
                opposing_box_size=self._receiver_cfg.control_qr_box_size,
                opposing_border=self._receiver_cfg.control_qr_border,
            )
            if raw is not None:
                try:
                    ctrl = decode_control_packet(raw)
                    if ctrl.ctrl_id == CtrlID.FRAME_ACK and len(ctrl.payload) >= 4:
                        acked = struct.unpack(">I", ctrl.payload[:4])[0]
                        if acked == seq_id:
                            return
                except Exception:
                    pass
            retries += 1

        raise ACKTimeoutError(
            f"No FRAME_ACK for seq_id={seq_id} after {self._cfg.max_ack_retries} retries"
        )

    # ------------------------------------------------------------------
    # Phase 3: recovery
    # ------------------------------------------------------------------

    def _recovering_phase(self) -> None:
        for round_num in range(self._timeout_cfg.max_recovery_rounds):
            if self._abort.is_set():
                return

            # Inner retry loop: scan until a STATUS packet is received or this
            # round's time budget expires.  Non-STATUS packets and decode errors
            # retry within the same round rather than burning a recovery round.
            bitmask: Bitmask | None = None
            deadline = (
                time.monotonic() + self._timeout_cfg.feedback_scan_timeout_ms / 1000.0
            )
            sub_timeout_ms = min(500, self._timeout_cfg.feedback_scan_timeout_ms)
            while time.monotonic() < deadline:
                if self._abort.is_set():
                    return
                raw = self._scanner.scan_blocking(
                    sub_timeout_ms,
                    opposing_box_size=self._receiver_cfg.control_qr_box_size,
                    opposing_border=self._receiver_cfg.control_qr_border,
                )
                if raw is None:
                    continue
                try:
                    ctrl = decode_control_packet(raw)
                    if ctrl.ctrl_id == CtrlID.STATUS:
                        bitmask = self._parse_status_payload(ctrl.payload)
                        break
                except Exception:
                    continue

            if bitmask is None:
                raise FeedbackTimeoutError(
                    f"Round {round_num + 1}: no STATUS QR received within "
                    f"{self._timeout_cfg.feedback_scan_timeout_ms} ms"
                )

            if bitmask.all_received():
                log.info("Recovery complete after %d round(s)", round_num + 1)
                return  # all frames confirmed → advance to completion

            missing = bitmask.missing_seq_ids()
            log.info(
                "Recovery round %d: retransmitting %d frame(s)",
                round_num + 1, len(missing),
            )
            for seq_id in missing:
                if self._abort.is_set():
                    return
                img = self._render_frame(seq_id)
                self._display.show_main_qr(img)
                time.sleep(self._cfg.frame_interval_ms / 1000.0)

        raise MaxRecoveryExceededError(
            f"Exceeded {self._timeout_cfg.max_recovery_rounds} recovery rounds"
        )

    def _parse_status_payload(self, payload: bytes) -> Bitmask:
        """Decode the STATUS control payload → Bitmask."""
        if len(payload) < 12:  # SID(8) + TotalFrames(4)
            raise ValueError("STATUS payload too short")
        _sid, total_frames = struct.unpack_from(">QI", payload, 0)
        bitmask_bytes = payload[12:]
        return Bitmask.from_bytes(bitmask_bytes, total_frames)

    # ------------------------------------------------------------------
    # Phase 4: completion
    # ------------------------------------------------------------------

    def _completing_phase(self) -> None:
        complete_pkt = encode_control_packet(self._sid, CtrlID.SESSION_COMPLETE)
        complete_img = render_control_frame(complete_pkt, self._receiver_cfg)

        hold_secs = 3 * self._cfg.frame_interval_ms / 1000.0

        for attempt in range(3):
            if self._abort.is_set():
                return
            self._display.show_main_qr(complete_img)
            time.sleep(hold_secs)

            raw = self._scanner.scan_blocking(self._timeout_cfg.completion_timeout_ms)
            if raw is not None:
                try:
                    ctrl = decode_control_packet(raw)
                    if ctrl.ctrl_id == CtrlID.SESSION_ACK:
                        return  # confirmed
                except Exception:
                    pass

        # No ACK after retries → DONE_UNCONFIRMED (non-fatal)
        self.status = "DONE_UNCONFIRMED"

    # ------------------------------------------------------------------
    # Frame rendering
    # ------------------------------------------------------------------

    def _render_frame(self, seq_id: int) -> Image.Image:
        """Render one data frame.

        Reads from ``self._fh`` when called from within ``run()`` (the normal
        path, opened once for the full transfer).  Falls back to opening the
        file inline if ``_fh`` is None (e.g., direct test invocations).
        """
        offset = seq_id * self._chunk_size
        if self._fh is not None:
            self._fh.seek(offset)
            raw_chunk = self._fh.read(self._chunk_size)
        else:
            with open(self._file_path, "rb") as fh:
                fh.seek(offset)
                raw_chunk = fh.read(self._chunk_size)
        encoded = encode_payload(raw_chunk, self._cfg.payload_encoding)
        pkt = encode_data_packet(self._sid, seq_id, self._total_frames, encoded)
        return render_data_frame(pkt, seq_id, self._cfg)
