#!/usr/bin/env python3
"""
Judge-facing demo script for LIFELINE_AI_PROVIDER=snapdragon.

Runs a document image through the exact same lib/ai_provider.py
dispatch that backend/handlers/process.py calls in the real
application — this is not a reimplementation or a mock, it is the
production code path with LIFELINE_AI_PROVIDER=snapdragon set, going
through lib/onnx_ocr.py -> lib/rapidocr_qnn_session.py ->
lib/qnn_execution.py exactly as the API does.

Usage:
    cd backend
    pip install -r requirements-dev.txt -r requirements-snapdragon.txt
    python tools/snapdragon_demo.py path/to/document-photo.png
    python tools/snapdragon_demo.py path/to/document-photo.png --mode qnn
    python tools/snapdragon_demo.py path/to/document-photo.png --mode cpu

`--mode` (default: "auto") sets LIFELINE_OCR_EXECUTION_MODE for this
run — see lib/qnn_execution.py for the full contract:
    auto  prefer QNNExecutionProvider (Snapdragon NPU), fall back to
          CPU when it isn't available. This is the default the real
          application uses.
    qnn   require QNNExecutionProvider; fail with a clear error
          instead of silently running on CPU. Use this on a
          Windows-on-Snapdragon device to *prove* NPU execution is
          happening, rather than hoping "auto" picked it.
    cpu   always CPU. Useful for a side-by-side comparison against
          --mode qnn on the same device.

What this proves: the image is OCR'd on-device via ONNX Runtime, with
no network call of any kind, the recognized text is structured into
LifeLine's document schema by the same deterministic logic
LIFELINE_AI_PROVIDER=local already uses, and — critically — this
script prints the *actual* ONNX Runtime execution provider the model
sessions ran under (queried live from onnxruntime, never assumed).

On the x86_64 Linux machine this project was primarily developed on,
that provider is CPUExecutionProvider (`--mode qnn` fails clearly
there, as intended — see docs/snapdragon-optimization.md). On a real
Windows-on-Snapdragon device with `onnxruntime-qnn` installed and the
QNN backend libraries reachable, `--mode auto` or `--mode qnn` should
report QNNExecutionProvider here; if it doesn't, this script's output
tells you exactly why (see lib/qnn_execution.py's error reasons).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_path", help="Path to a document image (PNG/JPEG/WebP)")
    parser.add_argument("--mode", choices=["auto", "qnn", "cpu"], default="auto",
                         help="OCR execution mode (default: auto). See lib/qnn_execution.py.")
    args = parser.parse_args()

    if not os.path.isfile(args.image_path):
        print(f"No such file: {args.image_path}", file=sys.stderr)
        return 1

    os.environ["LIFELINE_AI_PROVIDER"] = "snapdragon"
    os.environ["LIFELINE_OCR_EXECUTION_MODE"] = args.mode

    from lib import ai_provider, onnx_ocr  # noqa: E402  (import after env vars are set)

    with open(args.image_path, "rb") as f:
        image_bytes = f.read()

    ext = os.path.splitext(args.image_path)[1].lower()
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".webp": "image/webp"}.get(ext, "image/png")

    try:
        diag = onnx_ocr.runtime_status(mode=args.mode)
    except onnx_ocr.OnnxOcrError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Install backend/requirements-snapdragon.txt first.", file=sys.stderr)
        return 1

    print("=" * 70)
    print("LifeLine — Snapdragon on-device provider demo")
    print("=" * 70)
    print(f"Image:                     {args.image_path}")
    print(f"Requested execution mode:  {args.mode}")
    print(f"Platform:                  {diag['platform']} / {diag['machine']}")
    print(f"ONNX Runtime providers available in this process: {diag['available_providers']}")
    print(f"QNNExecutionProvider registered:  {diag['qnn_provider_registered']}")
    if not diag["qnn_provider_registered"]:
        print("NOTE: QNNExecutionProvider (Snapdragon NPU) is NOT registered in this")
        print("      ONNX Runtime build. This requires standard `onnxruntime`")
        print("      plus the Windows-ARM64 `onnxruntime-qnn` plugin — see")
        print("      docs/snapdragon-optimization.md.")
    print("-" * 70)

    t0 = time.time()
    result = ai_provider.extract_document(image_bytes=image_bytes, image_media_type=media_type)
    elapsed = time.time() - t0

    status = ai_provider.runtime_status()

    print(f"AI provider in use:        {ai_provider.current_provider()}")
    if status is not None:
        print(f"Resolved execution mode:   {status['resolved_mode']}")
        print(f"ACTIVE execution provider: {status['engine_active_provider']}")
        if status["engine_active_provider"] == "QNNExecutionProvider":
            print("  -> Running on the Snapdragon NPU via QNNExecutionProvider.")
        elif status["engine_active_provider"] is not None:
            print("  -> NOT running on the Snapdragon NPU (CPU-only for this run).")
    print(f"Wall-clock time:           {elapsed:.3f}s (single run — see "
          f"tools/onnx_ocr_benchmark.py for real latency numbers)")
    print("-" * 70)

    if not result.get("ok"):
        print(f"FAILED: {result.get('error')}")
        if args.mode == "qnn":
            print("(--mode qnn requires QNNExecutionProvider — see the error above for why "
                  "it could not be honored: unavailable vs. configured-but-failed.)")
        return 1

    doc = json.loads(result["text"])
    print(json.dumps(doc, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
