resource "digitalocean_vpc" "main" {
  name     = "${var.environment}-vpc"
  region   = var.region
  ip_range = var.vpc_cidr
}

resource "digitalocean_kubernetes_cluster" "main" {
  name     = "${var.environment}-cluster"
  region   = var.region
  vpc_uuid = digitalocean_vpc.main.id

  # Pinned, not looked up — see variables.tf for why.
  version = var.kubernetes_version

  # No argument here reads FROM digitalocean_container_registry.main, so
  # Terraform's graph has no natural edge between them — registry_integration
  # is just a literal `true`. Without this, Terraform is free to create the
  # registry and flip this flag concurrently, which is exactly the race that
  # produced the 412 (registry not yet "active" when the flag-flip landed).
  depends_on = [digitalocean_container_registry.main]  

  # Lets kubelets authenticate to DOCR automatically — no manually
  # created/rotated imagePullSecret needed for pulling images.
  registry_integration = true

  # Patch-level security fixes only, applied in the window below.
  # This is NOT the same as auto-upgrading Kubernetes minor/major versions.
  # Kubernetes Services (LoadBalancer type) and PVCs created INSIDE the
  # cluster provision real, separately-billed DO resources (Load
  # Balancers, Volumes) that Terraform never directly manages. Without
  # this, `terraform destroy` leaves those running — orphaned and still
  # billing — since Terraform only knows about the cluster itself.
  # True here means "one command down" (per the epic plan) actually
  # tears everything down, not just the parts Terraform created directly.
  destroy_all_associated_resources = true

  auto_upgrade  = true
  surge_upgrade = true
  ha            = false # see module notes: HA control plane's flat fee doesn't fit the cost ceiling

  maintenance_policy {
    day        = "sunday"
    start_time = "04:00"
  }

  # Surge upgrade: DO brings up new nodes before removing old ones during
  # an upgrade, so pool capacity never dips mid-upgrade. Small overlap
  # cost, essentially free insurance.
  node_pool {
    name       = "${var.environment}-pool"
    size       = var.node_size
    node_count = var.node_count
    auto_scale = false

    labels = {
      environment = var.environment
    }
  }
}

resource "digitalocean_container_registry" "main" {
  name                   = var.registry_name
  subscription_tier_slug = "starter" # free; one repo is all this project needs
  region                 = var.region
}

resource "digitalocean_spaces_bucket" "app_storage" {
  name   = var.app_storage_bucket_name
  region = var.region
  acl    = "private"
}
