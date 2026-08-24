terraform {
  required_version = ">= 1.11"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.34"
    }
  }

  # Intentionally empty (partial configuration). Real values come from
  # backend.hcl at `terraform init -backend-config=backend.hcl` time —
  # see generate-backend-config.sh, which derives them from the
  # bootstrap stack's outputs instead of anyone retyping them.
  backend "s3" {}
}
