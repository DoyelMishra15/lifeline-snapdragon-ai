"""
Wires `rapidocr_onnxruntime`'s three ONNX Runtime sessions (text
detection, angle classification, text recognition) through
`lib/qnn_execution.py`'s execution-mode system, so that
`LIFELINE_OCR_EXECUTION_MODE=qnn` genuinely runs those sessions on
`QNNExecutionProvider` (Snapdragon NPU) instead of merely mentioning
it, and `=cpu` / `=auto` behave exactly as documented there.

Why this exists instead of passing options through `RapidOCR(**kwargs)`:
`rapidocr_onnxruntime` only understands two provider toggles per model
stage (`det_use_cuda`/`det_use_dml`, and the `cls_`/`rec_` equivalents)
— see `rapidocr_onnxruntime.utils.parse_parameters.UpdateParameters`.
There is no supported way to hand it a `QNNExecutionProvider` provider
list through its public constructor. Forking or vendoring the whole
package to add that would be a much larger, harder-to-maintain change
than is warranted here.

What this does instead: `rapidocr_onnxruntime`'s three model wrappers
(`TextDetector`, `TextClassifier`, `TextRecognizer`) all create their
ONNX Runtime session the same narrow way — `OrtInferSession(config)`,
then call the resulting object, and (for the recognizer) read
`.have_key()` / `.get_character_list()`. `LifelineOrtInferSession`
below reimplements exactly that narrow interface (nothing about the
PP-OCRv4 pre/post-processing, box geometry, or CTC decoding — all of
that stays exactly as `rapidocr_onnxruntime` already implements it),
using `lib/qnn_execution.py` to build the session instead of
`rapidocr_onnxruntime`'s own CUDA/DirectML-only logic.
`patch_rapidocr_sessions()` then substitutes it in place of
`rapidocr_onnxruntime.utils.OrtInferSession` inside the three
already-imported model-wrapper modules, so `RapidOCR()` (constructed
by `lib/onnx_ocr.py`) picks it up with no changes to
`rapidocr_onnxruntime` itself and no vendored copy of it in this repo.
"""
from __future__ import annotations

import os
from typing import Any

from lib import qnn_execution


class LifelineOrtInferSession:
    """
    Drop-in replacement for `rapidocr_onnxruntime.utils.OrtInferSession`
    that resolves ONNX Runtime execution providers via
    `lib/qnn_execution.py` (auto/qnn/cpu) instead of rapidocr's own
    cuda/directml-only logic. Implements exactly the interface
    `rapidocr_onnxruntime`'s `TextDetector`/`TextClassifier`/
    `TextRecognizer` use: construct with a rapidocr model config dict,
    call with an input ndarray, and the two character-list helpers the
    recognizer uses.
    """

    def __init__(self, config: dict[str, Any]):
        model_path = config.get("model_path")
        if not model_path:
            raise ValueError("model_path is None!")
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"{model_path} does not exist.")

        mode = qnn_execution.resolve_execution_mode(qnn_execution.get_active_mode())
        self.execution_mode = mode
        self.session, self.active_provider = qnn_execution.create_session(
            model_path, mode, config=config,
        )

    def __call__(self, input_content):
        input_dict = dict(zip(self.get_input_names(), [input_content]))
        return self.session.run(self.get_output_names(), input_dict)

    def get_input_names(self):
        return [v.name for v in self.session.get_inputs()]

    def get_output_names(self):
        return [v.name for v in self.session.get_outputs()]

    def get_character_list(self, key: str = "character"):
        meta_dict = self.session.get_modelmeta().custom_metadata_map
        return meta_dict[key].splitlines()

    def have_key(self, key: str = "character") -> bool:
        meta_dict = self.session.get_modelmeta().custom_metadata_map
        return key in meta_dict


_PATCHED = False


def patch_rapidocr_sessions() -> None:
    """
    Replace `OrtInferSession` with `LifelineOrtInferSession` inside
    rapidocr_onnxruntime's three model-wrapper modules. Idempotent —
    safe to call every time an engine is (re)built. Must run before
    `RapidOCR()` is instantiated (see lib/onnx_ocr.py); has no effect
    on already-constructed engines, which keep whatever session they
    were built with.
    """
    global _PATCHED
    from rapidocr_onnxruntime.ch_ppocr_cls import text_cls
    from rapidocr_onnxruntime.ch_ppocr_det import text_detect
    from rapidocr_onnxruntime.ch_ppocr_rec import text_recognize

    text_detect.OrtInferSession = LifelineOrtInferSession
    text_cls.OrtInferSession = LifelineOrtInferSession
    text_recognize.OrtInferSession = LifelineOrtInferSession
    _PATCHED = True


def is_patched() -> bool:
    return _PATCHED
