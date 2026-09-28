#!/usr/bin/env bash
# Creates the DynamoDB table (with its GSI) and S3 bucket inside
# LocalStack, mirroring infrastructure/template.yaml's LifeLineTable
# and DocumentsBucket resources. Idempotent — safe to run every time
# ./start.sh runs; "already exists" errors from a previous run are
# swallowed on purpose.
#
# Runs on the HOST (the devcontainer), so it talks to LocalStack via
# the published port on localhost — NOT the "localstack" Docker-network
# hostname the SAM-local Lambda containers use (see
# infrastructure/env.local.json).
set -euo pipefail

ENDPOINT="http://localhost:4566"
TABLE_NAME="lifeline-local"
BUCKET_NAME="lifeline-documents-local"
REGION="us-east-1"

export AWS_ACCESS_KEY_ID="test"
export AWS_SECRET_ACCESS_KEY="test"
export AWS_DEFAULT_REGION="$REGION"

echo "==> Creating DynamoDB table: $TABLE_NAME"
aws --endpoint-url="$ENDPOINT" dynamodb create-table \
  --table-name "$TABLE_NAME" \
  --attribute-definitions \
    AttributeName=PK,AttributeType=S \
    AttributeName=SK,AttributeType=S \
    AttributeName=gsi1pk,AttributeType=S \
    AttributeName=gsi1sk,AttributeType=S \
  --key-schema \
    AttributeName=PK,KeyType=HASH \
    AttributeName=SK,KeyType=RANGE \
  --global-secondary-indexes \
    '[{"IndexName":"gsi1","KeySchema":[{"AttributeName":"gsi1pk","KeyType":"HASH"},{"AttributeName":"gsi1sk","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}]' \
  --billing-mode PAY_PER_REQUEST \
  --region "$REGION" \
  >/dev/null 2>&1 && echo "    created." || echo "    already exists — skipping."

echo "==> Creating S3 bucket: $BUCKET_NAME"
aws --endpoint-url="$ENDPOINT" s3 mb "s3://$BUCKET_NAME" --region "$REGION" \
  >/dev/null 2>&1 && echo "    created." || echo "    already exists — skipping."

echo "==> Local AWS resources ready."
