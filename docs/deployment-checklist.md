# Deployment checklist (real AWS)

> This checklist is for deploying to a real AWS account. To just run and demo LifeLine,
> see the README's Codespaces quickstart instead — no AWS account needed for that at all.


## Prerequisites
- [ ] AWS account with access to Bedrock, and **Claude Sonnet 4.6 model access granted**
      in Bedrock's "Model access" console page for your target region (or whichever model
      you set `BedrockModelId` to — see below)
- [ ] AWS CLI configured (`aws configure`) with a role that can create the resources below
- [ ] AWS SAM CLI installed (`sam --version`)
- [ ] Node.js 18+ and npm

## 1. Deploy the backend (SAM)
```bash
cd infrastructure
sam build
sam deploy --guided
```
On first run, `--guided` will ask for a stack name, region, and the stack parameters
(`Stage`, `BedrockModelId`, `AllowedOrigin`) — defaults are fine to start (`AllowedOrigin`
defaults to `'*'`; tighten it in step 4 below), and the answers are saved to
`samconfig.toml` for future `sam deploy` runs. `sam build` installs `backend/requirements.txt`
(`pydantic`, `pypdf`) into the Lambda deployment package automatically — no manual step
needed.

- [ ] Note the `ApiUrl`, `UserPoolId`, `UserPoolClientId` from the stack outputs
      (`sam deploy` prints them; also visible via `aws cloudformation describe-stacks`)
- [ ] In the Bedrock console, confirm model access is granted for the model in
      `BedrockModelId` (defaults to `global.anthropic.claude-sonnet-4-6`) — this is a
      manual, one-time step per AWS account and cannot be done via the SAM template

## 2. Configure the frontend
```bash
cd frontend
cp ../.env.example .env
# fill in:
#   VITE_API_BASE_URL=<ApiUrl output>
#   VITE_COGNITO_USER_POOL_ID=<UserPoolId output>
#   VITE_COGNITO_CLIENT_ID=<UserPoolClientId output>
npm install
npm run build   # sanity check the build succeeds
```
- [ ] Without a `.env` file, the frontend runs in local demo/mock mode (no AWS calls at
      all) — useful for UI iteration, not for the real submission.

## 3. Deploy the frontend (Amplify Hosting)
- [ ] Push the repo to GitHub (or another provider Amplify supports)
- [ ] In the Amplify console, "New app" → connect the repo → it will detect
      `infrastructure/amplify.yml` if you point the build settings at it (or paste its
      contents into the Amplify build settings directly)
- [ ] Add the three `VITE_*` environment variables from step 2 in the Amplify app's
      environment variables settings (Amplify env vars, not committed `.env`)
- [ ] Deploy; note the Amplify-provided URL — this is the Ship It submission URL

## 4. Tighten security for the deployed URL
- [ ] Redeploy with the real `AllowedOrigin` parameter set to your Amplify domain (replacing
      the `'*'` default used for first deploy):
      `sam deploy --parameter-overrides AllowedOrigin=https://<your-amplify-domain>`
      (this updates both the API Gateway CORS config and the S3 bucket CORS config in one
      pass — see `infrastructure/template.yaml`)
- [ ] Confirm no AWS credentials, account IDs, or secrets are committed anywhere in the repo

## 5. Smoke test end-to-end
- [ ] Sign up a test user (Cognito will send a confirmation email/code)
- [ ] Upload a real document (a PDF or photo of something like an insurance card)
- [ ] Confirm it appears in the dashboard with a priority level and reason
- [ ] Click into it and confirm the source link opens the original file
- [ ] Click "I HAVE A PROBLEM" → pick a situation → confirm a plan generates and
      references your uploaded document
- [ ] Manually invoke `ReminderSweepFunction` once (`aws lambda invoke`) and confirm it
      returns a 200 with a sweep count — this is what EventBridge calls daily. Reload the
      dashboard afterward and confirm "Recent activity" shows entries (these come from the
      `recent_events` the sweep wrote to DynamoDB, not recomputed client-side)
- [ ] Upload a text-based PDF (not just an image) and confirm it processes successfully —
      this exercises the `pypdf` text-extraction path specifically
- [ ] Upload a scanned/image-only PDF (if you have one) and confirm it fails as
      `needs_review` with a clear message, rather than erroring out or fabricating data
