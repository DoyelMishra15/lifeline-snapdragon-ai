#!/usr/bin/env python3
"""
Benchmark script for lib/onnx_ocr.py — meant to be run BY YOU on real
Snapdragon-powered HP hardware to get real numbers for the submission.
This repo does not ship any benchmark numbers itself; none have been
fabricated (see docs/snapdragon-optimization.md).

Usage:
    cd backend
    pip install -r requirements-dev.txt -r requirements-snapdragon.txt
    python tools/onnx_ocr_benchmark.py path/to/document-photo.png [--runs 20]
    python tools/onnx_ocr_benchmark.py path/to/document-photo.png --mode qnn
    python tools/onnx_ocr_benchmark.py path/to/document-photo.png --mode cpu --runs 20

`--mode` (default: "auto") sets the OCR execution mode for this run —
see lib/qnn_execution.py. Run once with `--mode qnn` and once with
`--mode cpu` on the same Snapdragon device to get a genuine NPU-vs-CPU
latency comparison for the submission, rather than trusting "auto" to
have picked NPU.

Reports, honestly:
  - the ONNX Runtime execution providers actually available on this
    machine (this is the only place "does this see the Snapdragon NPU"
    can be answered — if you have installed the ARM64-only
    `onnxruntime-qnn` package and it is not listed, QNN is not active)
  - the execution provider the loaded model sessions are ACTUALLY
    running under for this run (queried live from onnxruntime after
    the engine is built — never assumed from the requested mode)
  - model load time (first-call cost, done once)
  - per-run inference latency: min / median / mean / max over N runs
  - recognized text, so you can sanity-check accuracy alongside speed

Does NOT report: CPU/NPU utilization or memory (no dependency-free,
cross-platform way to measure that here) or any comparison to Bedrock
cloud latency (that depends on your network and AWS region — measure
it separately with the real deployed API if you want a side-by-side
number for the demo).
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from lib import onnx_ocr  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_path", help="Path to a document image (PNG/JPEG/WebP)")
    parser.add_argument("--runs", type=int, default=10, help="Number of timed inference runs (default: 10)")
    parser.add_argument("--mode", choices=["auto", "qnn", "cpu"], default="auto",
                         help="OCR execution mode (default: auto). See lib/qnn_execution.py.")
    args = parser.parse_args()

    if not os.path.isfile(args.image_path):
        print(f"No such file: {args.image_path}", file=sys.stderr)
        return 1

    with open(args.image_path, "rb") as f:
        image_bytes = f.read()

    try:
        providers = onnx_ocr.available_execution_providers()
    except onnx_ocr.OnnxOcrError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("=" * 70)
    print("LifeLine — on-device ONNX OCR benchmark")
    print("=" * 70)
    print(f"Image:                       {args.image_path}")
    print(f"Requested execution mode:    {args.mode}")
    print(f"Runs:                        {args.runs}")
    print(f"ONNX Runtime providers:      {providers}")
    print("  -> If you expected QNNExecutionProvider (Snapdragon NPU) here and")
    print("     don't see it: it requires the ARM64-only `onnxruntime-qnn`")
    print("     package on Windows on Snapdragon. This benchmark reports whatever")
    print("     ONNX Runtime actually finds on YOUR machine — nothing is assumed.")
    print("-" * 70)

    # Model load (lazy singleton in lib/onnx_ocr.py, keyed by mode) happens
    # on first call for this mode — time it separately from steady-state
    # inference latency.
    t0 = time.time()
    try:
        text = onnx_ocr.extract_text_from_image(image_bytes, mode=args.mode)
    except onnx_ocr.OnnxOcrError as e:
        print(f"FAILED to build the OCR engine under --mode {args.mode}: {e}", file=sys.stderr)
        if getattr(e, "reason", None) == "qnn_unavailable":
            print("(QNNExecutionProvider is not registered in this ONNX Runtime build — "
                  "install onnxruntime-qnn on Windows-on-Snapdragon, or use --mode auto/cpu "
                  "here.)", file=sys.stderr)
        elif getattr(e, "reason", None) == "qnn_session_failed":
            print("(QNNExecutionProvider IS registered, but creating a real session under "
                  "it failed — check LIFELINE_QNN_BACKEND_PATH and that an NPU/driver is "
                  "actually present.)", file=sys.stderr)
        return 1
    first_call_s = time.time() - t0

    status = onnx_ocr.runtime_status(mode=args.mode)
    print(f"ACTIVE execution provider:   {status['engine_active_provider']}")
    if status["engine_active_provider"] == "QNNExecutionProvider":
        print("  -> This run is genuinely executing on the Snapdragon NPU.")
    else:
        print("  -> This run is CPU-only (not NPU-accelerated).")
    print("-" * 70)

    print(f"First call (model load + inference): {first_call_s:.3f}s")
    print(f"Recognized text:\n{text}\n")

    timings = []
    for i in range(args.runs):
        t0 = time.time()
        onnx_ocr.extract_text_from_image(image_bytes, mode=args.mode)
        timings.append(time.time() - t0)

    print("-" * 70)
    print(f"Steady-state inference latency over {args.runs} runs on "
          f"{status['engine_active_provider']} (model already loaded):")
    print(f"  min:    {min(timings):.3f}s")
    print(f"  median: {statistics.median(timings):.3f}s")
    print(f"  mean:   {statistics.mean(timings):.3f}s")
    print(f"  max:    {max(timings):.3f}s")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
