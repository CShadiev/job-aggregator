resource "digitalocean_vpc" "main" {
  name     = "${var.environment}-vpc"
  region   = var.region
  ip_range = var.vpc_cidr
}
