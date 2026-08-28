variable "environment" {
  type        = string
  default     = "dev"
  description = "Must match the environment name used in ../dev — reconstructs the cluster name for the data source lookup."
}

variable "region" {
  type        = string
  default     = "fra1"
}

variable "acme_email" {
  type        = string
  description = "Contact address for the Let's Encrypt account on both ClusterIssuers (expiry/problem notices only, not published on the cert)."
}
