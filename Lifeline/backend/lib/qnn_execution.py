"""
Execution-mode resolution and ONNX Runtime session creation for
Qualcomm Snapdragon NPU acceleration via `QNNExecutionProvider`.

This module is the one place that knows how to:

1. Resolve which execution mode LifeLine's on-device OCR should use —
   "auto" (prefer QNN, fall back to CPU), "qnn" (require QNN, fail
   loudly if it can't be honored), or "cpu" (always CPU, for
   development/testing on machines with no NPU at all, e.g. Codespaces
   or a plain Linux/x86_64 dev box).
2. Build the ONNX Runtime `providers` list/options for that mode.
3. Actually create an `onnxruntime.InferenceSession` under that mode,
   with the guarantees described in `create_session()` below.

Nothing here is Snapdragon-hardware-only code that "can't run" off
real hardware: every function degrades correctly on a machine that
only has `CPUExecutionProvider` (any Codespaces/Linux/x86_64 box),
which is exactly what makes it possible to unit-test this module (see
backend/tests/test_qnn_execution.py) without a Snapdragon device —
hardware-specific bits (does `QNNExecutionProvider` actually appear in
`onnxruntime.get_available_providers()`, does a real HTP backend
library load) are mocked out in tests, not skipped.

Config vs. registration — the two things this module deliberately
keeps separate, so hardware never has to be present just to reason
about or test configuration:

- `qnn_provider_options()` / `build_providers()` are pure, hardware-
  independent *configuration* — they only read environment variables
  and return plain dicts/lists describing what *would* be requested.
  They never touch `onnxruntime.get_available_providers()`, never
  construct a session, and cannot fail due to missing hardware or a
  missing QNN backend library. Calling them on a bare Codespace with
  no `onnxruntime` installed at all still works (they don't even
  import `onnxruntime`).
- `available_providers()` / `create_session()` are the only two
  functions that actually ask ONNX Runtime what's *registered* in this
  process, or try to construct a real session. These are the only
  places "is QNN actually here" gets decided, and the only places that
  import `onnxruntime` (lazily, inside the function) — so importing
  this module itself never requires `onnxruntime` to be installed; only
  calling these two functions does.

GitHub Codespaces (Linux/x86_64) is this project's supported
development and testing environment — see the "Codespaces" section of
docs/snapdragon-optimization.md. It has no Snapdragon NPU, no QNN SDK,
and no Windows-only libraries, and none of that is needed for this
module to import, for `mode="cpu"` to fully work, or for `mode="auto"`
to correctly detect QNN's absence and use CPU. `mode="qnn"` there
correctly raises ExecutionModeError(reason=REASON_QNN_UNAVAILABLE) —
that is the intended, tested behavior in this environment, not a bug
to work around.

Environment variables (all optional; see docs/snapdragon-optimization.md
for the full reference):

- LIFELINE_OCR_EXECUTION_MODE   "auto" (default) | "qnn" | "cpu"
- LIFELINE_QNN_BACKEND_PATH     Path/name of the QNN HTP backend
                                 library ONNX Runtime should load
                                 (default: "QnnHtp.dll" on Windows,
                                 "libQnnHtp.so" elsewhere — resolved
                                 by the OS's normal library search
                                 path, never a hardcoded absolute
                                 machine path). Irrelevant in
                                 Codespaces/cpu mode: this value is
                                 never read from disk or loaded unless
                                 QNNExecutionProvider is both
                                 registered and actually selected.
- LIFELINE_QNN_PERFORMANCE_MODE Optional QNN HTP performance mode,
                                 e.g. "burst", "high_performance",
                                 "sustained_high_performance",
                                 "power_saver" (see the QNN EP options
                                 reference linked below). Unset by
                                 default (leaves ONNX Runtime's own
                                 default).
- LIFELINE_QNN_HTP_ARCH         Optional target HTP architecture
                                 override (e.g. "73", "68"). Unset by
                                 default (ONNX Runtime auto-detects).

See:
https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html
"""
from __future__ import annotations

import contextlib
import logging
import os
import platform
from typing import Any

logger = logging.getLogger("lifeline.qnn_execution")

QNN_PROVIDER = "QNNExecutionProvider"
CPU_PROVIDER = "CPUExecutionProvider"
_qnn_plugin_registered = False

