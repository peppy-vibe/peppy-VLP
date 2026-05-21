"""Tests for vlp.image_processor."""

import numpy as np
import pytest

from vlp.image_processor import (
    anchor_changed,
    binarize_otsu,
    read_anchor_color,
)


def _make_frame(h=200, w=200, color=255):
    return np.full((h, w), color, dtype=np.uint8)


def test_binarize_otsu_shape():
    frame = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
    binary = binarize_otsu(frame)
    assert binary.shape == (100, 100)


def test_binarize_otsu_binary_values():
    frame = np.random.randint(0, 256, (60, 60, 3), dtype=np.uint8)
    binary = binarize_otsu(frame)
    assert set(np.unique(binary)).issubset({0, 255})


def test_binarize_grayscale_input():
    gray = np.full((50, 50), 100, dtype=np.uint8)
    binary = binarize_otsu(gray)
    assert binary.shape == (50, 50)


def test_read_anchor_color_black():
    """Solid black image → anchor colour should be BLACK."""
    frame = _make_frame(color=0)
    color = read_anchor_color(frame, box_size=5, border=4)
    assert color == "BLACK"


def test_read_anchor_color_white():
    """Solid white image → anchor colour should be WHITE."""
    frame = _make_frame(color=255)
    color = read_anchor_color(frame, box_size=5, border=4)
    assert color == "WHITE"


def test_anchor_changed():
    assert anchor_changed("BLACK", "WHITE") is True
    assert anchor_changed("WHITE", "BLACK") is True
    assert anchor_changed("BLACK", "BLACK") is False
    assert anchor_changed("WHITE", "WHITE") is False
