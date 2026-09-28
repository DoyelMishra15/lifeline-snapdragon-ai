# Known limitations

## Snapdragon on-device provider specifically (`LIFELINE_AI_PROVIDER=snapdragon`)
- **GitHub Codespaces is this provider's supported dev/test environment, and it never
  needs Snapdragon/QNN hardware to work there.** `LIFELINE_OCR_EXECUTION_MODE=cpu` fully
  works in Codespaces; `=auto` correctly detects that `QNNExecutionProvider` isn't
  registered and cleanly uses CPU; `=qnn` fails with a clear `reason="qnn_unavailable"`
  error rather than silently using CPU or breaking any import — all three are directly
  tested there (`backend/tests/test_codespaces_environment.py`). Nothing about importing
  this project, running its handlers, or running its test suite in Codespaces requires
  `onnxruntime-qnn`, the Qualcomm QNN SDK, or any Windows-only library.
- **The QNN/CPU execution-mode decision logic is implemented and tested; actual NPU
  execution is not yet observed on real hardware.** `backend/lib/qnn_execution.py` and
  `backend/lib/rapidocr_qnn_session.py` genuinely wire the OCR model sessions through
  ONNX Runtime's `QNNExecutionProvider`, with unit tests covering every
  auto/qnn/cpu × available/unavailable/session-fails combination — but the
  hardware-specific calls (`onnxruntime.get_available_providers`, `InferenceSession`
  actually loading a QNN backend) are mocked in those tests, since this has only been run
  in Codespaces (Linux/x86_64). See `docs/snapdragon-optimization.md` for the full list of
  what's verified versus what still needs a real Snapdragon device — in short: does
  `onnxruntime-qnn` register `QNNExecutionProvider` there, do these specific ONNX graphs
  run correctly and faster under it, and accuracy on real (not synthetically generated)
  document photos.
- **Only the OCR step changed.** Document structuring and emergency-plan drafting reuse
  `local_reasoning.py`'s existing rule-based logic unchanged — this provider is not a
  bigger AI upgrade than that, and isn't presented as one.
- **Not wired into the SAM-local/LocalStack stack.** It's reachable via
  `backend/tools/snapdragon_demo.py` and directly via `lib/ai_provider.py` (e.g. from
  pytest), but hasn't been exercised through `start.sh`'s full Docker-based local API yet.

## Local (Codespaces) stack specifically
- **The local extraction engine (`local_reasoning.py`) is rule-based, not an LLM.** It does
  real regex/keyword extraction over actual document text — it's not a stub — but it will
  miss dates/providers/amounts in unusual formats or phrasings that a language model would
  catch. It's honest about this: missing fields become explicit warnings and lower
  confidence, never a fabricated guess. Switching to real Amazon Bedrock for a deployment
  (`LIFELINE_AI_PROVIDER=bedrock`) gets the full language understanding back with no code
  changes elsewhere in the pipeline.