VALID_MODES = ("auto", "qnn", "cpu")
DEFAULT_MODE = "auto"

ENV_MODE = "LIFELINE_OCR_EXECUTION_MODE"
ENV_BACKEND_PATH = "LIFELINE_QNN_BACKEND_PATH"
ENV_PERFORMANCE_MODE = "LIFELINE_QNN_PERFORMANCE_MODE"
ENV_HTP_ARCH = "LIFELINE_QNN_HTP_ARCH"

# Reasons attached to ExecutionModeError, so callers (and tests) can
# tell "QNN isn't even registered here" apart from "QNN is registered
# but this specific session/model failed under it" without parsing
# error strings. See module docstring and lib/onnx_ocr.py.
REASON_INVALID_MODE = "invalid_mode"
REASON_QNN_UNAVAILABLE = "qnn_unavailable"
REASON_QNN_SESSION_FAILED = "qnn_session_failed"


class ExecutionModeError(Exception):
    """
    Raised when the requested OCR execution mode cannot be honored.

    `.reason` is one of REASON_INVALID_MODE, REASON_QNN_UNAVAILABLE,
    or REASON_QNN_SESSION_FAILED — see the constants above.
    """

    def __init__(self, message: str, *, reason: str):
        super().__init__(message)
        self.reason = reason


# Set by lib/onnx_ocr.py while it builds the (single, process-wide,
# lazily-constructed) RapidOCR engine, so that
# lib/rapidocr_qnn_session.py's session wrapper — instantiated deep
# inside RapidOCR()'s own constructor, with no way for us to pass it
# extra kwargs through rapidocr_onnxruntime's public API — knows which
# execution mode to build each of the three model sessions under. Only
# meaningful during that single synchronous construction call; not a
# general-purpose global execution-mode switch.
_active_mode: str | None = None


@contextlib.contextmanager
def use_mode(mode: str):
    """Scope `mode` as the active mode for the duration of the `with` block."""
    global _active_mode
    previous = _active_mode
    _active_mode = mode
    try:
        yield
    finally:
        _active_mode = previous


def get_active_mode() -> str | None:
    """The mode set by the innermost enclosing `use_mode()`, if any."""
    return _active_mode


def resolve_execution_mode(explicit: str | None = None) -> str:
    """
    Resolve the execution mode to use: `explicit` if given, else the
    LIFELINE_OCR_EXECUTION_MODE environment variable, else "auto".
    Raises ExecutionModeError(reason=REASON_INVALID_MODE) for anything
    else, rather than silently coercing an unrecognized value to a
    default — a typo'd env var should fail loudly, not quietly switch
    behavior.
    """
    raw = explicit if explicit is not None else os.environ.get(ENV_MODE, DEFAULT_MODE)
    mode = (raw or "").strip().lower()
    if mode not in VALID_MODES:
        raise ExecutionModeError(
            f"Invalid OCR execution mode {raw!r} (from "
            f"{'explicit argument' if explicit is not None else ENV_MODE}). "
            f"Must be one of {VALID_MODES}.",
            reason=REASON_INVALID_MODE,
        )
    return mode


def _default_backend_path() -> str:
    # This is a library *name*, resolved by the OS's normal dynamic
    # linker search path (PATH on Windows, LD_LIBRARY_PATH/ldconfig on
    # Linux) — never a hardcoded machine-specific absolute path. Set
    # LIFELINE_QNN_BACKEND_PATH to point at a specific install if the
    # library isn't already discoverable that way.
    return "QnnHtp.dll" if platform.system() == "Windows" else "libQnnHtp.so"


def qnn_provider_options() -> dict[str, str]:
    """
    Build the QNNExecutionProvider provider_options dict from
    environment variables, with sensible defaults. Only includes keys
    the user has actually set (beyond backend_path, which always has a
    platform-appropriate default) so ONNX Runtime's own defaults apply
    to everything else.
    """
    options: dict[str, str] = {
        "backend_path": os.environ.get(ENV_BACKEND_PATH, _default_backend_path()),
    }
    performance_mode = os.environ.get(ENV_PERFORMANCE_MODE)
    if performance_mode:
        options["htp_performance_mode"] = performance_mode
    htp_arch = os.environ.get(ENV_HTP_ARCH)
    if htp_arch:
        options["htp_arch"] = htp_arch
    return options

