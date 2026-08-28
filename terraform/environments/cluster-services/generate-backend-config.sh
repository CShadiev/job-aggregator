#!/usr/bin/env bash
# Same source-of-truth pattern as ../dev/generate-backend-config.sh —
# reads the STATE bucket location from the bootstrap stack (bootstrap
# is shared infrastructure; both dev and cluster-services store their
# state in it, under different keys).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_DIR="$SCRIPT_DIR/../../bootstrap"

BUCKET=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket_name)
ENDPOINT=$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket_endpoint)

cat > "$SCRIPT_DIR/backend.hcl" <<EOF
bucket = "${BUCKET}"
key    = "cluster-services/terraform.tfstate"

endpoints = {
  s3 = "${ENDPOINT}"
}

region                      = "us-east-1"
skip_credentials_validation = true
skip_requesting_account_id  = true
skip_metadata_api_check     = true
skip_region_validation      = true
skip_s3_checksum            = true
use_lockfile                = true
EOF

echo "Wrote $SCRIPT_DIR/backend.hcl:"
cat "$SCRIPT_DIR/backend.hcl"
