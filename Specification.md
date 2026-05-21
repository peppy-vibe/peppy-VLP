# VLP: Visual Link Protocol
## Specification v1.0

> **Abstract:** VLP is a bidirectional, optical data transmission protocol designed for high-volume file transfer between two devices using cameras and displays. Files are segmented into QR-code encoded frames and transmitted visually. Both parties transmit simultaneously and independently, using a built-in feedback loop for error recovery without halting the primary data stream.

---

## Table of Contents

1. [Terminology](#1-terminology)
2. [Protocol Overview](#2-protocol-overview)
3. [Configuration Model](#3-configuration-model)
4. [Frame & Packet Structures](#4-frame--packet-structures)
5. [QR Code Rendering Rules](#5-qr-code-rendering-rules)
6. [Session Lifecycle & State Machine](#6-session-lifecycle--state-machine)
7. [Phase 1 — Handshake](#7-phase-1--handshake)
8. [Phase 2 — Data Streaming](#8-phase-2--data-streaming)
9. [Phase 3 — Error Recovery (Feedback Loop)](#9-phase-3--error-recovery-feedback-loop)
10. [Phase 4 — Completion & Teardown](#10-phase-4--completion--teardown)
11. [Cache Management (Receiver Temp Storage)](#11-cache-management-receiver-temp-storage)
12. [Timeout & Retry Policy](#12-timeout--retry-policy)
13. [Error Codes & Diagnostics](#13-error-codes--diagnostics)
14. [Security Considerations](#14-security-considerations)
15. [Conformance Requirements](#15-conformance-requirements)

---

## 1. Terminology

| Term | Definition |
|---|---|
| **Session** | A single end-to-end VLP exchange between two endpoints, identified by a unique Session ID. |
| **Endpoint** | Either participant in a session. Each endpoint is simultaneously a Sender and a Receiver. |
| **Sender role** | The role responsible for encoding and displaying data frames to the opposing camera. |
| **Receiver role** | The role responsible for capturing and decoding displayed frames from the opposing screen. |
| **Frame** | A single QR code displayed on screen, encoding one packet of data. |
| **Packet** | The binary payload encapsulated within a frame (see §4). |
| **Session ID (SID)** | A randomly generated 8-byte identifier unique to one VLP session. |
| **Bitmask** | A compact array of bits, one per frame slot, used to track which frames are received or missing. |
| **Anchor Square** | A small high-contrast toggle square embedded at a fixed position in every data frame, used as a frame-change clock. |
| **Paced Mode** | A streaming mode where the Sender advances frames at a fixed configurable interval without waiting for per-frame acknowledgement. |
| **Acknowledged Mode** | A streaming mode where the Sender waits for an explicit per-frame ACK from the Receiver before advancing to the next frame. |
| **Cache Directory** | A filesystem directory specified by the Receiver to persistently store partial frame data during an active session. |
| **Magic Bytes** | A fixed 2-byte sequence (`0x564C`, spelling "VL") that marks the start of any VLP packet. |
| **CRC32** | A 4-byte cyclic redundancy check computed over the packet payload, used for integrity verification. |

---

## 2. Protocol Overview

### 2.1 Transmission Model

VLP operates as two **independent, simultaneous, full-duplex streams**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Endpoint A                                  Endpoint B                     │
│                                                                             │
│  [Screen: Data QR / Feedback QR]  ←────→  [Camera: Capture]                 │
│  [Camera: Capture]                ←────→  [Screen: Data QR / Feedback QR]   │
└─────────────────────────────────────────────────────────────────────────────┘
```

Each endpoint independently:
- Encodes its own file into N frames and displays them (Sender role).
- Captures and decodes frames from the opposing screen (Receiver role).
- Displays a small Feedback QR in a reserved screen corner to communicate frame status back to the opposing Sender.

### 2.2 Separation of QR Roles

To prevent configuration conflicts and allow each endpoint to independently optimize its own display, QR rendering configurations are role-scoped:

| QR Usage | Configured By | Section |
|---|---|---|
| Handshake READY and ACK codes | **Receiver** (as it must read the opposing side's screen format) | §3.2 |
| Data streaming frames | **Sender** | §3.1 |
| Feedback (Status QR, bitmask) | **Receiver** | §3.2 |
| Completion DONE codes | **Sender** | §3.1 |

### 2.3 Streaming Mode Selection

The Sender MUST select exactly one streaming mode before session start:

- **Paced Mode (default):** The Sender advances to the next frame on a fixed time interval (`frame_interval_ms`). The Receiver accumulates any missed frames and requests retransmission during the feedback phase. This maximizes throughput.
- **Acknowledged Mode:** The Sender displays each frame and waits until it reads a `FRAME_ACK` from the Receiver's Feedback QR before advancing. This maximizes reliability at the cost of throughput and is recommended for noisy optical environments.

Both modes use the same packet structure and error recovery mechanism; only the advancement trigger differs.

---

## 3. Configuration Model

All configuration parameters MUST be resolved before Phase 1 begins and MUST NOT change during an active session.

### 3.1 Sender Configuration

These parameters govern the QR codes rendered by the **Sender** during data streaming and session completion.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `stream_qr_version` | Integer | No | `10` | QR Version for data frames (1–40). Higher versions hold more data per frame but require more camera resolution. Recommended range: 10–20. |
| `stream_qr_error_correction` | Enum | No | `M` | Error correction level for data frames. One of: `L` (7%), `M` (15%), `Q` (25%), `H` (30%). MUST be `M` or higher. |
| `stream_qr_box_size` | Integer | No | `10` | Pixel size of each QR module (box) in the rendered image, in pixels. Minimum: `5`. |
| `stream_qr_border` | Integer | No | `4` | Width of the quiet zone (border) around the QR code, measured in modules (not pixels). Minimum: `4` per QR spec. |
| `streaming_mode` | Enum | No | `PACED` | Either `PACED` or `ACKNOWLEDGED`. See §2.3. |
| `frame_interval_ms` | Integer | No | `150` | (Paced Mode only) Duration in milliseconds each data frame is held on screen. Valid range: 80–5000 ms. |
| `ack_timeout_ms` | Integer | No | `3000` | (Acknowledged Mode only) Maximum time in ms to wait for a FRAME_ACK before treating the frame as unacknowledged and re-displaying. |
| `max_ack_retries` | Integer | No | `5` | (Acknowledged Mode only) Number of times to re-display a frame before aborting the session with `ERR_ACK_TIMEOUT`. |
| `payload_encoding` | Enum | No | `BASE64` | How the raw binary payload is encoded inside the QR. One of: `BASE64`, `RAW_BYTES`. `BASE64` is safer across QR decoders; `RAW_BYTES` offers ~25% smaller frames. |

### 3.2 Receiver Configuration

These parameters govern the QR codes rendered by the **Receiver** for handshake responses and all feedback communications.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `control_qr_version` | Integer | No | `5` | QR Version for all control-plane codes (handshake ACK, Feedback Status QR). Control payloads are small; lower versions are recommended (1–10). |
| `control_qr_error_correction` | Enum | No | `Q` | Error correction for control codes. One of: `L`, `M`, `Q`, `H`. Recommended `Q` or `H` since control data is critical. |
| `control_qr_box_size` | Integer | No | `8` | Pixel size of each QR module for control codes, in pixels. Minimum: `5`. |
| `control_qr_border` | Integer | No | `4` | Quiet zone width for control codes, in modules. Minimum: `4`. |
| `feedback_position` | Enum | No | `BOTTOM_RIGHT` | Screen corner where the Feedback QR is displayed. One of: `BOTTOM_RIGHT`, `BOTTOM_LEFT`, `TOP_RIGHT`, `TOP_LEFT`. Must not overlap the main data stream display area. |
| `feedback_interval_ms` | Integer | No | `500` | How frequently the Receiver refreshes the Feedback Status QR with updated bitmask data, in milliseconds. |
| `cache_directory` | String | Yes | — | Absolute filesystem path to the directory where temporary session data is stored. Directory MUST exist and be writable before session start. |
| `max_cache_size_mb` | Integer | No | `512` | Maximum allowed disk usage for one session's cache, in megabytes. If exceeded, the session MUST abort with `ERR_CACHE_FULL`. |

---

## 4. Frame & Packet Structures

### 4.1 Packet Binary Layout

Every QR frame encodes exactly one packet. The binary layout is fixed:

```
┌──────────┬──────────┬──────────────┬────────────┬──────────────┬──────────┐
│  Header  │  SID     │  Seq ID      │ Tot Frames │  Payload     │ Checksum │
│  2 bytes │  8 bytes │  4 bytes     │  4 bytes   │  Variable    │  4 bytes │
└──────────┴──────────┴──────────────┴────────────┴──────────────┴──────────┘
```

| Field | Size | Type | Description |
|---|---|---|---|
| **Header** | 2 bytes | Fixed | Magic bytes `0x56 0x4C` ("VL"). Any packet not beginning with these bytes MUST be discarded. |
| **SID** | 8 bytes | Unsigned Int 64-bit | Session ID, randomly generated at handshake. Rejects stray frames from foreign sessions. |
| **Seq ID** | 4 bytes | Unsigned Int 32-bit | Zero-indexed frame sequence number. Frame 0 is the first data frame. |
| **Total Frames** | 4 bytes | Unsigned Int 32-bit | Total count of data frames in this file's transmission. Fixed for the entire session. |
| **Payload** | Variable | Binary | Encoded file data chunk. Encoding is determined by `payload_encoding` config. Max payload size per frame: see §5.1. |
| **Checksum** | 4 bytes | CRC32 | CRC32 computed over the **Payload field only** (not the headers). |

All multi-byte integer fields are **big-endian** (network byte order).

### 4.2 Handshake Packet Layout

Handshake packets share the same Header and SID fields but use a distinct structure for the payload:

```
┌──────────┬──────────┬────────────────────────────────────────────────────┐
│  Header  │  SID     │  Handshake Payload (JSON-UTF8, variable)           │
│  2 bytes │  8 bytes │  Variable bytes                                    │
└──────────┴──────────┴────────────────────────────────────────────────────┘
```

Handshake packets do NOT include Seq ID, Total Frames, or Checksum fields. The Handshake Payload is a UTF-8 encoded JSON object (see §7).

### 4.3 Control Packet Layout

Control packets (FRAME_ACK, Status Feedback, DONE, ERROR) share the same Header and SID, followed by a compact fixed structure:

```
┌──────────┬──────────┬──────────┬────────────────────────────────────────┐
│  Header  │  SID     │  Ctrl ID │  Control Payload (variable)            │
│  2 bytes │  8 bytes │  1 byte  │  Variable                              │
└──────────┴──────────┴──────────┴────────────────────────────────────────┘
```

| Ctrl ID | Name | Description |
|---|---|---|
| `0x01` | `HANDSHAKE_READY` | Initiates session. Payload: Handshake JSON (§7.2). |
| `0x02` | `HANDSHAKE_ACK` | Confirms handshake. Payload: Handshake JSON (§7.3). |
| `0x03` | `FRAME_ACK` | (Acknowledged Mode only) Acknowledges receipt of a specific frame. Payload: 4-byte Seq ID. |
| `0x04` | `STATUS` | Feedback bitmask. Payload: Bitmask structure (§9.2). |
| `0x05` | `RETRANSMIT_DONE` | Notifies Receiver that all requested retransmissions are complete. |
| `0x06` | `SESSION_COMPLETE` | Sender has transmitted all frames and all retransmissions. Session may close. |
| `0x07` | `SESSION_ACK` | Receiver confirms successful file assembly and hash verification. |
| `0x08` | `SESSION_ABORT` | Either party terminates the session. Payload: 1-byte Error Code (§13). |

---

## 5. QR Code Rendering Rules

### 5.1 Payload Capacity per QR Version

The maximum binary capacity of a QR code depends on the version and error correction level. Implementors MUST ensure the total packet size (header + payload + checksum) does not exceed the selected version's capacity.

Reference capacities (binary mode, bytes):

| QR Version | Level L | Level M | Level Q | Level H |
|---|---|---|---|---|
| 10 | 271 | 213 | 151 | 117 |
| 15 | 520 | 412 | 290 | 223 |
| 20 | 858 | 666 | 474 | 365 |
| 25 | 1273 | 1000 | 706 | 544 |
| 30 | 1732 | 1362 | 966 | 745 |
| 40 | 2953 | 2331 | 1663 | 1273 |

The packet overhead (excluding payload) is exactly **22 bytes** (`Header` 2 + `SID` 8 + `Seq ID` 4 + `Total Frames` 4 + `Checksum` 4). For `BASE64` encoding, the payload bytes available equal `floor((capacity - 22) * 3 / 4)` of raw binary data. For `RAW_BYTES`, available raw bytes equal `capacity - 22`.

### 5.2 Anchor Square

Every data frame (not control frames) MUST include an **Anchor Square**:

- A solid filled square, 4×4 pixels (before `box_size` scaling), positioned 1 module inset from the top-left quiet zone boundary.
- The fill color alternates between solid black and solid white on each successive frame (frame 0 = black, frame 1 = white, frame 2 = black, …).
- The Anchor Square is rendered **after** the QR code image is generated, as an overlay drawn directly onto the output image buffer.
- **Purpose:** The Receiver monitors this square to detect frame transitions, even if the QR content itself is identical between retransmissions.

### 5.3 Rendering Image Format

- Output format: **PNG** (lossless). JPEG MUST NOT be used for QR code frames due to compression artifacts at module boundaries.
- Color depth: **1-bit (black and white)**, or **8-bit grayscale**. RGB color is permitted but carries no benefit.
- The Anchor Square region MUST be excluded from the QR error correction area (it is a post-render overlay and is not decoded as QR data).

---

## 6. Session Lifecycle & State Machine

### 6.1 Endpoint States

Each endpoint maintains its own independent state machine:

```
          ┌─────────────────────────────────────────────────────┐
          │                  IDLE                               │
          └───────────────────┬─────────────────────────────────┘
                              │ Begin session
                              ▼
          ┌─────────────────────────────────────────────────────┐
          │              HANDSHAKING                            │
          │  Displaying READY QR / Awaiting opposing READY QR   │
          └───────────────────┬─────────────────────────────────┘
                              │ Both READY QRs scanned & validated
                              ▼
          ┌─────────────────────────────────────────────────────┐
          │              CONFIRMING                             │
          │  Displaying ACK QR / Awaiting opposing ACK QR       │
          └───────────────────┬─────────────────────────────────┘
                              │ Both ACK QRs scanned & validated
                              ▼
          ┌─────────────────────────────────────────────────────┐
          │              STREAMING                              │
          │  (Sender) Displaying data frames                    │
          │  (Receiver) Capturing frames, updating bitmask,     │
          │             displaying Feedback Status QR           │
          └───────────────────┬─────────────────────────────────┘
                              │ All N frames transmitted
                              ▼
          ┌─────────────────────────────────────────────────────┐
          │              RECOVERING                             │
          │  Sender reads Feedback QR, retransmits missing      │
          │  frames, displays RETRANSMIT_DONE when complete     │
          └───────────────────┬─────────────────────────────────┘
                              │ Receiver confirms bitmask all-ones
                              ▼
          ┌─────────────────────────────────────────────────────┐
          │              COMPLETING                             │
          │  Receiver assembles file, verifies hash,            │
          │  Sender displays SESSION_COMPLETE                   │
          └───────────────────┬─────────────────────────────────┘
                              │ SESSION_ACK received by Sender
                              ▼
          ┌─────────────────────────────────────────────────────┐
          │               DONE / ABORTED                        │
          └─────────────────────────────────────────────────────┘
```

At any state, either party MAY display `SESSION_ABORT` to immediately terminate the session. The opposing party MUST enter the `ABORTED` state upon reading an abort packet.

---

## 7. Phase 1 — Handshake

### 7.1 Purpose

The handshake phase establishes the session, exchanges file metadata, negotiates streaming parameters, and confirms both parties are ready before any data frame is sent.

### 7.2 READY Packet Payload (JSON)

Each endpoint displays a READY QR code (Ctrl ID `0x01`) containing the following JSON object:

```json
{
  "vlp_version": "1.0",
  "sid": "<8-byte hex string, e.g. A3F0C1D2E4B56789>",
  "file": {
    "name": "<filename with extension, UTF-8>",
    "size_bytes": 1048576,
    "sha256": "<lowercase hex SHA-256 of the complete file>",
    "total_frames": 512
  },
  "sender_config": {
    "streaming_mode": "PACED",
    "frame_interval_ms": 150,
    "stream_qr_version": 15,
    "stream_qr_error_correction": "M",
    "stream_qr_box_size": 10,
    "stream_qr_border": 4,
    "payload_encoding": "BASE64"
  },
  "receiver_config": {
    "control_qr_version": 5,
    "control_qr_error_correction": "Q",
    "control_qr_box_size": 8,
    "control_qr_border": 4,
    "feedback_position": "BOTTOM_RIGHT",
    "feedback_interval_ms": 500
  }
}
```

**Field Rules:**
- `sid`: Each endpoint independently generates its own 8-byte random Session ID. **Both SIDs coexist independently**; they do not need to match.
- `file.total_frames`: Pre-computed before transmission. MUST match the actual number of data frames that will be sent.
- `file.sha256`: Computed over the raw unmodified source file. Used by the Receiver for final assembly verification.
- Both `sender_config` and `receiver_config` fields MUST be present; missing fields indicate a non-conforming implementation.

### 7.3 Handshake Validation

Upon receiving the opposing endpoint's READY QR:

1. **VLP Version Check:** If `vlp_version` does not match the local implementation's supported version, abort with `ERR_VERSION_MISMATCH`.
2. **SID Storage:** Record the opposing SID. All subsequent packets from that endpoint must carry this SID.
3. **Config Compatibility Check:** Verify the opposing `sender_config.stream_qr_version` and `stream_qr_box_size` are renderable by the local camera and display. If not, abort with `ERR_CONFIG_INCOMPATIBLE`.
4. **Cache Pre-allocation:** Using `file.total_frames` and `file.size_bytes`, pre-allocate the receiver cache (see §11). If allocation fails, abort with `ERR_CACHE_FULL`.
5. **Display ACK:** Display a HANDSHAKE_ACK QR (Ctrl ID `0x02`) using local `receiver_config`.

### 7.4 ACK Packet Payload (JSON)

```json
{
  "vlp_version": "1.0",
  "sid": "<the local endpoint's own SID>",
  "status": "ACK",
  "opposing_sid": "<the SID read from the opposing READY QR>",
  "cache_ready": true,
  "frame_buffer_allocated": 512
}
```

- `opposing_sid`: Echoed back as confirmation of receipt.
- `frame_buffer_allocated`: MUST equal `file.total_frames` from the opposing READY packet.

### 7.5 Handshake Completion

The handshake is complete when **both** of the following conditions are met:
1. The local endpoint has displayed its own READY QR and received a valid HANDSHAKE_ACK from the opposing side that includes the correct `opposing_sid`.
2. The local endpoint has also displayed its own HANDSHAKE_ACK.

Only after both conditions are satisfied does either party transition to the `STREAMING` state. If either condition is not met within `handshake_timeout_ms` (default: 30,000 ms), the session aborts with `ERR_HANDSHAKE_TIMEOUT`.

---

## 8. Phase 2 — Data Streaming

### 8.1 Frame Sequence

The Sender MUST transmit frames in sequential order from Seq ID `0` to `N-1` during the initial pass. Re-transmissions during recovery MAY be in any order.

For each frame `i`:
1. Encode the raw file chunk corresponding to Seq ID `i` using the configured `payload_encoding`.
2. Assemble the full packet binary (§4.1) and encode into a QR image (§5).
3. Overlay the Anchor Square (§5.2), toggling its color based on frame parity.
4. Display the QR image on screen.

### 8.2 Paced Mode Advancement

```
Display frame i
    │
    └──► Hold for frame_interval_ms
              │
              └──► Advance to frame i+1
```

The Sender does NOT read the Receiver's Feedback QR during Paced Mode streaming. The Feedback QR is only read after all N frames have been displayed (entering the RECOVERING phase). This maximizes frame throughput.

### 8.3 Acknowledged Mode Advancement

```
Display frame i
    │
    └──► Poll opposing screen for FRAME_ACK (Ctrl ID 0x03) with Seq ID == i
              │
    ┌─────────┴──────────────────────────────┐
    │ ACK received within ack_timeout_ms     │ Timeout
    ▼                                        ▼
Advance to frame i+1              Increment retry counter
                                      │
                              ┌───────┴──────────────────┐
                              │ Retries < max_ack_retries │ Retries >= max_ack_retries
                              ▼                           ▼
                     Re-display frame i          Abort: ERR_ACK_TIMEOUT
```

The FRAME_ACK packet carries the Seq ID of the frame being acknowledged. The Receiver MUST display the FRAME_ACK within `feedback_interval_ms` after a successful decode. The Receiver's Feedback QR area is used for FRAME_ACK display in Acknowledged Mode.

### 8.4 Receiver Capture Loop

The Receiver runs a continuous capture loop independently of the Sender's timing:

1. **Capture** a frame from the camera at the highest feasible capture rate.
2. **Detect Screen Region:** Apply perspective transformation to flatten any keystoning or angle distortion on the detected screen rectangle.
3. **Binarize:** Apply Otsu's thresholding to convert the captured image to pure black-and-white.
4. **Anchor Square Check:** Before QR decoding, check the Anchor Square region. If the Anchor Square color has not changed since the last capture, discard this capture (same frame still displayed).
5. **QR Decode:** Attempt to decode the binarized image as a QR code.
6. **Packet Validation:**
   a. Verify Magic Bytes `0x564C`.
   b. Verify SID matches the opposing endpoint's SID from the handshake.
   c. Verify Ctrl ID is `0x00` (data frame).
   d. Verify `Total Frames` matches the pre-negotiated count.
   e. Compute CRC32 over the decoded payload. If mismatch, log the frame as `CORRUPT` and do **not** write it to the cache.
7. **Cache Write:** If all validations pass, write the payload to the cache at the position for `Seq ID` (see §11).
8. **Bitmask Update:** Mark the frame's bit in the local received-frame bitmask as `1` (received).

### 8.5 Concurrent Display Layout

Both endpoints display content simultaneously. The screen layout MUST follow this partitioning:

```
┌─────────────────────────────────────────────────────┐
│                                                     │
│          MAIN STREAM QR (Full / Large)              │
│         Sender's data frames displayed here         │
│                                                     │
│                                                     │
│                           ┌────────────────────────┐│
│                           │  FEEDBACK QR (Small)   ││
│                           │  Receiver's Status QR  ││
│                           └────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

- The Feedback QR region MUST NOT overlap the Main Stream QR region.
- The Feedback QR MUST be at minimum 10% of the shortest screen dimension in size (e.g., on a 1080p display, at least 108px × 108px).
- The Feedback QR position is determined by the local endpoint's `feedback_position` configuration.

---

## 9. Phase 3 — Error Recovery (Feedback Loop)

### 9.1 Transition to Recovery

The Sender transitions to `RECOVERING` after the last data frame (Seq ID `N-1`) has been displayed. At this point, the Sender:
1. Stops displaying data frames.
2. Begins actively scanning the opposing endpoint's Feedback QR.
3. Reads the latest STATUS packet to obtain the missing-frame bitmask.

### 9.2 Status Feedback Packet Structure

The Feedback STATUS payload (Ctrl ID `0x04`) is a binary structure:

```
┌────────────────┬────────────────┬────────────────────────────────────────┐
│  SID           │  Total Frames  │  Bitmask                               │
│  8 bytes       │  4 bytes       │  ceil(Total Frames / 8) bytes          │
└────────────────┴────────────────┴────────────────────────────────────────┘
```

**Bitmask Encoding:**
- The bitmask is a packed bit array, one bit per frame, starting from Seq ID 0 at the most significant bit of byte 0.
- A bit value of `1` means the frame at that Seq ID was received and validated.
- A bit value of `0` means the frame is missing or corrupt.
- Padding bits in the last byte (if `Total Frames` is not a multiple of 8) are set to `1` (treated as "received") to avoid false retransmission requests.

**Example:** 5 frames total, frames 1 and 3 are missing:
```
Byte 0 bits: [1][0][1][0][1][1][1][1]
              F0  F1  F2  F3  F4  pad pad pad
```

### 9.3 Retransmission Procedure

Upon reading the STATUS packet, the Sender:
1. Extracts the list of all Seq IDs where the bitmask bit is `0`.
2. Retransmits those frames in ascending order using the same QR configuration as the original stream.
3. After all retransmitted frames are displayed, the Sender reads the Feedback QR again.
4. Steps 1–3 repeat until one of the following:
   a. The Feedback QR bitmask shows all bits set to `1` → Success. Advance to §10.
   b. The number of recovery rounds exceeds `max_recovery_rounds` (default: `10`) → Abort with `ERR_MAX_RECOVERY_EXCEEDED`.
   c. The Feedback QR is not readable within `recovery_scan_timeout_ms` (default: `10,000` ms) → Abort with `ERR_FEEDBACK_TIMEOUT`.

### 9.4 Receiver Behavior During Recovery

The Receiver continues its capture loop unchanged during recovery. As retransmitted frames arrive and are validated:
- The cache is updated with the new payloads (overwriting any previously corrupt slot).
- The bitmask is updated.
- The Feedback QR is refreshed at `feedback_interval_ms` intervals.

The Receiver does not need to distinguish between initial-pass frames and retransmission frames; all incoming data frames are processed identically by the capture loop.

---

## 10. Phase 4 — Completion & Teardown

### 10.1 Sender Side

When the Sender receives a STATUS packet with all bitmask bits set to `1`:
1. Display a `SESSION_COMPLETE` control QR (Ctrl ID `0x06`) for a minimum of `3 × frame_interval_ms` duration to ensure the Receiver can scan it.
2. Await a `SESSION_ACK` (Ctrl ID `0x07`) from the Receiver.
3. If `SESSION_ACK` is received → session DONE.
4. If no `SESSION_ACK` is received within `completion_timeout_ms` (default: `15,000` ms) → Display `SESSION_COMPLETE` again (up to 3 times). If still no ACK → mark session as `DONE_UNCONFIRMED` and clean up.

### 10.2 Receiver Side

When the Receiver's bitmask is all-ones:
1. Assemble the complete file from the cache (see §11.4).
2. Compute SHA-256 of the assembled file.
3. Compare against the `file.sha256` received during handshake.
4. If hashes match:
   - Write the assembled file to the target output path.
   - Display `SESSION_ACK` (Ctrl ID `0x07`).
   - Clean up the cache directory (see §11.5).
   - Session DONE.
5. If hashes do not match:
   - Abort with `ERR_HASH_MISMATCH`.
   - The cache directory is preserved for diagnostic purposes.

### 10.3 Simultaneous Completion

Because both endpoints operate as Sender and Receiver simultaneously, each endpoint runs Phases 2–4 independently in both roles. An endpoint may reach DONE in its Sender role while still in RECOVERING in its Receiver role. This is expected behavior; the two roles do not block each other.

---

## 11. Cache Management (Receiver Temp Storage)

### 11.1 Cache Directory Structure

For each active session, the Receiver creates a subdirectory within the configured `cache_directory`:

```
{cache_directory}/
└── vlp_{opposing_sid}/
    ├── session.json
    └── frames/
        ├── 0000000000.frm
        ├── 0000000001.frm
        ├── 0000000002.frm
        └── ...
```

| Path | Description |
|---|---|
| `vlp_{opposing_sid}/` | Session root directory. Named using the **opposing** endpoint's SID (8-byte hex). Enables identification if multiple sessions existed on the same device. |
| `session.json` | Session metadata file (see §11.2). Created at handshake completion. |
| `frames/` | Directory holding one file per frame. |
| `frames/{seq_id_10digits}.frm` | Binary frame payload. Filename is the zero-padded 10-digit decimal Seq ID. Content is the raw decoded payload bytes (pre-CRC32 verification; only valid frames are written). |

### 11.2 `session.json` Schema

Written immediately after a successful handshake:

```json
{
  "vlp_version": "1.0",
  "created_at_utc": "<ISO 8601 UTC timestamp>",
  "opposing_sid": "<hex>",
  "local_sid": "<hex>",
  "file": {
    "name": "<filename>",
    "size_bytes": 1048576,
    "sha256": "<hex>",
    "total_frames": 512
  },
  "streaming_mode": "PACED",
  "payload_encoding": "BASE64",
  "received_frame_count": 0,
  "bitmask_hex": "<hex representation of current bitmask>",
  "state": "STREAMING"
}
```

`session.json` is updated on every state transition and whenever `received_frame_count` or `bitmask_hex` changes. This allows session resumption after an unexpected interruption (see §11.6).

### 11.3 Frame File Write Rules

- A `.frm` file is only written if the CRC32 check for that Seq ID passed.
- Writing is **atomic**: data MUST be written to a temporary file (e.g., `{seq_id}.frm.tmp`) first, then renamed to the final `.frm` filename. This prevents reading a partially written frame.
- If a `.frm` file already exists for a Seq ID (received in initial pass) and a retransmission arrives that also passes CRC32, the existing file MUST be overwritten atomically.
- Partial `.tmp` files left by an interrupted write MUST be deleted at the start of the capture loop initialization.

### 11.4 File Assembly

When the bitmask is all-ones, the Receiver assembles the output file:

1. Open a new output file in write mode at the target output path.
2. Iterate Seq IDs from `0` to `N-1` in order.
3. For each Seq ID, open the corresponding `.frm` file and append its payload bytes to the output file.
4. Close the output file.
5. Verify the output file's SHA-256 hash.

The assembled output file MUST be written to a separate location from the cache directory. The cache is temporary working storage only.

### 11.5 Cache Cleanup

Upon successful session completion (SHA-256 verified), the cache subdirectory MUST be deleted, including all `.frm` files, `session.json`, and the `frames/` subdirectory.

Cleanup MUST NOT occur before `SESSION_ACK` is displayed, to ensure the frame data is available for any final re-scan.

### 11.6 Session Resumption

If a session is interrupted (application crash, device restart) before completion, the cache directory and `session.json` persist. An implementation MAY offer session resumption:

1. On startup, scan `cache_directory` for any `vlp_*/session.json` files.
2. For sessions with `state` not equal to `DONE`, prompt the user to resume or discard.
3. If resuming: re-enter the RECOVERING phase using the existing bitmask, requesting only the frames whose `.frm` files are absent.

Session resumption is OPTIONAL for conforming implementations. If not supported, stale session directories SHOULD be cleaned up on startup.

---

## 12. Timeout & Retry Policy

| Timeout Parameter | Default | Applies To | Abort Code |
|---|---|---|---|
| `handshake_timeout_ms` | 30,000 | Awaiting opposing READY or ACK QR | `ERR_HANDSHAKE_TIMEOUT` |
| `frame_interval_ms` | 150 | Paced Mode: time held per data frame | — |
| `ack_timeout_ms` | 3,000 | Acknowledged Mode: wait for FRAME_ACK | `ERR_ACK_TIMEOUT` |
| `max_ack_retries` | 5 | Acknowledged Mode: per-frame retry limit | `ERR_ACK_TIMEOUT` |
| `feedback_scan_timeout_ms` | 10,000 | Recovery: wait to read Feedback QR | `ERR_FEEDBACK_TIMEOUT` |
| `max_recovery_rounds` | 10 | Total allowed retransmission passes | `ERR_MAX_RECOVERY_EXCEEDED` |
| `completion_timeout_ms` | 15,000 | Awaiting SESSION_ACK after DONE | Session closes as `DONE_UNCONFIRMED` |

All timeout values are in milliseconds and MAY be overridden by configuration, subject to the following minimums:

| Parameter | Minimum |
|---|---|
| `frame_interval_ms` | 80 |
| `ack_timeout_ms` | 500 |
| `handshake_timeout_ms` | 5,000 |
| `completion_timeout_ms` | 5,000 |

---

## 13. Error Codes & Diagnostics

| Code | Hex | Description | Recovery |
|---|---|---|---|
| `ERR_VERSION_MISMATCH` | `0x01` | Opposing VLP version not supported. | Abort. |
| `ERR_CONFIG_INCOMPATIBLE` | `0x02` | Opposing sender config unrenderable. | Abort. |
| `ERR_HANDSHAKE_TIMEOUT` | `0x03` | Handshake not completed within timeout. | Retry from IDLE. |
| `ERR_SID_MISMATCH` | `0x04` | Incoming packet SID does not match expected. | Discard packet; continue. |
| `ERR_MAGIC_INVALID` | `0x05` | Packet does not begin with magic bytes. | Discard packet; continue. |
| `ERR_CRC_FAIL` | `0x06` | Payload CRC32 mismatch. | Log frame as CORRUPT; continue. |
| `ERR_ACK_TIMEOUT` | `0x07` | FRAME_ACK not received within retries (Acknowledged Mode). | Abort. |
| `ERR_FEEDBACK_TIMEOUT` | `0x08` | Feedback QR not readable during recovery. | Abort. |
| `ERR_MAX_RECOVERY_EXCEEDED` | `0x09` | Too many recovery rounds; frames still missing. | Abort. |
| `ERR_CACHE_FULL` | `0x0A` | Cache directory exceeded `max_cache_size_mb`. | Abort. Increase limit or free space. |
| `ERR_CACHE_WRITE_FAIL` | `0x0B` | Filesystem write to cache directory failed. | Abort. |
| `ERR_HASH_MISMATCH` | `0x0C` | Assembled file SHA-256 does not match metadata. | Abort. Cache preserved. |
| `ERR_TOTAL_FRAMES_MISMATCH` | `0x0D` | Incoming packet's `Total Frames` differs from handshake. | Abort. |
| `ERR_REMOTE_ABORT` | `0x0E` | Opposing endpoint sent SESSION_ABORT. | Clean up and halt. |

When a fatal error occurs, the affected endpoint:
1. Displays `SESSION_ABORT` QR with the relevant 1-byte error code as payload.
2. Preserves the cache directory if `ERR_HASH_MISMATCH` or `ERR_CRC_FAIL` was the cause.
3. Deletes the cache directory for all other abort reasons.
4. Transitions to `ABORTED` state.

---

## 14. Security Considerations

### 14.1 Session Isolation

The Session ID (SID) is generated fresh using a cryptographically random 8-byte value for every session. Packets carrying an unrecognized SID MUST be silently discarded, protecting against frame injection from a nearby concurrent VLP session.

### 14.2 Integrity Verification

CRC32 provides error detection, not cryptographic authentication. For sensitive data transmissions, implementors SHOULD:
- Replace or supplement SHA-256 file verification (Phase 4) with a keyed HMAC.
- Derive the HMAC key out-of-band (e.g., via QR scanning before session start or manual passphrase entry).

### 14.3 Privacy of Transmitted Data

VLP frames are displayed on screens and may be visible to bystanders. Implementors handling private data SHOULD encrypt the file before segmentation, so that individual QR frames do not expose plaintext data even if visually captured by an unintended observer.

### 14.4 Cache Security

The `cache_directory` stores raw file chunks on disk during transmission. Implementors MUST ensure:
- The cache directory has filesystem permissions restricting access to the running process or user only.
- On `SESSION_ABORT`, any partial data in the cache SHOULD be securely deleted (overwritten with zeros before deletion) when the data is sensitive.

---

## 15. Conformance Requirements

A conforming VLP implementation MUST:

1. Support all packet types defined in §4.3.
2. Implement both PACED and ACKNOWLEDGED streaming modes (§2.3).
3. Implement the Anchor Square mechanism (§5.2).
4. Apply perspective transformation and Otsu's thresholding on the capture side (§8.4).
5. Implement the full bitmask feedback and Selective Repeat ARQ recovery procedure (§9).
6. Store receiver cache as specified in §11, including atomic frame file writes.
7. Update `session.json` on every state transition.
8. Enforce all timeout policies in §12.
9. Use the Magic Bytes `0x564C` in all packets.
10. Use big-endian byte order for all multi-byte integer fields.
11. Use PNG format for all rendered QR frames.
12. Verify file SHA-256 after assembly.

A conforming VLP implementation MAY:

1. Implement session resumption (§11.6).
2. Support `RAW_BYTES` payload encoding in addition to `BASE64`.
3. Implement HMAC-based authentication (§14.2).
4. Implement pre-transmission file encryption (§14.3).
5. Support QR versions outside the recommended range (10–20) provided capacity constraints in §5.1 are respected.

---

*End of VLP Specification v1.0*