def _ensure_qnn_plugin_registered() -> bool:
    """
    Register the standalone onnxruntime-qnn plugin when running on
    Windows ARM64. Safe no-op everywhere else.
    """
    global _qnn_plugin_registered

    if _qnn_plugin_registered:
        return True

    if platform.system() != "Windows" or platform.machine().upper() != "ARM64":
        return False

    try:
        import onnxruntime as ort
        import onnxruntime_qnn

        if QNN_PROVIDER not in ort.get_available_providers():
            ep_lib_path = onnxruntime_qnn.get_library_path()
            ort.register_execution_provider_library(
                QNN_PROVIDER,
                ep_lib_path,
            )

        _qnn_plugin_registered = (
            QNN_PROVIDER in ort.get_available_providers()
        )
        return _qnn_plugin_registered

    except (ImportError, OSError, RuntimeError) as exc:
        logger.warning("Could not register QNN plugin: %s", exc)
        return False

def available_providers() -> list[str]:
    """Return providers currently registered with ONNX Runtime."""
    import onnxruntime

    _ensure_qnn_plugin_registered()

    return list(onnxruntime.get_available_providers())


def build_providers(mode: str) -> list[Any]:
    """
    Build the ordered `providers` argument for
    `onnxruntime.InferenceSession` for the given mode. This only
    describes what will be *requested*; it doesn't check hardware
    availability or verify anything actually loaded — that's
    `create_session()`'s job, since "was the provider list well-formed"
    and "did the hardware/backend actually come up" are different
    questions with different failure handling per mode.
    """
    if mode == "cpu":
        return [CPU_PROVIDER]
    if mode == "qnn":
        return [(QNN_PROVIDER, qnn_provider_options())]
    if mode == "auto":
        return [(QNN_PROVIDER, qnn_provider_options()), CPU_PROVIDER]
    raise ExecutionModeError(
        f"Invalid OCR execution mode {mode!r}. Must be one of {VALID_MODES}.",
        reason=REASON_INVALID_MODE,
    )


def _base_session_options(config: dict[str, Any] | None = None):
    import onnxruntime

    config = config or {}
    sess_opt = onnxruntime.SessionOptions()
    sess_opt.log_severity_level = 4
    sess_opt.enable_cpu_mem_arena = False
    sess_opt.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL

    cpu_count = os.cpu_count() or 1
    intra = config.get("intra_op_num_threads", -1)
    if intra != -1 and 1 <= intra <= cpu_count:
        sess_opt.intra_op_num_threads = intra
    inter = config.get("inter_op_num_threads", -1)
    if inter != -1 and 1 <= inter <= cpu_count:
        sess_opt.inter_op_num_threads = inter
    return sess_opt


