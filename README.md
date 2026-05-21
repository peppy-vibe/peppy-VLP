# VLP — Visual Link Protocol

A Python implementation of the Visual Link Protocol (VLP) v1.0.
Transfers files between two devices using only cameras and displays via QR codes.

## Quick Start

```bash
conda activate vlp
pip install -e ".[dev]"

# Full-duplex transfer (both endpoints run simultaneously)
python -m vlp transfer my_file.bin received_file.bin \
    --cache-dir /tmp/vlp_cache \
    --camera-index 0

# Sender only
python -m vlp send my_file.bin --camera-index 0

# Receiver only
python -m vlp receive output.bin --cache-dir /tmp/vlp_cache
```

## Options

```
--camera-index INT          Camera device index (default: 0)
--cache-dir PATH            Required for receiver role
--streaming-mode            PACED|ACKNOWLEDGED (default: PACED)
--frame-interval-ms INT     ms per frame in paced mode (default: 150)
--qr-version INT            QR version 1-40 (default: 10)
--qr-ec LEVEL               M|Q|H (default: M)
--feedback-position CORNER  BOTTOM_RIGHT|BOTTOM_LEFT|TOP_RIGHT|TOP_LEFT
--max-cache-mb INT          Max cache size in MB (default: 512)
--resume                    Attempt to resume an interrupted session
```

## Running Tests

```bash
pytest --cov=vlp
```
