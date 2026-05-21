"""Session cache — atomic frame writes, session.json, file assembly."""

from __future__ import annotations

import json
import os
import shutil
import threading
from typing import Any

from vlp.exceptions import CacheFullError, CacheWriteFailError


class SessionCache:
    """Manages the per-session directory structure under *cache_directory*."""

    def __init__(
        self,
        cache_directory: str,
        opposing_sid: str,
        max_cache_size_mb: int = 512,
    ) -> None:
        self._root = os.path.join(cache_directory, f"vlp_{opposing_sid}")
        self._frames_dir = os.path.join(self._root, "frames")
        self._session_json = os.path.join(self._root, "session.json")
        self._max_bytes = max_cache_size_mb * 1024 * 1024
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self, session_meta: dict) -> None:
        """Create directory structure, clean up stale tmp files, write session.json."""
        os.makedirs(self._frames_dir, exist_ok=True)

        # Remove any leftover .tmp files from a previous interrupted run
        for fname in os.listdir(self._frames_dir):
            if fname.endswith(".tmp"):
                _safe_remove(os.path.join(self._frames_dir, fname))

        self._write_json(session_meta)

    # ------------------------------------------------------------------
    # Frame I/O
    # ------------------------------------------------------------------

    def write_frame(self, seq_id: int, payload: bytes) -> None:
        """Atomically write *payload* for *seq_id*.

        Uses a .tmp rename strategy to prevent partial reads.
        """
        self._check_cache_size(len(payload))
        final_path = self._frame_path(seq_id)
        tmp_path = final_path + ".tmp"
        try:
            with open(tmp_path, "wb") as fh:
                fh.write(payload)
            os.replace(tmp_path, final_path)  # atomic on POSIX
        except OSError as exc:
            _safe_remove(tmp_path)
            raise CacheWriteFailError(
                f"Failed to write frame {seq_id}: {exc}"
            ) from exc

    def read_frame(self, seq_id: int) -> bytes:
        """Read and return the payload for *seq_id*."""
        with open(self._frame_path(seq_id), "rb") as fh:
            return fh.read()

    def frame_exists(self, seq_id: int) -> bool:
        return os.path.isfile(self._frame_path(seq_id))

    # ------------------------------------------------------------------
    # session.json
    # ------------------------------------------------------------------

    def update_session_json(self, updates: dict) -> None:
        """Thread-safe JSON patch of session.json."""
        with self._lock:
            current = self._read_json()
            current.update(updates)
            self._write_json(current)

    def read_session_json(self) -> dict:
        return self._read_json()

    # ------------------------------------------------------------------
    # Assembly & cleanup
    # ------------------------------------------------------------------

    def assemble_file(self, total_frames: int, output_path: str) -> None:
        """Concatenate frames 0..N-1 into *output_path*."""
        with open(output_path, "wb") as out:
            for seq_id in range(total_frames):
                out.write(self.read_frame(seq_id))

    def cleanup(self) -> None:
        """Delete the entire session directory tree."""
        if os.path.isdir(self._root):
            shutil.rmtree(self._root)

    # ------------------------------------------------------------------
    # Session resumption helper
    # ------------------------------------------------------------------

    @staticmethod
    def find_resumable_sessions(cache_directory: str) -> list[dict]:
        """Scan *cache_directory* for vlp_*/session.json with state != DONE."""
        results = []
        if not os.path.isdir(cache_directory):
            return results
        for entry in os.scandir(cache_directory):
            if not entry.is_dir() or not entry.name.startswith("vlp_"):
                continue
            sj = os.path.join(entry.path, "session.json")
            if not os.path.isfile(sj):
                continue
            try:
                with open(sj, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get("state") != "DONE":
                    meta["_session_dir"] = entry.path
                    results.append(meta)
            except (json.JSONDecodeError, OSError):
                continue
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _frame_path(self, seq_id: int) -> str:
        return os.path.join(self._frames_dir, f"{seq_id:010d}.frm")

    def _check_cache_size(self, additional_bytes: int) -> None:
        total = additional_bytes
        for dirpath, _, filenames in os.walk(self._root):
            for fname in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass
        if total > self._max_bytes:
            raise CacheFullError(
                f"Cache size {total} bytes exceeds limit {self._max_bytes} bytes"
            )

    def _write_json(self, data: dict) -> None:
        tmp = self._session_json + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self._session_json)
        except OSError as exc:
            _safe_remove(tmp)
            raise CacheWriteFailError(f"Failed to write session.json: {exc}") from exc

    def _read_json(self) -> dict:
        try:
            with open(self._session_json, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {}


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