def create_session(model_path: str, mode: str, *, config: dict[str, Any] | None = None):
    """
    Create a real `onnxruntime.InferenceSession` for `model_path`
    under the given execution mode.

    Returns (session, active_provider), where active_provider is
    whatever `session.get_providers()[0]` actually reports — never an
    assumed value.

    Per-mode guarantees:
    - "cpu": always CPUExecutionProvider. Never touches QNN, so this
      always works on Codespaces/Linux/x86_64 dev machines.
    - "qnn": the returned session is genuinely running on
      QNNExecutionProvider, or this raises ExecutionModeError — it
      NEVER silently returns a CPU session. The error's `.reason`
      distinguishes QNN not being registered at all
      (REASON_QNN_UNAVAILABLE — wrong onnxruntime package/platform)
      from QNN being registered but session creation for this specific
      model failing (REASON_QNN_SESSION_FAILED — bad backend_path, no
      NPU/driver present, an incompatible model).
    - "auto": prefers QNN, transparently falls back to CPU (either
      because QNN isn't registered, or because session creation under
      it failed) and logs which one ended up active. Never raises for
      hardware-availability reasons.
    """
    import onnxruntime

    if mode not in VALID_MODES:
        raise ExecutionModeError(
            f"Invalid OCR execution mode {mode!r}. Must be one of {VALID_MODES}.",
            reason=REASON_INVALID_MODE,
        )

    sess_opt = _base_session_options(config)

    if mode == "cpu":
        session = onnxruntime.InferenceSession(
            model_path, sess_options=sess_opt, providers=[CPU_PROVIDER],
        )
        return session, session.get_providers()[0]

    if mode == "qnn":
        avail = available_providers()
        if QNN_PROVIDER not in avail:
            raise ExecutionModeError(
                f"Execution mode 'qnn' was requested but {QNN_PROVIDER} is not "
                f"registered in this ONNX Runtime build (available providers: "
                f"{avail}). This requires standard `onnxruntime` plus the "
                f"Windows-ARM64 `onnxruntime-qnn` plugin package — see "
                f"docs/snapdragon-optimization.md.",
                reason=REASON_QNN_UNAVAILABLE,
            )
        try:
            session = onnxruntime.InferenceSession(
                model_path, sess_options=sess_opt,
                providers=[(QNN_PROVIDER, qnn_provider_options())],
            )
        except Exception as e:  # noqa: BLE001 - wrapping is the point here
            raise ExecutionModeError(
                f"{QNN_PROVIDER} is registered, but creating an inference "
                f"session for '{model_path}' under it failed: {e}. This "
                "usually means the QNN backend library couldn't be loaded "
                "(check LIFELINE_QNN_BACKEND_PATH), no compatible NPU/driver "
                "is present, or this model isn't QNN-compatible as exported.",
                reason=REASON_QNN_SESSION_FAILED,
            ) from e

        active = session.get_providers()[0]
        if active != QNN_PROVIDER:
            # Defensive: onnxruntime is not expected to silently swap the
            # single requested provider for another, but 'qnn' mode's
            # entire contract is "never silently run on CPU" — verify
            # rather than assume.
            raise ExecutionModeError(
                f"Execution mode 'qnn' requires {QNN_PROVIDER}, but the "
                f"session for '{model_path}' actually reports {active!r} as "
                "its active provider. Refusing to proceed on an unintended "
                "backend.",
                reason=REASON_QNN_SESSION_FAILED,
            )
        logger.info("OCR model %s running on %s (Snapdragon NPU).", model_path, active)
        return session, active

    # mode == "auto"
    avail = available_providers()
    if QNN_PROVIDER not in avail:
        logger.info(
            "%s not available in this process (available: %s); "
            "auto mode using CPU for %s.", QNN_PROVIDER, avail, model_path,
        )
        session = onnxruntime.InferenceSession(
            model_path, sess_options=sess_opt, providers=[CPU_PROVIDER],
        )
        return session, session.get_providers()[0]

    try:
        session = onnxruntime.InferenceSession(
            model_path, sess_options=sess_opt, providers=build_providers("auto"),
        )
    except Exception:  # noqa: BLE001 - auto mode's whole point is to degrade, not raise
        logger.warning(
            "%s is registered but session creation failed for %s under "
            "auto mode; falling back to %s.",
            QNN_PROVIDER, model_path, CPU_PROVIDER, exc_info=True,
        )
        session = onnxruntime.InferenceSession(
            model_path, sess_options=sess_opt, providers=[CPU_PROVIDER],
        )

    active = session.get_providers()[0]
    if active == QNN_PROVIDER:
        logger.info("OCR model %s running on %s (Snapdragon NPU).", model_path, active)
    else:
        logger.info("OCR model %s running on %s (not NPU-accelerated).", model_path, active)
    return session, active


def diagnostics(mode: str | None = None) -> dict[str, Any]:
    """
    A JSON-serializable snapshot of the current execution-mode
    situation, for demos/tooling/logging to report honestly whether
    QNN/NPU execution is actually possible right now — never asserted,
    always queried live from ONNX Runtime.
    """
    resolved_mode = resolve_execution_mode(mode)
    try:
        avail = available_providers()
        onnxruntime_installed = True
    except ImportError:
        avail = []
        onnxruntime_installed = False

    qnn_available = QNN_PROVIDER in avail
    return {
        "requested_mode": mode,
        "resolved_mode": resolved_mode,
        "onnxruntime_installed": onnxruntime_installed,
        "available_providers": avail,
        "qnn_provider_registered": qnn_available,
        "qnn_would_be_used": resolved_mode in ("auto", "qnn") and qnn_available,
        "qnn_backend_path": qnn_provider_options().get("backend_path"),
        "platform": platform.system(),
        "machine": platform.machine(),
    }
