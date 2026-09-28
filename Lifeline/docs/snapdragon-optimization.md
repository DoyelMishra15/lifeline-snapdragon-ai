# Snapdragon on-device AI path

This document describes the `LIFELINE_AI_PROVIDER=snapdragon` provider
and its execution-mode system for Qualcomm Snapdragon NPU acceleration
via ONNX Runtime's `QNNExecutionProvider`, added for the Snapdragon®
AI Lab Build & Present Challenge. It states plainly what is genuinely
implemented and verified versus what still requires a physical
Windows-on-Snapdragon device to observe, and it does not blur that
line.

## Supported environments

This project is developed and tested primarily in **GitHub Codespaces
(Linux/x86_64)** — that is the supported development/testing
environment for everything in this repository, including this
Snapdragon/QNN path. Nothing about running this project, its handlers,
or its test suite in Codespaces requires a Snapdragon NPU, Windows
ARM64, the Qualcomm QNN SDK, `onnxruntime-qnn`, or `QnnHtp.dll`/
`libQnnHtp.so` — see "How to run it in Codespaces" below.

**Windows on Snapdragon is the production target for actual NPU
acceleration.** The QNN integration is implemented and kept
production-ready for that hardware (see "Architecture" and "Setting up
on Windows on Snapdragon" below), but this repository does not claim
QNN has been run on real hardware, and Codespaces is never made to
depend on it.

| | GitHub Codespaces (Linux/x86_64) | Windows on Snapdragon (ARM64) |
|---|---|---|
| Role | Supported dev/test environment | Production NPU target |
| `onnxruntime` package | plain `onnxruntime` (CPU) | `onnxruntime-qnn` (registers `QNNExecutionProvider`) |
| `mode=cpu` | Fully works — real OCR on `CPUExecutionProvider` | Works (for comparison benchmarking) |
| `mode=auto` | Detects QNN is unavailable, cleanly uses CPU | Prefers `QNNExecutionProvider`, falls back to CPU if it fails |
| `mode=qnn` | Fails clearly: `reason="qnn_unavailable"` (correct, expected, tested behavior — not a bug) | Runs on the NPU, or fails clearly with `reason="qnn_session_failed"` if something's misconfigured |
| Requires QNN SDK / `onnxruntime-qnn` / Windows libraries? | **No — never** | Yes, by design (that's the point) |

## What this actually is

LifeLine already had a clean seam for swapping the AI backend:
`backend/lib/ai_provider.py` dispatches to one of several modules based
on the `LIFELINE_AI_PROVIDER` environment variable, and every backend
implements the same two functions (`extract_document`,
`draft_emergency_plan`) with the same `{"ok": bool, "text": "..."}`
contract. The `snapdragon` backend goes through that exact same seam —
no handler, schema, or frontend code needed to change.

**The genuinely new thing:** `backend/lib/onnx_ocr.py` recognizes text
in document photos on-device, using an ONNX Runtime OCR pipeline
(`rapidocr-onnxruntime` on PyPI — PaddleOCR's PP-OCRv4 detection +
angle-classification + recognition models, pre-exported to ONNX and
bundled inside the package; ~16MB total, no model download at runtime,
no network call). This replaces `backend/lib/ocr.py`'s Tesseract call
for the `snapdragon` provider only — Tesseract and the `local` provider
are completely unchanged.

**On top of that, three model sessions (detector, angle-classifier,
recognizer) are wired through a real execution-mode system** —
`backend/lib/qnn_execution.py` and `backend/lib/rapidocr_qnn_session.py`
— so that on a real Snapdragon device, those sessions genuinely run
under `QNNExecutionProvider` (the Snapdragon NPU), not merely
"mentioned" or configured-but-unused. See "Architecture" below for
exactly how, and why a direct `RapidOCR(**kwargs)` call can't do this.

**Everything else is deliberately reused, not reinvented:**
`backend/lib/snapdragon_provider.py` feeds the OCR'd (or, for PDFs,
already-extracted) text into `local_reasoning.py`'s existing
regex/keyword structuring logic unchanged, and delegates
`draft_emergency_plan()` straight to `local_reasoning.py`'s existing
template engine unchanged. That logic is not a neural network, and
this document doesn't claim otherwise.

## Execution modes: auto / qnn / cpu

Set via the `LIFELINE_OCR_EXECUTION_MODE` environment variable, or an
explicit `mode=` argument to `lib/onnx_ocr.py`'s functions (mainly used
by tests and `tools/*.py`):

