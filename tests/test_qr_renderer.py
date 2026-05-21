"""Tests for vlp.qr_renderer."""

import numpy as np
import pytest
from PIL import Image

from vlp.config import ReceiverConfig, SenderConfig
from vlp.qr_renderer import pil_to_numpy, render_control_frame, render_data_frame


@pytest.fixture
def sender_cfg(tmp_path):
    return SenderConfig(
        stream_qr_version=5,
        stream_qr_error_correction="M",
        stream_qr_box_size=5,
        stream_qr_border=4,
    )


@pytest.fixture
def receiver_cfg(tmp_path):
    return ReceiverConfig(
        control_qr_version=3,
        control_qr_box_size=5,
        control_qr_border=4,
        cache_directory=str(tmp_path),
    )


def test_render_data_frame_returns_image(sender_cfg):
    pkt = b"VL" + b"\x00" * 30  # 32 bytes << v5-M capacity (84 bytes)
    img = render_data_frame(pkt, seq_id=0, sender_cfg=sender_cfg)
    assert isinstance(img, Image.Image)


def test_anchor_color_even_frame(sender_cfg):
    """Even seq_id → Anchor Square is black."""
    pkt = b"VL" + b"\x00" * 30
    img = render_data_frame(pkt, seq_id=0, sender_cfg=sender_cfg)
    arr = np.array(img.convert("L"))

    box_size = sender_cfg.stream_qr_box_size
    border = sender_cfg.stream_qr_border
    x = (border + 1) * box_size
    y = (border + 1) * box_size
    size = 4 * box_size
    region = arr[y: y + size, x: x + size]
    assert region.mean() < 50, "Even frame Anchor Square should be black"


def test_anchor_color_odd_frame(sender_cfg):
    """Odd seq_id → Anchor Square is white."""
    pkt = b"VL" + b"\x00" * 30
    img = render_data_frame(pkt, seq_id=1, sender_cfg=sender_cfg)
    arr = np.array(img.convert("L"))

    box_size = sender_cfg.stream_qr_box_size
    border = sender_cfg.stream_qr_border
    x = (border + 1) * box_size
    y = (border + 1) * box_size
    size = 4 * box_size
    region = arr[y: y + size, x: x + size]
    assert region.mean() > 200, "Odd frame Anchor Square should be white"


def test_render_control_frame_returns_image(receiver_cfg):
    pkt = b"VL" + b"\x00" * 20
    img = render_control_frame(pkt, receiver_cfg=receiver_cfg)
    assert isinstance(img, Image.Image)


def test_pil_to_numpy(sender_cfg):
    pkt = b"VL" + b"\x00" * 30
    img = render_data_frame(pkt, seq_id=0, sender_cfg=sender_cfg)
    arr = pil_to_numpy(img)
    assert isinstance(arr, np.ndarray)
    assert arr.ndim == 3
    assert arr.shape[2] == 3  # RGB
