# VLP Implementation Plan — Python

## Overview

Full Python implementation of the Visual Link Protocol (VLP) v1.0 as defined in `Specification.md`. The implementation targets two endpoints running on separate machines, each simultaneously acting as Sender and Receiver, communicating via camera and display.

---

## Technology Stack

| Concern | Library | Reason |
|---|---|---|
| QR generation | `qrcode[pil]` | Standard Python QR library with PIL backend |
| Image rendering | `Pillow` | PNG output, pixel-level drawing for Anchor Square |
| Camera capture | `opencv-python` (cv2) | Camera I/O, perspective transform, Otsu's thresholding |
| QR decoding | `zxingcpp` | Fast multi-format decoder; falls back to `pyzbar` |
| Display window | `tkinter` | Built-in; composites main stream QR + feedback QR overlay |
| Numeric ops | `numpy` | Bitmask arrays, image buffer manipulation |
| Config models | `dataclasses` | Lightweight typed config without extra deps |
| Binary packing | `struct` | Big-endian pack/unpack of packet fields |
| CRC32 | `zlib.crc32` | Standard library |
| SHA-256 | `hashlib` | Standard library |
| Concurrency | `threading` | Sender and Receiver roles run as concurrent threads |
| CLI | `argparse` | Standard library entry point |

---

## Project Structure

```
vlp/
├── __init__.py
├── constants.py           # Magic bytes, Ctrl IDs, error codes, protocol version
├── exceptions.py          # VLPError hierarchy (one class per error code)
├── config.py              # SenderConfig, ReceiverConfig dataclasses + validation
├── packet.py              # Encode/decode all packet types (data, handshake, control)
├── bitmask.py             # Bitmask create/read/update/serialize operations
├── qr_renderer.py         # QR image generation + Anchor Square overlay
├── image_processor.py     # Perspective transform, Otsu binarize, Anchor Square check
├── qr_scanner.py          # Camera loop, screen region detection, QR decode
├── cache.py               # Cache directory lifecycle + session.json R/W
├── handshake.py           # Phase 1: READY / ACK exchange logic
├── sender.py              # Sender role: streaming + recovery + completion
├── receiver.py            # Receiver role: capture loop + feedback QR + assembly
├── session.py             # Session state machine + dual-role orchestration
├── display.py             # Tkinter window: main QR area + feedback QR overlay
└── cli.py                 # argparse entry point: `python -m vlp`
tests/
├── test_constants.py
├── test_packet.py
├── test_bitmask.py
├── test_qr_renderer.py
├── test_image_processor.py
├── test_cache.py
├── test_handshake.py
├── test_sender.py
├── test_receiver.py
└── test_session.py
pyproject.toml
requirements.txt
README.md
```

---

## Implementation Phases

### Phase 0 — Project Scaffold

**Deliverables:** Runnable skeleton with all modules stubbed.

- [ ] Create `pyproject.toml` with package metadata and dependencies.
- [ ] Create `requirements.txt` (`qrcode[pil]`, `Pillow`, `opencv-python`, `zxingcpp`, `numpy`).
- [ ] Create all module files with module-level docstrings and `pass` stubs.
- [ ] Verify `python -m vlp --help` runs without import errors.

---

### Phase 1 — Constants & Exceptions

**Module:** `constants.py`, `exceptions.py`