| Mode | Behavior |
|---|---|
| `auto` (default) | Prefer `QNNExecutionProvider`. If it isn't registered in this ONNX Runtime build, or session creation under it fails for these models, transparently fall back to `CPUExecutionProvider` — logged, never silent about *which* provider ended up active, but never an error either. This is what makes the identical code run in Codespaces/Linux (CPU) and on a real Snapdragon device (NPU) with no code change. |
| `qnn` | *Require* `QNNExecutionProvider`. Raises a clear error — never silently falls back to CPU — if QNN isn't registered at all, or if a session can't actually be created under it. Use this to *prove* NPU execution is happening, rather than trusting `auto` picked it. In Codespaces, this mode is expected to fail — that's the correct, tested behavior (see below), not something to work around. |
| `cpu` | Always `CPUExecutionProvider`. This is what makes Codespaces (and any machine with no NPU) a fully functional development/testing environment. |

The error raised in `qnn` mode carries a `.reason` that distinguishes
two genuinely different problems, rather than one generic failure:

- `qnn_unavailable` — `QNNExecutionProvider` isn't registered in this
  process at all (wrong `onnxruntime` package installed, wrong
  platform, etc). **This is what `mode=qnn` correctly produces in
  Codespaces.**
- `qnn_session_failed` — `QNNExecutionProvider` **is** registered, but
  creating a real session under it failed for this specific model
  (bad `LIFELINE_QNN_BACKEND_PATH`, no NPU/driver present, an
  incompatible model, etc). Only reachable on a machine where QNN is
  actually registered (i.e. not in Codespaces).

## Architecture

```
backend/lib/qnn_execution.py
    Pure execution-mode logic: resolves auto/qnn/cpu, builds ONNX
    Runtime provider lists + QNN provider_options from environment
    variables, and create_session() gives the per-mode guarantees
    above. No dependency on rapidocr — this module would work to
    accelerate any ONNX model.

    Deliberately split into two halves that never need hardware to
    reason about or test:
      - qnn_provider_options() / build_providers() — pure config. Only
        reads environment variables, returns plain dicts/lists, never
        imports onnxruntime, never touches hardware. Works identically
        whether run in Codespaces or on a Snapdragon device.
      - available_providers() / create_session() — the only two
        functions that actually ask ONNX Runtime what's registered, or
        try to build a real session. These are the only places "is QNN
        actually here" gets decided, and the only places that import
        onnxruntime at all (lazily, inside the function).
    This split is what backend/tests/test_qnn_execution.py exploits:
    the config half is tested directly with no mocking at all; the
    registration half is tested with onnxruntime.get_available_providers()
    and onnxruntime.InferenceSession() mocked, so QNN
    available/unavailable/failing scenarios are all covered without
    needing a Snapdragon device.

backend/lib/rapidocr_qnn_session.py
    LifelineOrtInferSession — a small, drop-in replacement for
    rapidocr_onnxruntime's own ONNX Runtime session wrapper, built on
    top of qnn_execution.py. rapidocr_onnxruntime only understands two
    provider toggles per model stage (CUDA/DirectML) — there's no
    supported way to hand it a QNNExecutionProvider provider list
    through its public RapidOCR(**kwargs) constructor (see
    rapidocr_onnxruntime.utils.parse_parameters.UpdateParameters).
    patch_rapidocr_sessions() substitutes this class in place of
    rapidocr's own inside its three model-wrapper modules
    (TextDetector/TextClassifier/TextRecognizer), so RapidOCR() picks
    it up with zero changes to rapidocr_onnxruntime itself and no
    vendored fork of it in this repo. This only reimplements the
    narrow ONNX Runtime session interface those three wrappers
    actually use (construct-with-config, call-with-ndarray, two
    metadata helpers) — none of the PP-OCRv4 pre/post-processing, box
    geometry, or CTC decoding is touched; that all stays exactly as
    rapidocr_onnxruntime already implements it.

backend/lib/onnx_ocr.py
    Public OCR API (extract_text_from_image, runtime_status,
    available_execution_providers) and the lazy engine singleton,
    keyed by resolved execution mode so switching modes across calls
    rebuilds rather than silently reusing a stale engine.

backend/lib/snapdragon_provider.py
    The ai_provider backend: OCR through the above for images, text
    extraction for PDFs (unchanged), structuring/plan-drafting via
    local_reasoning.py (unchanged). Adds runtime_status() as an extra,
    optional function beyond the shared two-function contract.
```