- **Local uploads are capped at 4MB**, smaller than the real-AWS 15MB limit. Local mode
  sends the file inline as base64 (see `docs/local-development.md` for why presigned S3
  URLs don't work against a SAM-local Lambda talking to LocalStack), which has to stay
  comfortably under API Gateway/Lambda's own 6MB synchronous payload limit.
- **OCR (Tesseract) is less accurate than Bedrock's vision model**, especially on skewed,
  low-resolution, or handwritten text. Low-confidence/empty OCR results flow into the same
  honest low-confidence path as any other uncertain extraction, rather than failing outright.
- **The local JWT secret (`LIFELINE_LOCAL_JWT_SECRET`) is a fixed development value**,
  not a real secret — fine for a Codespace only you have access to, but this local-auth
  path must never be pointed at from a real production frontend (it isn't, by default —
  see `frontend/src/context/AuthContext.jsx`, which only uses it when `VITE_LOCAL_MODE` is
  explicitly set).
- **LocalStack's DynamoDB/S3 are close to, but not byte-for-byte identical to, real AWS**
  (e.g. some edge-case error codes/consistency behaviors differ). The application code
  itself is unchanged between local and real AWS — only the endpoint URL differs — so this
  risk is inherited from LocalStack itself, not from anything LifeLine-specific.

## General (both environments)
- **Scanned/image-only PDFs have no OCR.** `backend/lib/pdf_extract.py` extracts real text
  from PDFs that have a text layer (the common case — insurance policies, bills,
  certificates exported from a word processor or downloaded from a provider portal). A
  scanned PDF with no text layer is detected and fails honestly (`needs_review`, with a
  message suggesting the user upload a photo instead) rather than being sent to the
  extraction engine as fabricated or empty content. A photo (PNG/JPEG/WebP) of the same
  document works today via image OCR (locally) or Bedrock's multimodal input (real AWS).
- **No real outbound notifications.** The EventBridge sweep writes attention events to
  DynamoDB (a real, demoable event-driven mechanism, surfaced in the dashboard's "Recent
  activity" section, and now also manually triggerable via `POST /reminders/sweep` — see
  Settings) but does not send email/SMS/push. A production version would fan these events
  out via SNS or SES.
- **Page-level provenance is document-level, not page-level.** LifeLine shows which
  document a fact came from and links to the original file, but does not (yet) point to a
  specific page/region within a multi-page PDF.
- **Single Bedrock model, no fallback (real AWS only).** LifeLine defaults to
  `global.anthropic.claude-sonnet-4-6`. If the configured model/profile is unavailable in a
  region/account, extraction and emergency-plan generation fail gracefully (status
  `failed`/502, with a `retryable` flag) but there's no automatic fallback to a different
  model.
- **Conflict detection is same-type+provider only, and requires a detected provider on
  both documents.** Two documents with different providers but describing the same
  real-world thing (e.g. a renamed insurer) won't be flagged as conflicting; likewise two
  documents where neither has a detected provider are deliberately *not* grouped, to avoid
  false-positive conflicts between unrelated documents.
- **IAM-level S3/DynamoDB access is scoped per-function, not per-user (real AWS).** User
  isolation is enforced in application code (every query is scoped to the caller's verified
  identity; `get_document`/`get_handler` double-check the returned item's `user_id` even
  though the query already guarantees it) rather than via per-user IAM policies or STS
  scoping. This is standard for a Lambda-behind-API-Gateway architecture at this scale, but
  worth naming explicitly. The Bedrock IAM policy, by contrast, *is* scoped at the
  infrastructure level (see `docs/aws-services.md`).
- **No automated integration test against a live deployed stack or a running LocalStack.**
  Tests cover the priority engine, schema validation, PDF text extraction, the local
  extraction/emergency-plan engine, local JWT auth, emergency-plan guardrails, DynamoDB
  Decimal/float handling, the reminder sweep, user isolation, and the on-device ONNX
  OCR/QNN execution-mode system — all in isolation via moto and mocked hardware pieces,
  run in GitHub Codespaces (172 tests total, no Docker and no Snapdragon hardware
  required). There's no test that exercises a real
  `sam local start-api` + LocalStack + Vite proxy chain end-to-end, or a real deployed AWS
  stack; both are documented as manual verification steps (`docs/demo-flow.md`,
  `docs/deployment-checklist.md`).
- **Frontend mock/demo mode is a separate code path from the real API calls** in
  `frontend/src/api/client.js`, alongside local mode and real-AWS mode. All three mirror
  the same request/response shapes so they shouldn't drift, but mock mode in particular is
  a second implementation (including a JS port of the priority engine) to keep in sync —
  and per the hackathon requirements, it is **not** what `frontend/.env` points at by
  default; `VITE_API_BASE_URL=/api` + `VITE_LOCAL_MODE=true` route every request through
  the real local backend instead. A console warning fires if a production build
  (`import.meta.env.PROD`) ends up in mock mode, to catch a missing `VITE_API_BASE_URL`
  before it ships.
- **Reminder sweep window is ±90 days.** The sweep re-flags anything expiring in the next
  90 days and anything that expired in the last 90 days (so an unrenewed item keeps
  showing as urgent). An item that lapsed more than 90 days ago and was never renewed will
  stop generating fresh attention events, though it remains visible and correctly
  prioritized whenever the dashboard itself is loaded (the priority engine re-derives its
  status from the stored expiry date, not from the last sweep).