**`constants.py`**
```python
MAGIC_BYTES = b'\x56\x4C'
VLP_VERSION = "1.0"
PACKET_OVERHEAD_BYTES = 22  # header(2) + sid(8) + seq_id(4) + total_frames(4) + crc32(4)

class CtrlID:
    HANDSHAKE_READY  = 0x01
    HANDSHAKE_ACK    = 0x02
    FRAME_ACK        = 0x03
    STATUS           = 0x04
    RETRANSMIT_DONE  = 0x05
    SESSION_COMPLETE = 0x06
    SESSION_ACK      = 0x07
    SESSION_ABORT    = 0x08

class ErrorCode:
    VERSION_MISMATCH       = 0x01
    CONFIG_INCOMPATIBLE    = 0x02
    HANDSHAKE_TIMEOUT      = 0x03
    SID_MISMATCH           = 0x04
    MAGIC_INVALID          = 0x05
    CRC_FAIL               = 0x06
    ACK_TIMEOUT            = 0x07
    FEEDBACK_TIMEOUT       = 0x08
    MAX_RECOVERY_EXCEEDED  = 0x09
    CACHE_FULL             = 0x0A
    CACHE_WRITE_FAIL       = 0x0B
    HASH_MISMATCH          = 0x0C
    TOTAL_FRAMES_MISMATCH  = 0x0D
    REMOTE_ABORT           = 0x0E

class SessionState:
    IDLE        = "IDLE"
    HANDSHAKING = "HANDSHAKING"
    CONFIRMING  = "CONFIRMING"
    STREAMING   = "STREAMING"
    RECOVERING  = "RECOVERING"
    COMPLETING  = "COMPLETING"
    DONE        = "DONE"
    ABORTED     = "ABORTED"
```

**`exceptions.py`**: One exception class per fatal error code, all inheriting from `VLPError(Exception)`. Each carries the `ErrorCode` byte so the session can embed it in a `SESSION_ABORT` packet.

---

### Phase 2 — Configuration

**Module:** `config.py`

Two frozen `@dataclass` classes:

**`SenderConfig`**
| Field | Type | Default |
|---|---|---|
| `stream_qr_version` | int | 10 |
| `stream_qr_error_correction` | str | `"M"` |
| `stream_qr_box_size` | int | 10 |
| `stream_qr_border` | int | 4 |
| `streaming_mode` | str | `"PACED"` |
| `frame_interval_ms` | int | 150 |
| `ack_timeout_ms` | int | 3000 |
| `max_ack_retries` | int | 5 |
| `payload_encoding` | str | `"BASE64"` |

**`ReceiverConfig`**
| Field | Type | Default |
|---|---|---|
| `control_qr_version` | int | 5 |
| `control_qr_error_correction` | str | `"Q"` |
| `control_qr_box_size` | int | 8 |
| `control_qr_border` | int | 4 |
| `feedback_position` | str | `"BOTTOM_RIGHT"` |
| `feedback_interval_ms` | int | 500 |
| `cache_directory` | str | *(required)* |
| `max_cache_size_mb` | int | 512 |

**`__post_init__` validation rules:**
- `stream_qr_error_correction` must be `M`, `Q`, or `H` (not `L`).
- `stream_qr_box_size` ≥ 5; `stream_qr_border` ≥ 4.
- `frame_interval_ms` in `[80, 5000]`.
- `ack_timeout_ms` ≥ 500.
- `cache_directory` must exist and be writable.
- `feedback_position` must be one of `BOTTOM_RIGHT`, `BOTTOM_LEFT`, `TOP_RIGHT`, `TOP_LEFT`.

**`TimeoutConfig`** dataclass (separate, not in handshake payload):
- `handshake_timeout_ms` = 30000
- `feedback_scan_timeout_ms` = 10000
- `max_recovery_rounds` = 10
- `completion_timeout_ms` = 15000

---

### Phase 3 — Packet Codec

**Module:** `packet.py`

Responsible for all binary serialization and deserialization. Uses `struct` for big-endian packing.

#### 3.1 Data Packet

```python
def encode_data_packet(sid: int, seq_id: int, total_frames: int, payload: bytes) -> bytes:
    """Packs: MAGIC(2) + SID(8) + SEQ_ID(4) + TOTAL_FRAMES(4) + PAYLOAD(var) + CRC32(4)"""
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return struct.pack(">2sQII", MAGIC_BYTES, sid, seq_id, total_frames) + payload + struct.pack(">I", crc)

def decode_data_packet(raw: bytes) -> DataPacket:
    """Validates magic, unpacks fields, verifies CRC32. Raises appropriate VLPError on failure."""
```

`DataPacket` is a dataclass: `sid`, `seq_id`, `total_frames`, `payload`.

#### 3.2 Control Packet

```python
def encode_control_packet(sid: int, ctrl_id: int, payload: bytes = b'') -> bytes:
    return struct.pack(">2sQB", MAGIC_BYTES, sid, ctrl_id) + payload

def decode_control_packet(raw: bytes) -> ControlPacket:
    """Returns ControlPacket(sid, ctrl_id, payload). Validates magic bytes."""
```

