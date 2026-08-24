resource "digitalocean_spaces_bucket" "terraform_state" {
  name   = var.state_bucket_name
  region = var.region
  acl    = "private"

  # Versioning means an accidental corrupt state write doesn't destroy
  # history — you can recover a previous version of terraform.tfstate
  # the same way you'd recover any other object version in S3/Spaces.
  versioning {
    enabled = true
  }
}