All of `lib/qnn_execution.py`, `lib/onnx_ocr.py`,
`lib/rapidocr_qnn_session.py`, and `lib/snapdragon_provider.py` import
`onnxruntime`/`rapidocr_onnxruntime` lazily, inside functions — never
at module import time. `import lib.ai_provider` (and therefore
importing any handler) succeeds even with neither package installed;
`backend/tests/test_codespaces_environment.py` proves this directly by
blocking both imports in a subprocess and confirming every module and
handler still imports cleanly.

## How to run it in Codespaces

Everything below runs as-is in a stock GitHub Codespace — nothing
Snapdragon/Windows-specific is required.

```bash
cd backend
pip install -r requirements-dev.txt
pip install -r requirements-snapdragon.txt   # onnxruntime (plain CPU build here) + rapidocr-onnxruntime

# Run the new/updated tests
pytest tests/test_qnn_execution.py tests/test_rapidocr_qnn_session.py \
       tests/test_onnx_ocr.py tests/test_snapdragon_provider.py \
       tests/test_ai_provider.py tests/test_codespaces_environment.py -v

# Run the full suite to confirm nothing else broke
pytest tests/ -v

# Demo: run a document photo through the real dispatch path
python tools/snapdragon_demo.py /path/to/a/document-photo.png --mode cpu
python tools/snapdragon_demo.py /path/to/a/document-photo.png --mode auto
python tools/snapdragon_demo.py /path/to/a/document-photo.png --mode qnn   # expected to fail here — see below

# Benchmark CPU performance in Codespaces (useful as a baseline to
# compare against real NPU numbers later)
python tools/onnx_ocr_benchmark.py /path/to/a/document-photo.png --mode cpu --runs 20
```

`--mode qnn` in Codespaces is *expected* to print something like:
```
ACTIVE execution provider: None
FAILED: Execution mode 'qnn' was requested but QNNExecutionProvider is not
registered in this ONNX Runtime build (available providers:
['AzureExecutionProvider', 'CPUExecutionProvider']). This requires the
Windows-ARM64 `onnxruntime-qnn` package (not the standard `onnxruntime`
package) — see docs/snapdragon-optimization.md.
```
and exit non-zero. That is the correct, tested behavior for this
environment (see `test_qnn_mode_fails_with_clear_actionable_error_in_codespaces`
in `backend/tests/test_codespaces_environment.py`) — not something to
troubleshoot away. `--mode cpu` and `--mode auto` should both succeed
and print `ACTIVE execution provider: CPUExecutionProvider`.

You do not need `requirements-snapdragon.txt` installed at all to work
on the rest of the project: `pytest tests/` with those extras absent
still runs every other test and skips only the OCR-specific ones
cleanly (via `pytest.importorskip`) — nothing fails, and no handler or
other library import breaks.

