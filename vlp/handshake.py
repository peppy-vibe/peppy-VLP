"""Phase 1: concurrent READY/ACK handshake coordination."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vlp.constants import CtrlID, VLP_VERSION
from vlp.exceptions import (
    ConfigIncompatibleError,
    HandshakeTimeoutError,
    VersionMismatchError,
)
from vlp.packet import (
    FileMetadata,
    decode_control_packet,
    decode_handshake_json,
    encode_handshake_ack,
    encode_handshake_ready,
)
from vlp.qr_renderer import render_control_frame

if TYPE_CHECKING:
    from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
    from vlp.display import VLPDisplay
    from vlp.qr_scanner import QRScanner


@dataclass
class HandshakeResult:
    opposing_sid: int
    opposing_file_meta: FileMetadata
    opposing_sender_cfg: "SenderConfig"
    opposing_receiver_cfg: dict  # raw dict — remote cache_dir not available locally


class HandshakeCoordinator:
    """Runs the Phase 1 handshake concurrently (Sender + Receiver roles).

    Thread A: continuously displays a READY QR.
    Thread B: scans for the opposing READY QR; on success, switches to ACK QR.
    Main:     waits until both READY sent and valid ACK received that echoes local SID.
    """

    def __init__(
        self,
        local_sid: int,
        file_meta: FileMetadata,
        sender_cfg: "SenderConfig",
        receiver_cfg: "ReceiverConfig",
        display: "VLPDisplay",
        scanner: "QRScanner",
        timeout_cfg: "TimeoutConfig",
    ) -> None:
        self._local_sid = local_sid
        self._file_meta = file_meta
        self._sender_cfg = sender_cfg
        self._receiver_cfg = receiver_cfg
        self._display = display
        self._scanner = scanner
        self._timeout_cfg = timeout_cfg

        self._result: HandshakeResult | None = None
        self._error: Exception | None = None
        self._stop = threading.Event()
        self._ack_ready = threading.Event()  # set once we have opposing READY
        self._confirmed = threading.Event()  # set once our ACK is echoed back

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> HandshakeResult:
        """Block until handshake completes or timeout.  Returns HandshakeResult."""
        ready_pkt = encode_handshake_ready(
            self._local_sid,
            self._file_meta,
            self._sender_cfg,
            self._receiver_cfg,
        )

        sender_thread = threading.Thread(
            target=self._sender_loop,
            args=(ready_pkt,),
            daemon=True,
            name="vlp-hs-sender",
        )
        receiver_thread = threading.Thread(
            target=self._receiver_loop,
            daemon=True,
            name="vlp-hs-receiver",
        )

        sender_thread.start()
        receiver_thread.start()

        deadline = time.monotonic() + self._timeout_cfg.handshake_timeout_ms / 1000.0
        while time.monotonic() < deadline:
            if self._error is not None:
                self._stop.set()
                raise self._error
            if self._confirmed.is_set() and self._result is not None:
                self._stop.set()
                return self._result
            time.sleep(0.05)

        self._stop.set()
        raise HandshakeTimeoutError("Handshake did not complete within timeout")

    # ------------------------------------------------------------------
    # Thread A: display READY, then ACK
    # ------------------------------------------------------------------

    def _sender_loop(self, ready_pkt: bytes) -> None:
        from vlp.qr_renderer import render_control_frame as _render

        ready_img = _render(ready_pkt, self._receiver_cfg)

        while not self._stop.is_set():
            if self._ack_ready.is_set():
                break
            self._display.show_main_qr(ready_img)
            time.sleep(0.2)

        # Switch to ACK QR
        while not self._stop.is_set() and not self._confirmed.is_set():
            if self._result is not None:
                ack_pkt = encode_handshake_ack(
                    self._local_sid,
                    self._result.opposing_sid,
                    self._result.opposing_file_meta.total_frames,
                )
                ack_img = _render(ack_pkt, self._receiver_cfg)
                self._display.show_main_qr(ack_img)
            time.sleep(0.2)

    # ------------------------------------------------------------------
    # Thread B: scan for opposing READY + our echoed ACK
    # ------------------------------------------------------------------

    def _receiver_loop(self) -> None:
        opposing_sid: int | None = None
        anchor = "UNKNOWN"

        deadline = time.monotonic() + self._timeout_cfg.handshake_timeout_ms / 1000.0

        while not self._stop.is_set() and time.monotonic() < deadline:
            try:
                raw, anchor = self._scanner.scan_for_packet(
                    anchor,
                    opposing_box_size=self._sender_cfg.stream_qr_box_size,
                    opposing_border=self._sender_cfg.stream_qr_border,
                )
            except Exception:
                time.sleep(0.05)
                continue

            if raw is None:
                time.sleep(0.01)
                continue

            try:
                ctrl = decode_control_packet(raw)
            except Exception:
                continue

            if ctrl.ctrl_id == CtrlID.HANDSHAKE_READY and opposing_sid is None:
                try:
                    result = self._process_ready(ctrl)
                    self._result = result
                    opposing_sid = result.opposing_sid
                    self._ack_ready.set()
                except Exception as exc:
                    self._error = exc
                    return

            elif ctrl.ctrl_id == CtrlID.HANDSHAKE_ACK and opposing_sid is not None:
                try:
                    body = decode_handshake_json(ctrl.payload)
                    echoed = int(body.get("opposing_sid", "0"), 16)
                    if echoed == self._local_sid:
                        self._confirmed.set()
                        return
                except Exception:
                    pass

            time.sleep(0.01)

    # ------------------------------------------------------------------
    # Processing helpers
    # ------------------------------------------------------------------

    def _process_ready(self, ctrl) -> HandshakeResult:
        from vlp.config import SenderConfig as SC

        body = decode_handshake_json(ctrl.payload)

        # Version check
        if body.get("vlp_version") != VLP_VERSION:
            raise VersionMismatchError(
                f"Opposing VLP version {body.get('vlp_version')!r} "
                f"!= {VLP_VERSION!r}"
            )

        opposing_sid = int(body["sid"], 16)

        fm = body["file"]
        file_meta = FileMetadata(
            name=fm["name"],
            size_bytes=fm["size_bytes"],
            sha256=fm["sha256"],
            total_frames=fm["total_frames"],
        )

        sender_d = body.get("sender_config", {})
        try:
            opposing_sender = SC.from_dict(sender_d)
        except (TypeError, ValueError) as exc:
            raise ConfigIncompatibleError(f"Opposing sender config invalid: {exc}") from exc

        return HandshakeResult(
            opposing_sid=opposing_sid,
            opposing_file_meta=file_meta,
            opposing_sender_cfg=opposing_sender,
            opposing_receiver_cfg=body.get("receiver_config", {}),
        )
