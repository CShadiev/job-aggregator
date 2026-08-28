output "vpc_id" {
  value       = digitalocean_vpc.main.id
  description = "UUID of the VPC. The DOKS cluster and node pool will attach to this."
}

output "vpc_urn" {
  value = digitalocean_vpc.main.urn
}

output "cluster_id" {
  value       = digitalocean_kubernetes_cluster.main.id
  description = "Use with: doctl kubernetes cluster kubeconfig save <cluster_id>"
}

output "cluster_endpoint" {
  value = digitalocean_kubernetes_cluster.main.endpoint
}

output "registry_endpoint" {
  value       = digitalocean_container_registry.main.server_url
  description = "Full registry URL for tagging/pushing images, e.g. registry.digitalocean.com/<name>"
}

output "app_storage_bucket_name" {
  value = digitalocean_spaces_bucket.app_storage.name
}

output "app_storage_bucket_endpoint" {
  value = "https://${var.region}.digitaloceanspaces.com"
}

# Deliberately NOT outputting kube_config here. The provider exposes it,
# but it contains a client cert + key with full cluster admin access —
# writing that into Terraform state (even remote state) means anyone
# who can read the state file gets cluster access, forever, until you
# rotate it. Fetch credentials on demand instead:
#   doctl kubernetes cluster kubeconfig save <cluster_id>
# which merges a short-lived, revocable config into ~/.kube/config.