#### 3.3 Handshake Packets

```python
def encode_handshake_ready(sid: int, file_meta: FileMetadata,
                            sender_cfg: SenderConfig, receiver_cfg: ReceiverConfig) -> bytes:
    """Encodes HANDSHAKE_READY as control packet with JSON payload."""

def encode_handshake_ack(local_sid: int, opposing_sid: int, total_frames: int) -> bytes:
    """Encodes HANDSHAKE_ACK as control packet with JSON payload."""

def decode_handshake_json(payload: bytes) -> dict:
    """UTF-8 decode + json.loads. Raises VLPError on malformed JSON."""
```

#### 3.4 Payload Encoding

```python
def encode_payload(raw_chunk: bytes, encoding: str) -> bytes:
    if encoding == "BASE64":
        return base64.b64encode(raw_chunk)
    return raw_chunk  # RAW_BYTES

def decode_payload(encoded: bytes, encoding: str) -> bytes:
    if encoding == "BASE64":
        return base64.b64decode(encoded)
    return encoded
```

#### 3.5 Max Payload Calculator

```python
QR_CAPACITY = {
    (10, 'L'): 271, (10, 'M'): 213, (10, 'Q'): 151, (10, 'H'): 117,
    (15, 'L'): 520, (15, 'M'): 412, (15, 'Q'): 290, (15, 'H'): 223,
    (20, 'L'): 858, (20, 'M'): 666, (20, 'Q'): 474, (20, 'H'): 365,
    (25, 'L'): 1273, (25, 'M'): 1000, (25, 'Q'): 706, (25, 'H'): 544,
    (30, 'L'): 1732, (30, 'M'): 1362, (30, 'Q'): 966, (30, 'H'): 745,
    (40, 'L'): 2953, (40, 'M'): 2331, (40, 'Q'): 1663, (40, 'H'): 1273,
}

def max_raw_bytes_per_frame(qr_version: int, ec_level: str, encoding: str) -> int:
    capacity = QR_CAPACITY[(qr_version, ec_level)]
    available = capacity - PACKET_OVERHEAD_BYTES
    if encoding == "BASE64":
        return (available * 3) // 4
    return available
```

---

### Phase 4 — Bitmask

**Module:** `bitmask.py`

```python
class Bitmask:
    def __init__(self, total_frames: int): ...
    def mark_received(self, seq_id: int) -> None: ...
    def is_received(self, seq_id: int) -> bool: ...
    def all_received(self) -> bool: ...
    def missing_seq_ids(self) -> list[int]: ...
    def to_bytes(self) -> bytes:
        """Packs bits MSB-first; pads last byte with 1-bits."""
    @classmethod
    def from_bytes(cls, data: bytes, total_frames: int) -> 'Bitmask': ...
    def to_hex(self) -> str: ...
    @classmethod
    def from_hex(cls, hex_str: str, total_frames: int) -> 'Bitmask': ...
```

Key detail: padding bits in the last byte are set to `1` on serialization.

---

### Phase 5 — QR Renderer

**Module:** `qr_renderer.py`

#### 5.1 Data Frame Rendering

```python
def render_data_frame(packet_bytes: bytes, seq_id: int,
                       sender_cfg: SenderConfig) -> PIL.Image.Image:
    """
    1. Generate QR image using qrcode library (PNG, version=stream_qr_version,
       error_correction=stream_qr_error_correction, box_size, border).
    2. Convert to RGB PIL image.
    3. Overlay Anchor Square (§5.2): determine color by seq_id % 2.
    4. Return PIL Image.
    """
```

**Anchor Square placement:**
- Position: `(border * box_size + box_size, border * box_size + box_size)` in pixels
  (1 module inset from top-left quiet zone boundary).
- Size: `4 * box_size` × `4 * box_size` pixels (4 modules × box_size).
- Color: `(0, 0, 0)` if `seq_id % 2 == 0`, else `(255, 255, 255)`.
- Drawn with `PIL.ImageDraw.Draw.rectangle()` after QR generation.

#### 5.2 Control Frame Rendering

