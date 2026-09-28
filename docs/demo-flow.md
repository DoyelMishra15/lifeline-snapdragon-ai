# 3-minute demo flow (Build It track — Codespaces)

Run `./start.sh` before recording (see README) — leave it running in a terminal
throughout. Open the forwarded port 5173.

**0:00–0:20 — Hook**
Open on the landing page. One line: "Important information is scattered across PDFs,
screenshots, and folders — and nobody remembers what's about to expire until it already
has." Sign up with any email/password — mention: "this is a real account, created just
now, in a database running entirely in this Codespace."

**0:20–1:00 — Upload & understand**
Go to Documents, drop in a real document (an insurance PDF, or a photo of a warranty
card). Narrate: "This is processed by real backend code — `sam local start-api`, the
actual AWS SAM CLI — and stored in DynamoDB and S3, both running inside LocalStack right
here in the codespace. No AWS account involved." Point out the confidence score and that
a blurry/ambiguous scan gets flagged for review instead of guessed at — mention this
extraction is a real, deterministic, offline engine (regex/keyword-based date and field
extraction, Tesseract OCR for images) standing in for Amazon Bedrock, since Bedrock needs
a real AWS account; swapping back to Bedrock for a real deployment is a one-line
environment variable change (`LIFELINE_AI_PROVIDER=bedrock`), not a rewrite.

**1:00–1:35 — Dashboard**
Switch to Dashboard. Show "Attention needed" already surfacing an item with a plain-English
reason ("expires in 12 days and requires renewal"). Click into it — show the extracted
detail panel and the "Open original document" link back to the source file. This is the
provenance requirement: every fact traces back to a document.

**1:35–1:55 — Priority engine**
Briefly show two more items at different priority levels (Upcoming, Safe) to make clear
this is a real ranking, not a random highlight — deterministic code, not an LLM call, so
it's explainable and cheap either way.

**1:55–2:35 — Emergency mode**
Click "I have a problem." Pick "Lost my wallet." Show the resulting plan — numbered
steps, each with a "why," each linking back to the specific stored document it came from.
Point out the disclaimer: this is decision support, not medical advice, not a bank
transfer, not an autonomous phone call.

**2:35–2:50 — EventBridge, made demoable**
Go to Settings, click "Run attention sweep now." Explain: "In production this is Amazon
EventBridge firing once a day — can't watch a day pass live, so the exact same Lambda
code is wired to a button here too." Point at the Dashboard's "Recent activity" updating.

**2:50–3:00 — Architecture close**
One sentence: "Every AWS service here — API Gateway, Lambda, DynamoDB, S3, EventBridge —
runs through the real AWS SAM CLI, against LocalStack; the only thing swapped for local
dev is Bedrock (no account) and Cognito (not in LocalStack's free tier), each replaced
with a real, working, open-source equivalent — see `docs/local-development.md`."
