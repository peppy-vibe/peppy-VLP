"""Session orchestrator — ties all components together."""

from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vlp.bitmask import Bitmask
from vlp.cache import SessionCache
from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig
from vlp.constants import CtrlID, SessionState
from vlp.display import VLPDisplay
from vlp.handshake import HandshakeCoordinator
from vlp.packet import FileMetadata, encode_control_packet, max_raw_bytes_per_frame
from vlp.qr_renderer import render_control_frame
from vlp.qr_scanner import QRScanner
from vlp.receiver import ReceiverRole
from vlp.sender import SenderRole

if TYPE_CHECKING:
    pass


@dataclass
class SessionResult:
    sender_status: str
    receiver_status: str


class VLPSession:
    """Runs both Sender and Receiver roles concurrently for a full-duplex transfer."""

    def __init__(
        self,
        file_to_send: str,
        output_path: str,
        sender_cfg: SenderConfig,
        receiver_cfg: ReceiverConfig,
        timeout_cfg: TimeoutConfig | None = None,
        camera_index: int = 0,
    ) -> None:
        self._file_to_send = file_to_send
        self._output_path = output_path
        self._sender_cfg = sender_cfg
        self._receiver_cfg = receiver_cfg
        self._timeout_cfg = timeout_cfg or TimeoutConfig()
        self._camera_index = camera_index

        self._abort_event = threading.Event()
        self._local_sid: int = 0
        self._cache: SessionCache | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> SessionResult:
        """Run the full session synchronously.

        On macOS, NSWindow must live on the main thread.  The Tkinter mainloop
        is therefore run here (blocking the caller's thread), while all VLP
        protocol logic executes in a background thread.
        """
        display = VLPDisplay(self._receiver_cfg.feedback_position)
        display.start()  # creates Tk window — must be called from main thread

        _outcome: list[SessionResult | BaseException] = []

        def _protocol() -> None:
            try:
                _outcome.append(self._run_protocol(display))
            except BaseException as exc:  # noqa: BLE001
                _outcome.append(exc)
            finally:
                display.stop()  # queues root.quit() → unblocks run_mainloop()

        protocol_thread = threading.Thread(
            target=_protocol, daemon=True, name="vlp-protocol"
        )
        protocol_thread.start()

        display.run_mainloop()  # blocks main thread until display.stop() called
        protocol_thread.join(timeout=5)

        result = _outcome[0] if _outcome else SessionResult("UNKNOWN", "UNKNOWN")
        if isinstance(result, BaseException):
            raise result
        return result

    def _run_protocol(self, display: VLPDisplay) -> SessionResult:
        """All VLP protocol logic — runs in a background thread."""
        # 1. File metadata
        file_meta = self._compute_file_meta()

        # 2. Session ID
        self._local_sid = struct.unpack(">Q", os.urandom(8))[0]

        # 4. Scanner
        scanner = QRScanner(camera_index=self._camera_index)
        scanner.open()

        try:
            # 5. Handshake
            hs = HandshakeCoordinator(
                local_sid=self._local_sid,
                file_meta=file_meta,
                sender_cfg=self._sender_cfg,
                receiver_cfg=self._receiver_cfg,
                display=display,
                scanner=scanner,
                timeout_cfg=self._timeout_cfg,
            )
            result = hs.run()

            # 6. Cache + Bitmask
            opposing_sid_hex = format(result.opposing_sid, "016X")
            cache = SessionCache(
                cache_directory=self._receiver_cfg.cache_directory,
                opposing_sid=opposing_sid_hex,
                max_cache_size_mb=self._receiver_cfg.max_cache_size_mb,
            )
            cache.initialize(
                {
                    "vlp_version": "1.0",
                    "opposing_sid": opposing_sid_hex,
                    "local_sid": format(self._local_sid, "016X"),
                    "file": {
                        "name": result.opposing_file_meta.name,
                        "size_bytes": result.opposing_file_meta.size_bytes,
                        "sha256": result.opposing_file_meta.sha256,
                        "total_frames": result.opposing_file_meta.total_frames,
                    },
                    "state": SessionState.STREAMING,
                    "received_frame_count": 0,
                    "bitmask_hex": "",
                }
            )
            self._cache = cache
            bitmask = Bitmask(result.opposing_file_meta.total_frames)

            # 7. Launch roles
            sender = SenderRole(
                file_path=self._file_to_send,
                file_meta=file_meta,
                sid=self._local_sid,
                sender_cfg=self._sender_cfg,
                receiver_cfg=self._receiver_cfg,
                display=display,
                scanner=scanner,
                timeout_cfg=self._timeout_cfg,
                abort_event=self._abort_event,
            )
            receiver = ReceiverRole(
                opposing_sid=result.opposing_sid,
                opposing_file_meta=result.opposing_file_meta,
                opposing_sender_cfg=result.opposing_sender_cfg,
                receiver_cfg=self._receiver_cfg,
                output_path=self._output_path,
                display=display,
                scanner=scanner,
                cache=cache,
                bitmask=bitmask,
                timeout_cfg=self._timeout_cfg,
                abort_event=self._abort_event,
            )

            sender_thread = threading.Thread(
                target=sender.run, daemon=True, name="vlp-sender"
            )
            receiver_thread = threading.Thread(
                target=receiver.run, daemon=True, name="vlp-receiver"
            )

            sender_thread.start()
            receiver_thread.start()

            sender_thread.join()
            receiver_thread.join()

            return SessionResult(
                sender_status=sender.status,
                receiver_status=receiver.status,
            )

        except Exception as exc:
            code = getattr(exc, "error_code", 0xFF)
            self.abort(code)
            raise

        finally:
            scanner.close()

    def abort(self, error_code: int) -> None:
        """Signal all threads to stop and display SESSION_ABORT."""
        self._abort_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_file_meta(self) -> FileMetadata:
        size = os.path.getsize(self._file_to_send)
        sha256 = _sha256_file(self._file_to_send)
        chunk_size = max_raw_bytes_per_frame(
            self._sender_cfg.stream_qr_version,
            self._sender_cfg.stream_qr_error_correction,
            self._sender_cfg.payload_encoding,
        )
        total_frames = math.ceil(size / chunk_size)
        return FileMetadata(
            name=os.path.basename(self._file_to_send),
            size_bytes=size,
            sha256=sha256,
            total_frames=total_frames,
        )


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()
