"""Tests for vlp.bitmask."""

import pytest

from vlp.bitmask import Bitmask


def test_initial_all_missing():
    bm = Bitmask(5)
    assert bm.missing_seq_ids() == [0, 1, 2, 3, 4]
    assert not bm.all_received()


def test_mark_and_check():
    bm = Bitmask(5)
    bm.mark_received(2)
    assert bm.is_received(2)
    assert not bm.is_received(1)
    assert bm.missing_seq_ids() == [0, 1, 3, 4]


def test_all_received():
    bm = Bitmask(3)
    for i in range(3):
        bm.mark_received(i)
    assert bm.all_received()
    assert bm.missing_seq_ids() == []


def test_out_of_range():
    bm = Bitmask(4)
    with pytest.raises(IndexError):
        bm.mark_received(4)
    with pytest.raises(IndexError):
        bm.is_received(-1)


def test_to_bytes_padding_bits_set():
    """Padding bits in last byte must be 1 (5 frames → 3 padding bits)."""
    bm = Bitmask(5)
    for i in range(5):
        bm.mark_received(i)
    data = bm.to_bytes()
    # Only 1 byte needed; all 5 data bits + 3 padding bits = 0xFF
    assert data == bytes([0xFF])


def test_padding_bits_not_treated_as_missing():
    bm = Bitmask(5)
    for i in range(5):
        bm.mark_received(i)
    data = bm.to_bytes()
    bm2 = Bitmask.from_bytes(data, 5)
    assert bm2.all_received()


def test_bytes_roundtrip():
    bm = Bitmask(10)
    bm.mark_received(0)
    bm.mark_received(3)
    bm.mark_received(9)
    data = bm.to_bytes()
    bm2 = Bitmask.from_bytes(data, 10)
    assert bm2.is_received(0)
    assert bm2.is_received(3)
    assert bm2.is_received(9)
    assert not bm2.is_received(1)


def test_hex_roundtrip():
    bm = Bitmask(8)
    for i in [0, 2, 4, 6]:
        bm.mark_received(i)
    hex_str = bm.to_hex()
    bm2 = Bitmask.from_hex(hex_str, 8)
    for i in [0, 2, 4, 6]:
        assert bm2.is_received(i)
    for i in [1, 3, 5, 7]:
        assert not bm2.is_received(i)


def test_example_from_spec():
    """Spec §9.2 example: 5 frames, frames 1 and 3 missing → byte = 0b10101111."""
    bm = Bitmask(5)
    for i in [0, 2, 4]:
        bm.mark_received(i)
    data = bm.to_bytes()
    # bits: F0=1 F1=0 F2=1 F3=0 F4=1 pad=1 pad=1 pad=1 → 0b10101111 = 0xAF
    assert data[0] == 0b10101111
