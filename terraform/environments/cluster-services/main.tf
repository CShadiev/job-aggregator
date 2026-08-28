# CRDs (Gateway API's, Traefik's own, and cert-manager's) are installed by
# scripts/bootstrap-cluster.sh, NOT here — see that script and the
# module notes on why kubernetes_manifest/Helm-managed CRDs don't mix
# well with same-apply creation.
resource "helm_release" "traefik" {
  name             = "traefik"
  repository       = "https://traefik.github.io/charts"
  chart            = "traefik"
  version          = "41.2.0" # keep in lockstep with TRAEFIK_CHART_VERSION in scripts/bootstrap-cluster.sh
  namespace        = "traefik"
  create_namespace = true

  values = [
    yamlencode({
      providers = {
        kubernetesGateway = {
          enabled = true
        }
      }

      # The chart auto-creates a default GatewayClass ("traefik") and
      # Gateway ("traefik-gateway") when the above is enabled. Rather than
      # taking those over as separate kubernetes_manifest resources, we
      # configure that same default Gateway directly through chart values —
      # this is the chart's documented way to add a TLS listener and the
      # cert-manager annotation that drives it.
      gateway = {
        # "Annotated Gateway" pattern: cert-manager's gateway-shim
        # controller watches for this annotation and auto-creates/manages
        # a Certificate per listener below that has certificateRefs set —
        # no separate Certificate resource needed on our side.
        # https://cert-manager.io/docs/usage/gateway/
        annotations = {
          # Proven against letsencrypt-staging first (untrusted cert, but the
          # whole HTTP-01 + Gateway API flow validated end-to-end). Now on prod.
          "cert-manager.io/cluster-issuer" = "letsencrypt-prod"
        }
        listeners = {
          # namespacePolicy defaults to "Same" (Gateway API's AllowedRoutes),
          # which would restrict HTTPRoutes to the `traefik` namespace only.
          # Real workloads (API, worker, UI, this whoami test) live in other
          # namespaces, so both listeners open up to "All" — acceptable on a
          # single-tenant demo cluster with no cross-namespace isolation need.
          web = {
            port            = 8000
            protocol        = "HTTP"
            namespacePolicy = { from = "All" }
          }
          websecure = {
            port     = 8443
            protocol = "HTTPS"
            hostname = "app.cshadiev.dev" # HTTP-01 only proves single hostnames, not wildcards — see D7
            certificateRefs = [
              { name = "app-cshadiev-dev-tls" }
            ]
            mode            = "Terminate"
            namespacePolicy = { from = "All" }
          }
        }
      }
    })
  ]
}

resource "helm_release" "cert_manager" {
  name             = "cert-manager"
  chart            = "oci://quay.io/jetstack/charts/cert-manager"
  version          = "1.21.1" # keep in lockstep with CERT_MANAGER_VERSION in scripts/bootstrap-cluster.sh
  namespace        = "cert-manager"
  create_namespace = true

  values = [
    yamlencode({
      # CRDs come from scripts/bootstrap-cluster.sh (server-side apply) —
      # same split as Traefik/Gateway API above. See ADR 0001.
      crds = {
        enabled = false
      }
      config = {
        apiVersion = "controller.config.cert-manager.io/v1alpha1"
        kind       = "ControllerConfiguration"
        # Off by default and still Beta upstream: without this, the
        # gateway-shim controller and the HTTP-01 Gateway API solver never
        # start, and ClusterIssuers/Certificates that rely on them just sit
        # there doing nothing — no error, easy to misread as "not working yet".
        gatewayAPI = {
          enabled = true
        }
      }
    })
  ]
}

# One shared ACME account key per issuer would also work, but a dedicated
# key per issuer is the documented default and avoids any cross-environment
# coupling if the staging issuer is ever reused for other test domains.
resource "kubernetes_manifest" "letsencrypt_staging" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata = {
      name = "letsencrypt-staging"
    }
    spec = {
      acme = {
        server = "https://acme-staging-v02.api.letsencrypt.org/directory"
        email  = var.acme_email
        privateKeySecretRef = {
          name = "letsencrypt-staging-account-key"
        }
        solvers = [
          {
            http01 = {
              gatewayHTTPRoute = {
                parentRefs = [
                  {
                    name        = "traefik-gateway"
                    namespace   = "traefik"
                    kind        = "Gateway"
                    sectionName = "web" # challenge traffic is plain HTTP, never the websecure listener
                  }
                ]
              }
            }
          }
        ]
      }
    }
  }

  depends_on = [helm_release.cert_manager]
}

resource "kubernetes_manifest" "letsencrypt_prod" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata = {
      name = "letsencrypt-prod"
    }
    spec = {
      acme = {
        server = "https://acme-v02.api.letsencrypt.org/directory"
        email  = var.acme_email
        privateKeySecretRef = {
          name = "letsencrypt-prod-account-key"
        }
        solvers = [
          {
            http01 = {
              gatewayHTTPRoute = {
                parentRefs = [
                  {
                    name        = "traefik-gateway"
                    namespace   = "traefik"
                    kind        = "Gateway"
                    sectionName = "web"
                  }
                ]
              }
            }
          }
        ]
      }
    }
  }

  depends_on = [helm_release.cert_manager]
}

# Reads the LB's real external IP dynamically — never hardcode it, since
# it could change if the Service (and therefore the LB) is ever recreated.
data "kubernetes_service" "traefik" {
  metadata {
    name      = "traefik"
    namespace = "traefik"
  }

  depends_on = [helm_release.traefik]
}

# `app.cshadiev.dev` — a SUBDOMAIN delegated to DO, not the whole
# cshadiev.dev domain. Only NS records for this one subdomain point at
# DigitalOcean; the rest of the domain (apex, other subdomains, MX,
# etc.) stays exactly as it was at the registrar, untouched.
resource "digitalocean_domain" "app" {
  name = "app.cshadiev.dev"
}

resource "digitalocean_record" "app_root" {
  domain = digitalocean_domain.app.name
  type   = "A"
  name   = "@"
  value  = data.kubernetes_service.traefik.status[0].load_balancer[0].ingress[0].ip
  ttl    = 300
}

# Wildcard, so any future service (api.app.cshadiev.dev, ui.app.cshadiev.dev,
# etc.) resolves automatically without another Terraform change — cheap
# insurance given we don't yet know the final path/subdomain layout.
resource "digitalocean_record" "app_wildcard" {
  domain = digitalocean_domain.app.name
  type   = "A"
  name   = "*"
  value  = data.kubernetes_service.traefik.status[0].load_balancer[0].ingress[0].ip
  ttl    = 300
}
