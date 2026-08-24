terraform {
  # >= 1.11 is required for native S3 lockfile locking (use_lockfile),
  # which the main stack's backend will rely on later.
  required_version = ">= 1.11"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.34"
    }
  }

  # Deliberately NO backend block here. This config's own state stays
  # local — it creates the bucket that OTHER stacks will use as remote
  # state, so it can't depend on that bucket existing yet.
}
