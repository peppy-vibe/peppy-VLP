"""Bitmask for tracking received/missing frame sequence IDs."""

from __future__ import annotations

import math


class Bitmask:
    """Packed bit array, MSB-first, tracking received frames.

    Bit value 1 = received / OK.
    Bit value 0 = missing / corrupt.
    Padding bits in the last byte are set to 1 on serialisation to avoid
    spurious retransmission requests.
    """

    def __init__(self, total_frames: int) -> None:
        if total_frames <= 0:
            raise ValueError("total_frames must be positive")
        self._total_frames = total_frames
        self._bits = bytearray(math.ceil(total_frames / 8))

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def mark_received(self, seq_id: int) -> None:
        self._validate(seq_id)
        byte_idx, bit_pos = divmod(seq_id, 8)
        self._bits[byte_idx] |= 0x80 >> bit_pos

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_received(self, seq_id: int) -> bool:
        self._validate(seq_id)
        byte_idx, bit_pos = divmod(seq_id, 8)
        return bool(self._bits[byte_idx] & (0x80 >> bit_pos))

    def all_received(self) -> bool:
        return not self.missing_seq_ids()

    def missing_seq_ids(self) -> list[int]:
        return [i for i in range(self._total_frames) if not self.is_received(i)]

    @property
    def total_frames(self) -> int:
        return self._total_frames

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialise with padding bits set to 1."""
        result = bytearray(self._bits)
        remainder = self._total_frames % 8
        if remainder:
            # set trailing (8 - remainder) bits to 1
            mask = (1 << (8 - remainder)) - 1
            result[-1] |= mask
        return bytes(result)

    @classmethod
    def from_bytes(cls, data: bytes, total_frames: int) -> "Bitmask":
        bm = cls(total_frames)
        for i in range(total_frames):
            byte_idx, bit_pos = divmod(i, 8)
            if byte_idx < len(data) and data[byte_idx] & (0x80 >> bit_pos):
                bm.mark_received(i)
        return bm

    def to_hex(self) -> str:
        return self.to_bytes().hex().upper()

    @classmethod
    def from_hex(cls, hex_str: str, total_frames: int) -> "Bitmask":
        return cls.from_bytes(bytes.fromhex(hex_str), total_frames)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _validate(self, seq_id: int) -> None:
        if not (0 <= seq_id < self._total_frames):
            raise IndexError(
                f"seq_id {seq_id} out of range [0, {self._total_frames})"
            )

    def __repr__(self) -> str:  # pragma: no cover
        received = self._total_frames - len(self.missing_seq_ids())
        return f"Bitmask(total={self._total_frames}, received={received})"
