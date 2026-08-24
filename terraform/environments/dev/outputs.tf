output "vpc_id" {
  value       = digitalocean_vpc.main.id
  description = "UUID of the VPC. The DOKS cluster and node pool will attach to this."
}

output "vpc_urn" {
  value = digitalocean_vpc.main.urn
}
