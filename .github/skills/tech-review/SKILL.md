---
name: tech-review
description: "Comprehensive technical review of the VLP (Visual Link Protocol) codebase. Use when: conducting code review; auditing security; assessing architecture; reviewing production-readiness; finding bugs; evaluating test coverage; generating a tech review report; reviewing threading or concurrency; reviewing QR protocol correctness; generating improvement roadmap."
argument-hint: "Optional: focus area (e.g., security, threading, protocol-correctness, performance)"
---

# VLP Technical Review

You are a principal software engineer reviewing **peppy-VLP** — a Visual Link Protocol that transfers files between two devices using only cameras and screens via QR codes. Python ≥3.11. Key dependencies: `qrcode[pil]`, `Pillow`, `opencv-python`, `zxingcpp`, `numpy`, `pyzbar` (test fallback).

## Project Map (read before analysing)

| Module | Role |
|---|---|
| `vlp/constants.py` | Magic bytes, control IDs, error codes, session states |
| `vlp/exceptions.py` | Exception hierarchy keyed on error codes |
| `vlp/config.py` | Frozen dataclasses: `SenderConfig`, `ReceiverConfig`, `TimeoutConfig` |
| `vlp/packet.py` | Binary encode/decode for data + control packets; CRC32; QR capacity table |
| `vlp/bitmask.py` | Bit-packed frame-received tracking with MSB-first serialisation |
| `vlp/qr_renderer.py` | QR image generation; Anchor Square overlay for frame-change detection |
| `vlp/image_processor.py` | Camera frame pipeline: screen detection → perspective transform → Otsu binarise → anchor read |
| `vlp/qr_scanner.py` | OpenCV capture + dual-decoder (zxingcpp primary, pyzbar fallback) |
| `vlp/cache.py` | Session cache: atomic frame writes, session.json, assembly, resume |
| `vlp/handshake.py` | Phase 1: bidirectional READY/ACK negotiation across two threads |
| `vlp/sender.py` | Phases 2–4: PACED/ACKNOWLEDGED streaming → recovery → SESSION_COMPLETE |
| `vlp/receiver.py` | Concurrent capture loop + feedback loop → assembly + SHA-256 verify |
| `vlp/session.py` | Orchestrator: spawns Sender + Receiver threads; owns Tk main thread |
| `vlp/display.py` | Tkinter fullscreen window; thread-safe queue-based update system |
| `vlp/cli.py` | `send` / `receive` / `transfer` subcommands |

---

## When to Use
- Protocol correctness audits (packet encoding, state machine, bitmask, handshake)
- Threading and race-condition review (Sender/Receiver/display/abort_event interactions)
- Security reviews (no encryption, peer auth, cache path traversal, CRC vs. cryptographic auth)
- Performance audits (QR pipeline throughput, anchor optimisation, Base64 overhead)
- Test coverage gaps (recovery phase, session resume, CLI, real camera/display paths)
- Pre-release readiness checks

---

## Phase 1 — Read the Codebase

Read every file in `vlp/` and `tests/`, plus `pyproject.toml`, `requirements.txt`, `README.md`, and `Specification.md`. Map the full protocol flow before raising issues.

---

## Phase 2 — Deep Analysis

Be specific — cite file names, line numbers, function names, and exact code snippets.

### Correctness & Bugs

Focus areas for this codebase:
- **Threading races:** `abort_event` propagation across `sender_thread`, `receiver_thread`, `handshake` sub-threads, and the Tk main thread. Check that all loops test `abort.is_set()` before blocking calls.
- **Bitmask off-by-one:** `bitmask.py` — padding bits, `missing_seq_ids()` boundary, `all_received()` when `total_frames` is an exact multiple of 8.
- **CRC32 scope:** CRC is computed over payload only (`packet.py`); verify the header fields (SID, seq_id, total_frames) are not manipulable without detection.
- **Cache path traversal:** `cache.py` — `opposing_sid` comes from a decoded QR; if it contains `../` the session directory could escape `cache_directory`. Validate and sanitise.
- **Atomic rename on non-POSIX:** `os.replace()` is atomic on POSIX but not on Windows; flag if cross-platform support is intended.
- **Handshake SID uniqueness:** `session.py` generates a 64-bit random SID; verify `handshake.py` correctly rejects a round-trip where `opposing_sid == local_sid`.
- **Python static analysis:** Run `mypy --strict vlp/` and treat every error as a potential runtime bug. Check for bare `except:` clauses and mutable default arguments.

### Architecture

- **Tkinter main-thread constraint:** `session.py` blocks the main thread in `display.run_mainloop()`; protocol logic runs in a background thread. Verify the background thread can signal the Tk loop to stop and that joining it has a timeout.
- **Sender/Receiver symmetry:** Both devices run both roles simultaneously. Check that `local_sid` and `opposing_sid` are never confused in `packet.py` encoding vs. `receiver.py` filtering.
- **Session-resume gap:** `cache.py` has `find_resumable_sessions()` and `cache.py` persists bitmask state, but the `--resume` CLI flag integration is incomplete. Assess correctness risk of a partial resume.
- **Config coupling:** `ReceiverConfig.cache_dir` is excluded from handshake transmission — confirm this is consistently enforced and that no other local-only fields leak into the wire format.

### Performance

