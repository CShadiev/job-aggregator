variable "environment" {
  type        = string
  default     = "dev"
  description = "Short name used as a prefix for resource names in this stack."
}

variable "region" {
  type        = string
  default     = "fra1"
  description = "DigitalOcean region slug. Same fra1 choice as bootstrap, for the EU/Germany-facing audience."
}

variable "vpc_cidr" {
  type        = string
  default     = "10.10.0.0/24"
  description = "CIDR range for the VPC. /24 gives 256 addresses — plenty for a small DOKS node pool plus room to grow."
}

variable "kubernetes_version" {
  type        = string
  default     = "1.36.3-do.2"
  description = "Pinned explicitly (never wired to a 'latest' lookup) so `terraform plan` never surprises you with an unplanned cluster upgrade. Bump this deliberately, as its own change, when you want to upgrade."
}

variable "node_size" {
  type        = string
  default     = "s-2vcpu-4gb"
  description = "Droplet size for worker nodes. Matches the ~$48/mo (2 nodes) line in the cost plan."
}

variable "node_count" {
  type        = number
  default     = 2
  description = "Fixed node count — no cluster autoscaler. The epic's autoscaling requirement targets pod-level HPA on the API, not node count; keeping this static keeps cost predictable for a demo."
}

variable "registry_name" {
  type        = string
  description = "Globally-unique DOCR registry name — forms part of the pull URL registry.digitalocean.com/<name>/<repo>:<tag>."
}

variable "app_storage_bucket_name" {
  type        = string
  description = "Globally-unique Spaces bucket name for application object storage — CVs and generated cover letters (S3_BUCKET_NAME in the app's own config). Deliberately separate from the Terraform state bucket: different lifecycle, different access pattern, different blast radius if something goes wrong with one or the other."
}