To exercise this through the full local API stack (not just the
scripts above), set `LIFELINE_AI_PROVIDER=snapdragon` (and optionally
`LIFELINE_OCR_EXECUTION_MODE`) in whatever environment-variables file
you're already using for `sam local start-api` (see
`docs/local-development.md` for how the equivalent `local` provider is
wired in) — no handler code changes are required, since `ai_provider.py`
already reads these variables at call time.

## What is verified (in Codespaces)

Run and confirmed, in this project's GitHub Codespaces environment
(Ubuntu 24.04, Linux/x86_64, Python 3.12, `onnxruntime==1.24`+,
`rapidocr-onnxruntime==1.4.4`):

- **172 tests pass** (up from the original 108 — 64 new tests added
  across this change and its Codespaces-focused follow-up),
  including:
  - `backend/tests/test_qnn_execution.py` (27 tests) — execution-mode
    resolution, provider-list construction, and every
    auto/qnn/cpu × available/unavailable/session-fails combination in
    `create_session()`, with the hardware-specific pieces
    (`onnxruntime.get_available_providers`, `InferenceSession`) mocked
    so these run without a Snapdragon device.
  - `backend/tests/test_rapidocr_qnn_session.py` (9 tests) —
    `LifelineOrtInferSession` built against one of rapidocr's own real
    bundled ONNX models (so real session construction and real
    inference are exercised, not just mocks), plus the
    `patch_rapidocr_sessions()` monkeypatch itself.
  - `backend/tests/test_onnx_ocr.py` (10 tests) — end-to-end OCR
    correctness per mode: `cpu` and `auto` genuinely recognize text
    (including dates) via `CPUExecutionProvider`; explicit `qnn` mode
    fails with `reason="qnn_unavailable"` rather than silently using
    CPU; an invalid mode string raises clearly.
  - `backend/tests/test_snapdragon_provider.py` (5 tests) and
    `backend/tests/test_ai_provider.py` (10 tests) — provider dispatch,
    document structuring, and `runtime_status()`.
  - `backend/tests/test_codespaces_environment.py` (9 tests, new) —
    the explicit Codespaces-environment proof described above: modules
    import with the Snapdragon extras completely absent, requirements
    markers resolve correctly on Linux/x86_64, `cpu`/`auto`/`qnn` modes
    each behave exactly as this document says, and choosing the
    snapdragon provider doesn't disturb the local/bedrock providers or
    handler imports.
- The full pre-existing test suite (108 tests) continues to pass
  unmodified, both with and without `requirements-snapdragon.txt`
  installed.
- `pip install -r requirements-snapdragon.txt` in Codespaces installs
  plain `onnxruntime` (confirmed via `pip show onnxruntime` and via
  `test_requirements_snapdragon_selects_plain_onnxruntime_on_linux_x86_64`)
  — never `onnxruntime-qnn`, which the same requirements file correctly
  reserves for `platform_system == "Windows" and platform_machine ==
  "ARM64"`.
- `backend/tools/snapdragon_demo.py --mode cpu|auto|qnn` and
  `backend/tools/onnx_ocr_benchmark.py --mode cpu|auto|qnn` were run
  directly (not just via pytest): `cpu`/`auto` correctly OCR a test
  image and report `ACTIVE execution provider: CPUExecutionProvider`;
  `qnn` correctly fails with the `qnn_unavailable` message and a
  non-zero exit code, rather than silently running on CPU.
- `onnxruntime.get_available_providers()` in this Codespace reports
  `["AzureExecutionProvider", "CPUExecutionProvider"]` — i.e., **no
  QNN provider registered**, exactly as expected without
  `onnxruntime-qnn` installed. This was printed, not assumed.

## What is NOT claimed, and still needs real Snapdragon hardware

1. **`QNNExecutionProvider` has never actually executed a model in
   this effort.** The provider-selection *logic* around it — resolving
   modes, building provider option dicts, requiring vs. preferring it,
   distinguishing "unavailable" from "session failed", reporting the
   active provider — is real, implemented, and tested (with the
   hardware-specific calls mocked, as described above). Whether
   `onnxruntime-qnn` actually registers `QNNExecutionProvider` on a
   real Windows-on-Snapdragon machine, and whether these specific
   ONNX graphs (PP-OCRv4 det/cls/rec) load and run correctly and
   *faster* under it, is unknown until measured there.
