"""QR code image generation with Anchor Square overlay."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

import qrcode
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)

if TYPE_CHECKING:
    from vlp.config import ReceiverConfig, SenderConfig

_EC_MAP = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}


# ---------------------------------------------------------------------------
# Data frame
# ---------------------------------------------------------------------------

def render_data_frame(
    packet_bytes: bytes,
    seq_id: int,
    sender_cfg: "SenderConfig",
) -> Image.Image:
    """Generate a QR PNG with Anchor Square overlay for a data frame.

    The Anchor Square colour alternates per frame parity so the Receiver can
    detect frame transitions without decoding the QR content.
    """
    img = _make_qr(
        data=packet_bytes,
        version=sender_cfg.stream_qr_version,
        ec=sender_cfg.stream_qr_error_correction,
        box_size=sender_cfg.stream_qr_box_size,
        border=sender_cfg.stream_qr_border,
    )
    anchor_color = (0, 0, 0) if seq_id % 2 == 0 else (255, 255, 255)
    _draw_anchor(img, sender_cfg.stream_qr_box_size, sender_cfg.stream_qr_border, anchor_color)
    return img


# ---------------------------------------------------------------------------
# Control frame (no anchor square)
# ---------------------------------------------------------------------------

def render_control_frame(
    packet_bytes: bytes,
    receiver_cfg: "ReceiverConfig",
) -> Image.Image:
    """Generate a QR PNG for a control frame (no Anchor Square).

    The version auto-scales to fit the payload (handshake JSON can be large).
    """
    return _make_qr(
        data=packet_bytes,
        version=receiver_cfg.control_qr_version,
        ec=receiver_cfg.control_qr_error_correction,
        box_size=receiver_cfg.control_qr_box_size,
        border=receiver_cfg.control_qr_border,
        fit=True,
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def pil_to_numpy(img: Image.Image) -> np.ndarray:
    """Convert a PIL Image to an RGB numpy array."""
    return np.array(img.convert("RGB"))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_qr(
    data: bytes,
    version: int,
    ec: str,
    box_size: int,
    border: int,
    fit: bool = False,
) -> Image.Image:
    qr = qrcode.QRCode(
        version=version,
        error_correction=_EC_MAP[ec],
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=fit)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img


def _draw_anchor(
    img: Image.Image,
    box_size: int,
    border: int,
    color: tuple[int, int, int],
) -> None:
    """Draw the 4×4-module Anchor Square (1 module inset from quiet zone)."""
    x = (border + 1) * box_size
    y = (border + 1) * box_size
    size = 4 * box_size
    draw = ImageDraw.Draw(img)
    draw.rectangle([x, y, x + size - 1, y + size - 1], fill=color)
