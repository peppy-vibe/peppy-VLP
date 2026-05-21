"""Camera frame processing: perspective transform, Otsu binarise, Anchor Square."""

from __future__ import annotations

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Screen region detection
# ---------------------------------------------------------------------------

def detect_screen_region(frame: np.ndarray) -> np.ndarray | None:
    """Find the largest quadrilateral contour (assumed to be the opposing screen).

    Returns an array of shape (4, 2) with corner coordinates, or None.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Sort by area descending, find first approximately-rectangular contour
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True):
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) > 1000:
            return approx.reshape(4, 2).astype(np.float32)

    return None


# ---------------------------------------------------------------------------
# Perspective transform
# ---------------------------------------------------------------------------

def perspective_transform(
    frame: np.ndarray,
    corners: np.ndarray,
    output_size: tuple[int, int],
) -> np.ndarray:
    """Warp the region defined by *corners* into a flat *output_size* rectangle."""
    dst = np.array(
        [
            [0, 0],
            [output_size[0] - 1, 0],
            [output_size[0] - 1, output_size[1] - 1],
            [0, output_size[1] - 1],
        ],
        dtype=np.float32,
    )
    corners_ordered = _order_corners(corners)
    M = cv2.getPerspectiveTransform(corners_ordered, dst)
    return cv2.warpPerspective(frame, M, output_size)


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order corners: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]    # top-left  (smallest x+y)
    rect[2] = pts[np.argmax(s)]    # bottom-right (largest x+y)
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right  (smallest y-x)
    rect[3] = pts[np.argmax(diff)]  # bottom-left (largest y-x)
    return rect


# ---------------------------------------------------------------------------
# Otsu binarisation
# ---------------------------------------------------------------------------

def binarize_otsu(frame: np.ndarray) -> np.ndarray:
    """Convert *frame* to grayscale and apply Otsu's global threshold."""
    if len(frame.shape) == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


# ---------------------------------------------------------------------------
# Anchor Square reading
# ---------------------------------------------------------------------------

def read_anchor_color(frame: np.ndarray, box_size: int, border: int) -> str:
    """Return 'BLACK' or 'WHITE' based on the average pixel value in the Anchor region."""
    x = (border + 1) * box_size
    y = (border + 1) * box_size
    size = 4 * box_size

    h, w = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w, x + size), min(h, y + size)

    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return "UNKNOWN"

    if len(region.shape) == 3:
        avg = float(np.mean(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)))
    else:
        avg = float(np.mean(region))

    return "BLACK" if avg < 128 else "WHITE"


def anchor_changed(prev_color: str, curr_color: str) -> bool:
    """Return True when the Anchor Square has toggled (new frame detected)."""
    return prev_color != curr_color
