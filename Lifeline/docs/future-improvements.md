# Future improvements

- **A local LLM option for the offline extraction engine** — e.g. Ollama running a small
  open-weight model, with `local_reasoning.py` calling it instead of (or as a fallback
  behind) the current regex/keyword approach. Deliberately not done for this submission
  (see `docs/aws-services.md`'s note on Strands Agents SDK) — a multi-GB model download
  inside Codespaces trades reliability for a capability the deterministic engine already
  covers reasonably well; worth revisiting if Codespaces resource limits allow it.
- **Page-level citations for provenance**, extending `pdf_extract.py`'s per-page text
  extraction (already tracked per page internally) through to the UI.
- **Step Functions orchestration** for document processing once it's genuinely
  multi-stage (e.g. OCR → translation → extraction → validation → embeddings), giving
  visual execution history and built-in retry/backoff per step.
- **Real notifications** — fan the EventBridge sweep's events out through SNS/SES for
  actual email/SMS reminders, with user-configurable lead times per document type.
- **Multi-modal conflict resolution** — when two documents disagree, let the user resolve
  the conflict in-app (mark one superseded) instead of just flagging it.
- **Shared/family accounts** — a second Cognito group or a "trusted contact" role that can
  view a subset of another user's LifeLine data during an actual emergency.
- **Offline/exportable emergency card** — a printable or downloadable one-page summary of
  the highest-stakes information (identity doc numbers, emergency contact, insurance
  provider) for situations with no phone/network access.
- **Confidence-aware re-extraction** — automatically retry extraction with a stronger
  prompt or a second model pass when confidence is low, before falling back to
  needs_review.
- **Audit log** — a visible history of every extraction and plan generation, including the
  raw model/engine output, for full transparency into what the AI saw and returned.
- **A `samlocal deploy`-based option** for deploying the whole template (not just
  DynamoDB/S3) into LocalStack in one shot, once LocalStack's CloudFormation/Lambda
  execution support for this pattern matures further — see `docs/local-development.md`
  for why `sam local start-api` was chosen as the more reliable option today.
