output "state_bucket_name" {
  value       = digitalocean_spaces_bucket.terraform_state.name
  description = "Use as `bucket` in the main stack's backend \"s3\" block."
}

output "state_bucket_endpoint" {
  value       = "https://${var.region}.digitaloceanspaces.com"
  description = "Use as the s3 endpoint override in the main stack's backend \"s3\" block."
}