2. **No Snapdragon/ARM64 hardware or OS testing at all.** Everything
   above was run in GitHub Codespaces (Linux/x86_64). `pip install
   onnxruntime-qnn rapidocr-onnxruntime` has not been attempted on
   Windows ARM64 in this effort, and this repository does not claim
   otherwise anywhere, including in code comments or log messages.
3. **No latency/throughput benchmark numbers exist yet.** None have
   been fabricated. `backend/tools/onnx_ocr_benchmark.py --mode qnn`
   and `--mode cpu` are provided for you to run side-by-side on the
   actual HP Snapdragon device and get real numbers.
4. **OCR accuracy on real-world photographed documents is unverified.**
   Tests here use clean, synthetically generated text images. A
   skewed, low-light, or handwritten real document may perform worse —
   the same honest-degradation pattern the existing Tesseract path
   already documents in `docs/limitations.md` applies here too.
5. **Windows packaging is out of scope of this change.** How a judge
   would actually launch this on their HP Snapdragon PC (native
   Python? a bundled executable? through the existing
   Docker/SAM-local/LocalStack stack, which itself assumes Linux — see
   `docs/local-development.md`) has not been decided or tested.

## Setting up on Windows on Snapdragon (production hardware)

Everything in this section is **only needed on the real target
hardware** — none of it applies to, or is required by, Codespaces
development. These are the exact steps to get real NPU execution.

1. **Use an ARM64-native Python.** Install Python 3.11+ for
   Windows ARM64 from python.org (not the x64 build running under
   emulation — `onnxruntime-qnn` is an ARM64-only wheel and won't
   install under an x64 interpreter). Confirm with:
   ```powershell
   python -c "import platform; print(platform.machine())"
   ```
   This should print `ARM64`.

2. **Install the Qualcomm AI Engine Direct (QNN) SDK**, which provides
   the HTP backend libraries ONNX Runtime loads at runtime (e.g.
   `QnnHtp.dll`). Follow Qualcomm's current QNN SDK download/install
   instructions for Windows on Snapdragon; note the install directory
   containing `QnnHtp.dll` (typically under
   `.../qnn/lib/arm64x-windows-msvc/` or similar — the exact path
   depends on the SDK version you install).

3. **Make the QNN backend library discoverable.** Either add its
   directory to your `PATH`, or set:
   ```powershell
   $env:LIFELINE_QNN_BACKEND_PATH = "C:\path\to\QnnHtp.dll"
   ```

4. **Install this project's Snapdragon dependencies** — the
   requirements file's platform markers automatically select
   `onnxruntime-qnn` (not plain `onnxruntime`) on Windows ARM64:
   ```powershell
   cd backend
   pip install -r requirements.txt -r requirements-dev.txt -r requirements-snapdragon.txt
   ```
   Verify only one `onnxruntime` distribution is installed
   (`onnxruntime-qnn` and `onnxruntime` must not both be present):
   ```powershell
   pip show onnxruntime
   ```

5. **Set the execution mode and provider:**
   ```powershell
   $env:LIFELINE_AI_PROVIDER = "snapdragon"
   $env:LIFELINE_OCR_EXECUTION_MODE = "qnn"   # or "auto" for prefer-QNN-fallback-CPU
   ```

