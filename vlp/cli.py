"""CLI entry point for VLP.

Usage:
    python -m vlp send <file_path> [options]
    python -m vlp receive <output_path> [options]
    python -m vlp transfer <file_path> <output_path> [options]
"""

from __future__ import annotations

import argparse
import os
import sys


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--camera-index", type=int, default=0, metavar="INT",
                   help="Camera device index (default: 0)")
    p.add_argument("--streaming-mode", choices=["PACED", "ACKNOWLEDGED"],
                   default="PACED", help="Streaming mode (default: PACED)")
    p.add_argument("--frame-interval-ms", type=int, default=150, metavar="INT",
                   help="Frame interval in ms for PACED mode (default: 150)")
    p.add_argument("--qr-version", type=int, default=10, metavar="INT",
                   help="QR version 1-40 (default: 10)")
    p.add_argument("--qr-ec", choices=["M", "Q", "H"], default="M",
                   help="QR error correction level (default: M)")
    p.add_argument("--feedback-position",
                   choices=["BOTTOM_RIGHT", "BOTTOM_LEFT", "TOP_RIGHT", "TOP_LEFT"],
                   default="BOTTOM_RIGHT",
                   help="Feedback QR corner position (default: BOTTOM_RIGHT)")
    p.add_argument("--max-cache-mb", type=int, default=512, metavar="INT",
                   help="Max cache size in MB (default: 512)")


def _add_cache_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cache-dir", required=True, metavar="PATH",
                   help="Directory to store temporary session cache")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vlp",
        description="Visual Link Protocol — optical file transfer via QR codes",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- send ---
    send_p = sub.add_parser("send", help="Send a file to the opposing device")
    send_p.add_argument("file_path", help="Path to the file to send")
    _add_common_args(send_p)

    # --- receive ---
    recv_p = sub.add_parser("receive", help="Receive a file from the opposing device")
    recv_p.add_argument("output_path", help="Path for the received output file")
    _add_cache_arg(recv_p)
    _add_common_args(recv_p)
    recv_p.add_argument("--resume", action="store_true",
                        help="Attempt to resume an interrupted session")

    # --- transfer (primary, full-duplex) ---
    xfr_p = sub.add_parser("transfer",
                            help="Full-duplex transfer: send and receive simultaneously")
    xfr_p.add_argument("file_path", help="Path to the file to send")
    xfr_p.add_argument("output_path", help="Path for the received output file")
    _add_cache_arg(xfr_p)
    _add_common_args(xfr_p)
    xfr_p.add_argument("--resume", action="store_true",
                        help="Attempt to resume an interrupted session")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from vlp.config import ReceiverConfig, SenderConfig, TimeoutConfig

    sender_cfg = SenderConfig(
        stream_qr_version=args.qr_version,
        stream_qr_error_correction=args.qr_ec,
        streaming_mode=args.streaming_mode,
        frame_interval_ms=args.frame_interval_ms,
    )

    if args.command in ("receive", "transfer"):
        cache_dir = args.cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        receiver_cfg = ReceiverConfig(
            feedback_position=args.feedback_position,
            max_cache_size_mb=args.max_cache_mb,
            cache_directory=cache_dir,
        )
    else:
        # send-only: still need a ReceiverConfig for handshake QR rendering
        # Use a temp dir as placeholder
        import tempfile
        _tmp = tempfile.mkdtemp(prefix="vlp_cache_")
        receiver_cfg = ReceiverConfig(
            feedback_position=args.feedback_position,
            cache_directory=_tmp,
        )

    timeout_cfg = TimeoutConfig()

    if args.command == "send":
        _run_send(args.file_path, sender_cfg, receiver_cfg, timeout_cfg, args)
    elif args.command == "receive":
        _run_receive(args.output_path, sender_cfg, receiver_cfg, timeout_cfg, args)
    elif args.command == "transfer":
        _run_transfer(
            args.file_path, args.output_path,
            sender_cfg, receiver_cfg, timeout_cfg, args,
        )
    return 0


def _run_send(file_path, sender_cfg, receiver_cfg, timeout_cfg, args):
    from vlp.session import VLPSession

    _check_file(file_path)
    session = VLPSession(
        file_to_send=file_path,
        output_path=os.devnull,
        sender_cfg=sender_cfg,
        receiver_cfg=receiver_cfg,
        timeout_cfg=timeout_cfg,
        camera_index=args.camera_index,
    )
    result = session.start()
    print(f"Sender: {result.sender_status}")


def _run_receive(output_path, sender_cfg, receiver_cfg, timeout_cfg, args):
    from vlp.cache import SessionCache
    from vlp.session import VLPSession

    if getattr(args, "resume", False):
        sessions = SessionCache.find_resumable_sessions(receiver_cfg.cache_directory)
        if sessions:
            print(f"Found {len(sessions)} resumable session(s).")
            for s in sessions:
                print(f"  opposing_sid={s.get('opposing_sid')} state={s.get('state')}")

    # Placeholder file_to_send for receive-only mode
    import tempfile
    _dummy = tempfile.NamedTemporaryFile(delete=False, suffix=".vlp_dummy")
    _dummy.close()
    try:
        session = VLPSession(
            file_to_send=_dummy.name,
            output_path=output_path,
            sender_cfg=sender_cfg,
            receiver_cfg=receiver_cfg,
            timeout_cfg=timeout_cfg,
            camera_index=args.camera_index,
        )
        result = session.start()
        print(f"Receiver: {result.receiver_status}")
    finally:
        os.unlink(_dummy.name)


def _run_transfer(file_path, output_path, sender_cfg, receiver_cfg, timeout_cfg, args):
    from vlp.session import VLPSession

    _check_file(file_path)
    session = VLPSession(
        file_to_send=file_path,
        output_path=output_path,
        sender_cfg=sender_cfg,
        receiver_cfg=receiver_cfg,
        timeout_cfg=timeout_cfg,
        camera_index=args.camera_index,
    )
    result = session.start()
    print(f"Sender: {result.sender_status}  |  Receiver: {result.receiver_status}")


def _check_file(path: str) -> None:
    if not os.path.isfile(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