- **QR pipeline hot path:** `image_processor.py` runs Canny + contour detection on every camera frame. Measure whether screen detection can be cached once locked-on, falling back only on confidence drop.
- **Base64 overhead:** `SenderConfig` defaults to BASE64 encoding (~33% overhead). Confirm `RAW_BYTES` mode is fully implemented and tested, and document the tradeoff.
- **Anchor optimisation:** `qr_scanner.py` skips QR decode when anchor is unchanged — verify this optimisation is not defeated by lighting changes causing spurious anchor flips.
- **numpy array copies:** `qr_renderer.pil_to_numpy()` — check whether unnecessary copies are made converting PIL → numpy for display vs. for scanning.

### Security

- **No encryption:** QR codes are plaintext on-screen; any camera in line-of-sight reads the full file. This is a known design constraint. Document it prominently and add a runtime warning for sensitive files.
- **No peer authentication:** The handshake validates VLP version and config but not peer identity. A MITM can respond to a READY QR with a forged ACK. Assess whether a shared-secret or ECDH key exchange is feasible within the QR payload budget.
- **CRC32 is not a MAC:** `zlib.crc32` detects accidental corruption but is not collision-resistant. An active attacker can produce a payload with the same CRC. Flag this clearly in docs; consider HMAC-SHA256 truncated to fit QR capacity.
- **Session ID entropy:** `os.urandom(8)` gives 64 bits — adequate for accidental collision prevention but not for adversarial prediction. Document this scope.
- **Cache directory traversal:** `opposing_sid` is decoded from a QR; if it contains `..` or `/`, the session root path could escape `cache_directory`. Sanitise to hex/numeric only.
- **Dependency CVEs:** Run `pip-audit` against installed packages. Run `bandit -r vlp/` for anti-patterns (insecure `subprocess`, hardcoded secrets, use of `eval`).

### Reliability & Observability

- **No structured logging:** All status output is `print()` statements. Add `logging` module with configurable levels so users can diagnose dropped frames, CRC failures, and recovery rounds.
- **Thread exception propagation:** If `sender_thread` or `receiver_thread` raises an unhandled exception, does `session.py` detect it and abort cleanly, or does the main thread hang waiting for a result that never arrives?
- **Recovery round limit:** `sender.py` has `max_recovery_rounds`; confirm what happens when the limit is reached (graceful abort vs. silent completion with missing frames).
- **Feedback loop timing:** `receiver.py` feedback thread refreshes every `feedback_refresh_interval_ms`; confirm it does not continue running after the capture loop exits.

### Maintainability

- **Magic numbers in packet.py:** Header offsets (2, 8, 4, 4, 22 bytes) are used directly; extract named constants or use `struct.calcsize()` references.
- **State strings vs. enum:** Session states in `constants.py` are plain strings; using `enum.Enum` would prevent typo bugs and enable exhaustiveness checks.
- **`--resume` flag is a stub:** `cli.py` parses `--resume` but the integration is incomplete; either implement or raise `NotImplementedError` with a clear message rather than silently ignoring it.

### Test Coverage

Known gaps to assess:
- **Recovery phase** (`sender.py` Phase 3) — is retransmission of specific missing frames tested with a realistic bitmask?
- **Session resume** — `find_resumable_sessions()` and partial-bitmask resume path have no tests.
- **CLI** (`cli.py`) — no tests for argument parsing, config construction, or error messages.
- **`display.py`** — Tkinter window not tested; at minimum test the thread-safe queue mechanism in isolation.
- **Handshake failure paths** — version mismatch, SID collision, ACK timeout; are all error branches covered?
- **Cache path traversal** — no test for malicious `opposing_sid` values.
- Run `pytest --cov=vlp --cov-report=term-missing` and include coverage percentages per module in the report.

---

## Phase 3 — Output

Write a detailed report to `notes/tech_review.md`:

```
# VLP Technical Review

## 1. Project Overview
## 2. Critical Issues (fix immediately)
## 3. Architecture Problems
## 4. Performance Problems
## 5. Security Issues
## 6. Code Quality Issues
## 7. Observability Gaps
## 8. Refactoring Examples  ← concrete before/after code, 3–5 highest-impact
## 9. Testing Strategy      ← coverage numbers + prioritised test plan
## 10. Improvement Roadmap  ← P0 (this week) / P1 (this month) / P2 (this quarter)
```

Each issue: severity label, file + line, root cause, fix with code example. Never truncate.

---

## Phase 4 — Implementation

After writing the report, implement every item in the P0, P1, and P2 roadmap.

For each change:
1. State what you are changing and why (one sentence)
2. Make the change
3. Confirm it does not break adjacent code

VLP-specific implementation notes:
- Any change to `packet.py` encoding/decoding must preserve backward-compatible magic bytes and header layout unless a version bump is explicitly part of the fix
- Threading changes must be validated against the Tkinter main-thread constraint in `session.py`
- Cache changes must preserve atomic-write semantics (`os.replace()` pattern)
- Security additions (e.g., HMAC, path sanitisation) must not inflate QR payload size beyond the capacity table in `packet.py`

After all changes, write `notes/changes.md` summarising what was implemented and flagging any decisions requiring human review before merging.

---

## Constraints
- Never truncate output — write every section in full
- Prefer working code over explanations of what code should do
- If a fix requires a decision (e.g., HMAC key management, encryption library choice), state the tradeoff and implement the safer default
- Flag anything requiring hardware (camera, second display) — describe exactly what manual verification is needed