6. **Verify NPU execution is actually happening** (this is the
   verification procedure for the submission):
   ```powershell
   python tools/snapdragon_demo.py path\to\a\document-photo.png --mode qnn
   ```
   Look for:
   ```
   QNNExecutionProvider registered:  True
   ...
   ACTIVE execution provider: QNNExecutionProvider
     -> Running on the Snapdragon NPU via QNNExecutionProvider.
   ```
   If `--mode qnn` instead prints `FAILED: ... qnn_unavailable`, QNN
   isn't registered — recheck steps 1-4. If it prints `...
   qnn_session_failed`, QNN is registered but a real session couldn't
   be created — recheck `LIFELINE_QNN_BACKEND_PATH` and that an
   NPU/driver is actually present on the device.

7. **Get real latency numbers** (NPU vs. CPU, same device, same
   image):
   ```powershell
   python tools/onnx_ocr_benchmark.py path\to\a\document-photo.png --mode qnn --runs 20
   python tools/onnx_ocr_benchmark.py path\to\a\document-photo.png --mode cpu --runs 20
   ```

8. **Run the test suite** on the device (all tests still run — the
   ones exercising real QNN-unavailable behavior will now instead
   exercise the real hardware path where applicable, and everything
   else is unaffected by platform):
   ```powershell
   pytest tests\ -v
   ```

### Environment variable reference

| Variable | Default | Purpose |
|---|---|---|
| `LIFELINE_AI_PROVIDER` | `bedrock` | Set to `snapdragon` to use this provider at all. |
| `LIFELINE_OCR_EXECUTION_MODE` | `auto` | `auto` \| `qnn` \| `cpu` — see the table above. |
| `LIFELINE_QNN_BACKEND_PATH` | `QnnHtp.dll` (Windows) / `libQnnHtp.so` (else) | Path/name of the QNN HTP backend library. A bare name is resolved via the OS's normal library search path (`PATH` on Windows) — set this only if it isn't already discoverable that way. Never a hardcoded machine-specific path baked into the code, and never read/loaded at all in `cpu` mode or when `QNNExecutionProvider` isn't registered. |
| `LIFELINE_QNN_PERFORMANCE_MODE` | unset (ORT default) | Optional QNN HTP performance mode, e.g. `burst`, `high_performance`, `sustained_high_performance`, `power_saver`. |
| `LIFELINE_QNN_HTP_ARCH` | unset (auto-detected) | Optional target HTP architecture override (e.g. `73`, `68`). |

## Files changed

| File | Change |
|---|---|
| `backend/lib/qnn_execution.py` | New — execution-mode resolution + QNN/CPU session creation, config/registration split |
| `backend/lib/rapidocr_qnn_session.py` | New — wires rapidocr's ONNX sessions through the above |
| `backend/lib/onnx_ocr.py` | Rewritten — mode-aware engine, `runtime_status()`, `.reason` on errors |
| `backend/lib/snapdragon_provider.py` | Updated — adds `runtime_status()` |
| `backend/lib/ai_provider.py` | Added an optional `runtime_status()` passthrough |
| `backend/requirements-snapdragon.txt` | Updated — platform markers select `onnxruntime` (Codespaces/Linux) vs. `onnxruntime-qnn` (Windows ARM64) automatically |
| `backend/tests/test_qnn_execution.py` | New (27 tests) |
| `backend/tests/test_rapidocr_qnn_session.py` | New (9 tests) |
| `backend/tests/test_codespaces_environment.py` | New (9 tests) — explicit Codespaces-environment proof |
| `backend/tests/test_onnx_ocr.py`, `test_snapdragon_provider.py`, `test_ai_provider.py` | Extended |
| `backend/tools/snapdragon_demo.py` | Updated — `--mode` flag, reports the real active provider |
| `backend/tools/onnx_ocr_benchmark.py` | Updated — `--mode` flag, reports the real active provider |
| `docs/snapdragon-optimization.md` | Rewritten (this file) — Codespaces-first structure |
| `README.md`, `docs/architecture.md`, `docs/local-development.md`, `docs/limitations.md` | Pointers updated |

**Unchanged, deliberately:** `backend/handlers/*.py` (the existing
`ai_provider.py` abstraction already routes correctly with zero
handler edits), `backend/lib/local_reasoning.py`, `backend/lib/ocr.py`,
`backend/lib/bedrock_client.py`, `infrastructure/template.yaml`,
`docker-compose.yml`, `start.sh`, and the entire frontend.
