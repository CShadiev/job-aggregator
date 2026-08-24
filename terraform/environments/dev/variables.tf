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
