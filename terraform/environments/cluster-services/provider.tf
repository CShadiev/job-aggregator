provider "digitalocean" {}

# Looked up via a DATA SOURCE, not created here. The cluster already
# exists from a prior, separate `terraform apply` in ../dev. Reading it
# this way — rather than threading kube_config through remote-state
# outputs from that stack — sidesteps the provider-initialization race
# HashiCorp's own kubernetes provider docs warn against: configuring
# kubernetes/helm providers from a resource's attributes when that
# resource is created in the SAME apply leads to "intermittent and
# unpredictable errors," worst on any apply that recreates the cluster.
# https://registry.terraform.io/providers/hashicorp/kubernetes/latest/docs
data "digitalocean_kubernetes_cluster" "main" {
  name = "${var.environment}-cluster"
}

provider "kubernetes" {
  host                   = data.digitalocean_kubernetes_cluster.main.endpoint
  token                  = data.digitalocean_kubernetes_cluster.main.kube_config[0].token
  cluster_ca_certificate = base64decode(data.digitalocean_kubernetes_cluster.main.kube_config[0].cluster_ca_certificate)
}

provider "helm" {
  kubernetes {
    host                   = data.digitalocean_kubernetes_cluster.main.endpoint
    token                  = data.digitalocean_kubernetes_cluster.main.kube_config[0].token
    cluster_ca_certificate = base64decode(data.digitalocean_kubernetes_cluster.main.kube_config[0].cluster_ca_certificate)
  }
}
