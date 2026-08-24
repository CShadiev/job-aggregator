variable "state_bucket_name" {
  type        = string
  description = "Globally-unique name for the Spaces bucket holding Terraform remote state. Spaces bucket names follow S3 rules: lowercase, no underscores, must be unique across ALL of DigitalOcean, not just your account."
}

variable "region" {
  type        = string
  default     = "fra1"
  description = "DigitalOcean region slug. fra1 (Frankfurt) is chosen deliberately: it's the region the rest of the stack will likely live in too, given the EU/Germany-facing target audience for the demo."
}