```python
def render_control_frame(packet_bytes: bytes,
                          receiver_cfg: ReceiverConfig) -> PIL.Image.Image:
    """No Anchor Square. Uses control_qr_* config parameters."""
```

#### 5.3 Image to NumPy (for display)

```python
def pil_to_numpy(img: PIL.Image.Image) -> np.ndarray: ...
```

---

### Phase 6 — Image Processor

**Module:** `image_processor.py`

#### 6.1 Screen Region Detection

```python
def detect_screen_region(frame: np.ndarray) -> np.ndarray | None:
    """
    Uses cv2 to find the largest quadrilateral contour in the frame
    (assumed to be the opposing device's screen).
    Returns the 4-corner points or None if not found.
    """
```

#### 6.2 Perspective Transform

```python
def perspective_transform(frame: np.ndarray, corners: np.ndarray,
                           output_size: tuple[int, int]) -> np.ndarray:
    """
    Applies cv2.getPerspectiveTransform + cv2.warpPerspective to correct
    keystoning and angle distortion.
    """
```

#### 6.3 Binarize (Otsu's Thresholding)

```python
def binarize_otsu(frame: np.ndarray) -> np.ndarray:
    """Converts to grayscale, applies cv2.threshold with THRESH_OTSU."""
```

#### 6.4 Anchor Square Check

```python
def read_anchor_color(frame: np.ndarray, box_size: int, border: int) -> str:
    """
    Reads pixel region at Anchor Square position.
    Returns 'BLACK' or 'WHITE' based on average pixel value.
    """

def anchor_changed(prev_color: str, curr_color: str) -> bool:
    return prev_color != curr_color
```

---

### Phase 7 — QR Scanner

**Module:** `qr_scanner.py`

```python
class QRScanner:
    def __init__(self, camera_index: int = 0): ...
    def open(self) -> None: ...  # cv2.VideoCapture
    def close(self) -> None: ...

    def capture_frame(self) -> np.ndarray:
        """Reads one frame from the camera."""

    def scan_for_packet(self, last_anchor_color: str,
                         opposing_box_size: int,
                         opposing_border: int) -> tuple[bytes | None, str]:
        """
        Full pipeline: capture → detect screen region → perspective transform →
        binarize → anchor check → QR decode.
        Returns (raw_packet_bytes_or_None, new_anchor_color).
        Skips QR decode if anchor color unchanged.
        """

    def scan_blocking(self, timeout_ms: int) -> bytes | None:
        """
        Loops scan_for_packet until a valid raw packet is returned
        or timeout_ms elapses. Does NOT validate packet content.
        """
```

QR decoding uses `zxingcpp.read_barcodes()` on the binarized numpy array. Falls back to `pyzbar.decode()` if `zxingcpp` is unavailable.

---

### Phase 8 — Cache Manager

**Module:** `cache.py`

```python
class SessionCache:
    def __init__(self, cache_directory: str, opposing_sid: str,
                 max_cache_size_mb: int): ...

    def initialize(self, session_meta: dict) -> None:
        """
        Creates vlp_{opposing_sid}/ and frames/ subdirs.
        Deletes any leftover .tmp files.
        Writes initial session.json.
        """

    def write_frame(self, seq_id: int, payload: bytes) -> None:
        """
        Atomic write: payload → {seq_id:010d}.frm.tmp → rename to .frm
        Checks total cache size against max_cache_size_mb before write.
        Raises ERR_CACHE_FULL or ERR_CACHE_WRITE_FAIL on error.
        """

    def read_frame(self, seq_id: int) -> bytes:
        """Reads {seq_id:010d}.frm."""

    def frame_exists(self, seq_id: int) -> bool: ...

    def update_session_json(self, updates: dict) -> None:
        """Thread-safe JSON patch of session.json fields."""

    def assemble_file(self, total_frames: int, output_path: str) -> None:
        """Concatenates .frm files 0..N-1 into output_path."""

    def cleanup(self) -> None:
        """Deletes entire vlp_{opposing_sid}/ tree (shutil.rmtree)."""

    @staticmethod
    def find_resumable_sessions(cache_directory: str) -> list[dict]:
        """Scans for vlp_*/session.json with state != DONE."""
```

---

### Phase 9 — Display

