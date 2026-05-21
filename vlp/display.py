"""Tkinter display window: main stream QR + feedback QR overlay."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Callable

from PIL import Image, ImageTk


class VLPDisplay:
    """Thread-safe Tkinter window for displaying stream and feedback QR codes.

    On macOS, NSWindow must be created on the main thread.  The design is:
      - start()         — create the Tk window (call on the main thread)
      - run_mainloop()  — run root.mainloop(), blocking the main thread
      - stop()          — queue root.quit() so the mainloop exits (thread-safe)

    All image updates from non-GUI threads are routed through an update queue
    that is drained by _poll_updates() running inside the Tk event loop.
    """

    def __init__(self, feedback_position: str = "BOTTOM_RIGHT") -> None:
        self._feedback_position = feedback_position
        self._root: tk.Tk | None = None
        self._main_label: tk.Label | None = None
        self._feedback_label: tk.Label | None = None
        self._main_photo: ImageTk.PhotoImage | None = None
        self._feedback_photo: ImageTk.PhotoImage | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._update_queue: queue.Queue[Callable] = queue.Queue()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create the Tkinter window. Must be called from the main thread."""
        root = tk.Tk()
        root.title("VLP")
        root.configure(bg="black")
        root.attributes("-fullscreen", True)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        feedback_size = max(108, int(min(sw, sh) * 0.10))

        main_label = tk.Label(root, bg="black")
        main_label.place(relx=0.5, rely=0.5, anchor="center")

        feedback_label = tk.Label(root, bg="black")
        self._position_feedback(feedback_label, sw, sh, feedback_size)

        self._root = root
        self._main_label = main_label
        self._feedback_label = feedback_label
        self._ready.set()

        # Schedule the first poll tick; subsequent reschedules happen inside
        # _poll_updates once the mainloop is running.
        root.after(0, self._poll_updates)

    def run_mainloop(self) -> None:
        """Run the Tkinter event loop. Blocks until stop() is called.
        Must be called from the main thread after start()."""
        if self._root is not None:
            self._root.mainloop()

    def stop(self) -> None:
        """Stop the event loop and mark the display as done (thread-safe)."""
        if self._root is not None:
            self._schedule(self._root.quit)
        self._stopped.set()

    # ------------------------------------------------------------------
    # Image updates (thread-safe)
    # ------------------------------------------------------------------

    def show_main_qr(self, img: Image.Image) -> None:
        """Display *img* in the main QR area (thread-safe)."""
        self._schedule(lambda: self._update_main(img))

    def show_feedback_qr(self, img: Image.Image) -> None:
        """Display *img* in the feedback corner (thread-safe)."""
        self._schedule(lambda: self._update_feedback(img))

    def clear_feedback_qr(self) -> None:
        """Remove the feedback QR overlay."""
        self._schedule(self._clear_feedback)

    # ------------------------------------------------------------------
    # Internal: direct GUI mutations (must run on main thread)
    # ------------------------------------------------------------------

    def _poll_updates(self) -> None:
        """Drain the update queue on each Tkinter event-loop tick."""
        while not self._update_queue.empty():
            try:
                fn = self._update_queue.get_nowait()
                fn()
            except queue.Empty:
                break
        if self._root:
            self._root.after(16, self._poll_updates)  # ~60 fps polling

    def _update_main(self, img: Image.Image) -> None:
        if self._main_label is None or self._root is None:
            return
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        feedback_min = max(108, int(min(sw, sh) * 0.10))
        max_side = min(sw, sh - feedback_min) - 20
        img = _fit_image(img, max_side, max_side)
        photo = ImageTk.PhotoImage(img)
        self._main_photo = photo  # keep reference
        self._main_label.configure(image=photo)

    def _update_feedback(self, img: Image.Image) -> None:
        if self._feedback_label is None or self._root is None:
            return
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        size = max(108, int(min(sw, sh) * 0.10))
        img = _fit_image(img, size, size)
        photo = ImageTk.PhotoImage(img)
        self._feedback_photo = photo
        self._feedback_label.configure(image=photo)

    def _clear_feedback(self) -> None:
        if self._feedback_label is not None:
            self._feedback_label.configure(image="")
            self._feedback_photo = None

    def _position_feedback(
        self,
        label: tk.Label,
        sw: int,
        sh: int,
        size: int,
    ) -> None:
        pad = 8
        pos = self._feedback_position
        if pos == "BOTTOM_RIGHT":
            label.place(x=sw - size - pad, y=sh - size - pad)
        elif pos == "BOTTOM_LEFT":
            label.place(x=pad, y=sh - size - pad)
        elif pos == "TOP_RIGHT":
            label.place(x=sw - size - pad, y=pad)
        else:  # TOP_LEFT
            label.place(x=pad, y=pad)

    def _schedule(self, fn: Callable) -> None:
        """Queue *fn* to run on the GUI thread."""
        self._update_queue.put(fn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fit_image(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Resize *img* to fit within max_w × max_h keeping aspect ratio."""
    w, h = img.size
    if w <= max_w and h <= max_h:
        return img
    scale = min(max_w / w, max_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)
