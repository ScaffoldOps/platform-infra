# platform-infra

Local Kubernetes infrastructure source of truth for ScaffoldOps Minikube development.

## Scope

This repository currently owns the shared local-dev infrastructure that is visible in the cluster:

- bootstrap namespaces used by local development
- Keycloak in the `security` namespace

This repository does not currently define application workloads such as `userauth` in `energyco`. Those appear to belong to an application repository and are treated here only as consumers of shared infrastructure.

## Structure

```text
k8s/
  base/
    kustomization.yaml
    namespaces/
    security/
  overlays/
    local-dev/
```

- `k8s/base/namespaces`: namespace bootstrap manifests
- `k8s/base/security`: shared security infrastructure for local dev
- `k8s/overlays/local-dev`: local Minikube entrypoint

## Deploy

Apply the local-dev overlay:

```bash
kubectl apply -k k8s/overlays/local-dev
```

Preview the rendered manifests:

```bash
kubectl kustomize k8s/overlays/local-dev
```

## Verify

Check that the expected namespaces and Keycloak resources exist:

```bash
kubectl get ns
kubectl -n security get deploy,svc,secret
kubectl -n security get pods
```

Expected local-dev Keycloak service DNS:

```text
http://keycloak.security.svc.cluster.local:8080
```

## Port Forward Keycloak

Forward Keycloak to your workstation:

```bash
kubectl -n security port-forward svc/keycloak 8080:8080
```

Then open:

```text
http://localhost:8080
```

Default local-dev admin credentials are stored in `k8s/base/security/keycloak-admin-secret.yaml` and currently match the live Minikube deployment:

- username: `admin`
- password: `admin`

## Assumptions

- Minikube is already running and `kubectl` points to that cluster.
- A single local-dev Keycloak instance is used in namespace `security`.
- Keycloak runs in dev mode with the container image `quay.io/keycloak/keycloak:latest`.
- No production HA, ingress, or external PostgreSQL is configured here.