**Module:** `display.py`

Manages a single `tkinter` window that shows:
- **Main area**: large QR image (Sender's current data frame or control frame).
- **Feedback overlay**: small QR image pinned to a corner (Receiver's feedback).

```python
class VLPDisplay:
    def __init__(self, feedback_position: str): ...
    def start(self) -> None:      # Launches tkinter mainloop in a daemon thread
    def stop(self) -> None:

    def show_main_qr(self, img: PIL.Image.Image) -> None:
        """Thread-safe update of main QR region. Uses after() or queue."""

    def show_feedback_qr(self, img: PIL.Image.Image) -> None:
        """Thread-safe update of feedback QR region."""

    def clear_feedback_qr(self) -> None: ...
```

**Layout rules:**
- Window fills screen using `root.attributes('-fullscreen', True)`.
- Feedback QR minimum size = 10% of `min(screen_width, screen_height)` pixels.
- Feedback QR corner position determined by `feedback_position` config.
- Main QR area uses remaining space, centered.
- Both panes use `tkinter.Label` with `PIL.ImageTk.PhotoImage`.
- All updates routed through `root.after(0, callback)` from non-GUI threads.

---

### Phase 10 — Handshake

**Module:** `handshake.py`

```python
class HandshakeCoordinator:
    def __init__(self, local_sid: int, file_meta: FileMetadata,
                 sender_cfg: SenderConfig, receiver_cfg: ReceiverConfig,
                 display: VLPDisplay, scanner: QRScanner,
                 timeout_cfg: TimeoutConfig): ...

    def run(self) -> HandshakeResult:
        """
        Concurrent execution:
        Thread A (Sender role): display READY QR continuously.
        Thread B (Receiver role): scan for opposing READY QR.

        On receiving valid READY from opposing endpoint:
          1. Validate vlp_version.
          2. Store opposing_sid.
          3. Validate opposing sender_config compatibility.
          4. Pre-allocate cache.
          5. Switch display to HANDSHAKE_ACK QR.

        Wait until local ACK is also scanned by opposing side
        (inferred by receiving their HANDSHAKE_ACK that echoes local SID).

        Returns HandshakeResult(opposing_sid, opposing_file_meta,
                                opposing_sender_cfg, opposing_receiver_cfg).
        Raises VLPError on timeout or validation failure.
        """
```

`FileMetadata` dataclass: `name`, `size_bytes`, `sha256`, `total_frames`.

---

### Phase 11 — Sender Role

**Module:** `sender.py`

```python
class SenderRole:
    def __init__(self, file_path: str, total_frames: int, sid: int,
                 sender_cfg: SenderConfig, display: VLPDisplay,
                 scanner: QRScanner, timeout_cfg: TimeoutConfig): ...

    def run(self) -> None:
        """Runs streaming → recovering → completing in sequence."""

    def _streaming_phase(self) -> None:
        """
        PACED MODE:
          For seq_id in 0..N-1:
            render frame → display → sleep(frame_interval_ms)

        ACKNOWLEDGED MODE:
          For seq_id in 0..N-1:
            render frame → display
            Poll scanner for FRAME_ACK(seq_id) within ack_timeout_ms.
            On timeout: increment retry. If retries >= max_ack_retries → ERR_ACK_TIMEOUT.
        """

    def _recovering_phase(self) -> None:
        """
        Loop up to max_recovery_rounds:
          1. Scan feedback QR → parse STATUS bitmask.
          2. Retransmit missing frames in ascending seq_id order.
          3. If all bits = 1 → exit loop (success).
          4. If rounds exceeded → ERR_MAX_RECOVERY_EXCEEDED.
          5. If feedback QR unreadable within feedback_scan_timeout_ms → ERR_FEEDBACK_TIMEOUT.
        """

    def _completing_phase(self) -> None:
        """
        Display SESSION_COMPLETE for 3 × frame_interval_ms.
        Poll for SESSION_ACK within completion_timeout_ms (retry up to 3 times).
        If no ACK → DONE_UNCONFIRMED.
        """

    def _render_frame(self, seq_id: int) -> PIL.Image.Image:
        """Chunks file, encodes payload, builds packet, renders QR + anchor square."""
```

File chunking:
```python
chunk_size = max_raw_bytes_per_frame(qr_version, ec_level, encoding)
with open(file_path, 'rb') as f:
    f.seek(seq_id * chunk_size)
    raw_chunk = f.read(chunk_size)
```

---

### Phase 12 — Receiver Role

**Module:** `receiver.py`

```python
class ReceiverRole:
    def __init__(self, opposing_sid: int, opposing_file_meta: FileMetadata,
                 opposing_sender_cfg: SenderConfig,
                 receiver_cfg: ReceiverConfig, output_path: str,
                 display: VLPDisplay, scanner: QRScanner,
                 cache: SessionCache, bitmask: Bitmask,
                 timeout_cfg: TimeoutConfig): ...

    def run(self) -> None:
        """Runs capture loop; terminates when all frames received or on abort."""

    def _capture_loop(self) -> None:
        """
        Runs in its own thread. Continuous:
          1. scan_for_packet() → raw bytes.
          2. decode_control_packet() or decode_data_packet().
          3. If data packet: validate magic, SID, total_frames, CRC32.
             On pass: cache.write_frame(); bitmask.mark_received().
          4. If SESSION_COMPLETE: set completion flag; break.
          5. If SESSION_ABORT: raise ERR_REMOTE_ABORT.
        """

    def _feedback_loop(self) -> None:
        """
        Runs in its own thread. Every feedback_interval_ms:
          Render STATUS control frame (bitmask serialized per §9.2).
          Call display.show_feedback_qr().
        """

    def _assembly_phase(self) -> None:
        """
        cache.assemble_file() → compute SHA-256 → compare with handshake hash.
        On match: display SESSION_ACK; cache.cleanup().
        On mismatch: raise ERR_HASH_MISMATCH (cache preserved).
        """
```

---

### Phase 13 — Session Orchestrator

**Module:** `session.py`

Ties all components together. Each `VLPSession` instance runs both `SenderRole` and `ReceiverRole` concurrently in separate threads.

```python
class VLPSession:
    def __init__(self, file_to_send: str, output_path: str,
                 sender_cfg: SenderConfig, receiver_cfg: ReceiverConfig,
                 timeout_cfg: TimeoutConfig | None = None,
                 camera_index: int = 0): ...

    def start(self) -> SessionResult:
        """
        1. Compute file metadata (size, sha256, total_frames).
        2. Generate local SID (os.urandom(8) → int).
        3. Initialize VLPDisplay.
        4. Initialize QRScanner.
        5. Run HandshakeCoordinator → HandshakeResult.
        6. Initialize SessionCache + Bitmask.
        7. Launch SenderRole thread + ReceiverRole thread concurrently.
        8. Join both threads; collect results.
        9. Return SessionResult(sender_status, receiver_status).
        """

    def abort(self, error_code: int) -> None:
        """
        Renders SESSION_ABORT QR with error_code.
        Sets abort event to signal all threads to terminate.
        Cleans up cache (unless ERR_HASH_MISMATCH or ERR_CRC_FAIL).
        """
```

**Abort propagation:** A `threading.Event` (`_abort_event`) is shared across all components. Any component that encounters a fatal error calls `session.abort(code)`. All loops check `_abort_event.is_set()` at each iteration.

---

### Phase 14 — CLI Entry Point

**Module:** `cli.py`

```
python -m vlp send <file_path> [options]
python -m vlp receive <output_path> [options]
python -m vlp transfer <file_path> <output_path> [options]   # full duplex
```

**Common options:**
```
--camera-index INT          Camera device index (default: 0)
--cache-dir PATH            Required for receiver role
--streaming-mode PACED|ACKNOWLEDGED
--frame-interval-ms INT
--qr-version INT
--qr-ec LEVEL               M|Q|H
--feedback-position CORNER
--max-cache-mb INT
--resume                    Attempt to resume an interrupted session
```

`transfer` subcommand (primary use case): runs both roles simultaneously, requires both `--cache-dir` and `<output_path>`.

---

### Phase 15 — Testing

Each module has a corresponding test file under `tests/`.

| Test File | Coverage |
|---|---|
| `test_packet.py` | Round-trip encode/decode for all packet types; CRC32 validation; magic byte rejection; big-endian byte order |
| `test_bitmask.py` | mark_received, all_received, missing_seq_ids, padding bits, to_bytes/from_bytes round-trip |
| `test_qr_renderer.py` | Anchor Square pixel color at correct position; PNG output format; correct QR version |
| `test_image_processor.py` | Otsu binarize output shape; anchor color detection on synthetic images |
| `test_cache.py` | Atomic write (tmp → rename); frame_exists; assemble_file produces correct concatenation; cleanup; max_cache_size enforcement |
| `test_handshake.py` | READY JSON structure; ACK JSON structure; version mismatch raises correct error |
| `test_sender.py` | Paced mode timing (mocked sleep); ACKNOWLEDGED mode retry logic; frame chunking produces correct seq_id ordering |
| `test_receiver.py` | Capture loop correctly marks bitmask; corrupt CRC32 not written to cache; SHA-256 verification pass/fail |
| `test_session.py` | Full integration test using loopback (pre-rendered frames fed directly to decoder, no real camera) |

---

## Key Implementation Details & Decisions

### Concurrency Model
Each endpoint runs exactly three threads:
1. **Main thread**: session orchestration, GUI event loop (tkinter mainloop).
2. **Sender thread**: frame rendering + display updates + camera scanning for ACKs/recovery.
3. **Receiver thread**: capture loop (camera read) + feedback QR updates.

A shared `threading.Event` (`abort_event`) and `threading.Lock` guard shared state (bitmask, cache).

### Anchor Square Coordinate Formula
Given `box_size` and `border` (in modules):
```
x = (border + 1) * box_size   # 1 module inset from quiet zone
y = (border + 1) * box_size
width = height = 4 * box_size
```
The 4×4 spec refers to QR modules; multiply by `box_size` for pixel dimensions.

### Session ID Generation
```python
import os, struct
sid_int = struct.unpack(">Q", os.urandom(8))[0]
sid_hex = format(sid_int, '016X')
```

### Pre-computing `total_frames`
```python
chunk_size = max_raw_bytes_per_frame(qr_version, ec_level, encoding)
file_size = os.path.getsize(file_path)
total_frames = math.ceil(file_size / chunk_size)
```

### Thread-safe display updates (tkinter)
Tkinter is not thread-safe. All display mutations must be scheduled via `root.after(0, fn)` from non-main threads. The `VLPDisplay` class wraps this internally using a `queue.Queue`.

### Camera warm-up
`cv2.VideoCapture` requires several frames to stabilize exposure. The `QRScanner.open()` method discards the first 10 frames before returning.

---

## Dependencies (`requirements.txt`)

```
qrcode[pil]>=7.4
Pillow>=10.0
opencv-python>=4.8
zxingcpp>=2.0
numpy>=1.24
```

Optional:
```
pyzbar>=0.1.9     # fallback QR decoder if zxingcpp unavailable
```

Dev/test:
```
pytest>=8.0
pytest-cov>=5.0
```

---

## Conformance Checklist (from §15)

| Requirement | Module |
|---|---|
| All packet types (§4.3) | `packet.py` |
| PACED + ACKNOWLEDGED modes | `sender.py` |
| Anchor Square mechanism | `qr_renderer.py`, `image_processor.py` |
| Perspective transform + Otsu | `image_processor.py`, `qr_scanner.py` |
| Bitmask feedback + Selective Repeat ARQ | `bitmask.py`, `sender.py`, `receiver.py` |
| Atomic cache writes + session.json | `cache.py` |
| session.json state transitions | `cache.py`, `session.py` |
| Timeout policies | `sender.py`, `receiver.py`, `handshake.py` |
| Magic Bytes `0x564C` | `constants.py`, `packet.py` |
| Big-endian byte order | `packet.py` |
| PNG output format | `qr_renderer.py` |
| SHA-256 assembly verification | `receiver.py` |

Optional (MAY implement):
- Session resumption → `cache.py` + `cli.py --resume`
- `RAW_BYTES` encoding → `packet.py`
- HMAC authentication → `session.py` (post-MVP)
- Pre-transmission encryption → `cli.py` (post-MVP)
