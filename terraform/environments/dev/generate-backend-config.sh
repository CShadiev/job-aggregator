#!/usr/bin/env bash
# Generates backend.hcl for this stack by reading the bootstrap stack's
# own outputs directly — single source of truth, no manual copy-paste.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_DIR="$SCRIPT_DIR/../../bootstrap"

BUCKET=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket_name)
ENDPOINT=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket_endpoint)

cat > "$SCRIPT_DIR/backend.hcl" <<EOF
bucket = "${BUCKET}"
key    = "dev/terraform.tfstate"

endpoints = {
  s3 = "${ENDPOINT}"
}

# DO Spaces isn't AWS, so these silence AWS-specific checks the s3
# backend normally performs (account ID lookup, region validation, etc.)
region                      = "us-east-1"
skip_credentials_validation = true
skip_requesting_account_id  = true
skip_metadata_api_check     = true
skip_region_validation      = true
skip_s3_checksum            = true

# Native locking (Terraform >= 1.11) — no DynamoDB equivalent needed.
use_lockfile = true
EOF

echo "Wrote $SCRIPT_DIR/backend.hcl:"
cat "$SCRIPT_DIR/backend.hcl"
