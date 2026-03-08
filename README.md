# platform-infra

Local Kubernetes infrastructure source of truth for ScaffoldOps Minikube development.

## Scope

This repository currently owns the shared local-dev infrastructure that is visible in the cluster:

- bootstrap namespaces used by the ScaffoldOps platform
- shared PostgreSQL for platform services in the `scaffoldops` namespace
- Keycloak in the `security` namespace

This repository does not define product-specific application namespaces or workloads. Application repositories consume the shared infrastructure managed here.

## Structure

```text
k8s/
  base/
    kustomization.yaml
    database/
    namespaces/
    security/
  overlays/
    local-dev/
```

- `k8s/base/database`: shared PostgreSQL instance, PVC, service, secret, and init scripts
- `k8s/base/namespaces`: namespace bootstrap manifests
- `k8s/base/security`: shared security infrastructure for local dev
- `k8s/overlays/local-dev`: local Minikube entrypoint
- `.github/workflows`: validation and optional deployment workflow for the local-dev overlay

## Deploy

Preload the local-dev container images into Minikube, then apply the overlay:

```bash
./scripts/bootstrap-local-dev-images.sh
kubectl apply -k k8s/overlays/local-dev
```

If the images already exist in the Minikube node cache, the preload step is harmless. This avoids startup failures when the local cluster cannot reach Docker Hub or Quay during pod creation.

Apply only the local-dev overlay if image availability is already handled:

```bash
kubectl apply -k k8s/overlays/local-dev
```

Preview the rendered manifests:

```bash
kubectl kustomize k8s/overlays/local-dev
```

## Verify

Check that the expected namespaces, PostgreSQL resources, and Keycloak resources exist:

```bash
kubectl get ns
kubectl -n scaffoldops get deploy,svc,secret,pvc,configmap
kubectl -n security get deploy,svc,secret,pvc,configmap
kubectl -n security get pods
kubectl -n scaffoldops get pods
```

Expected local-dev Keycloak service DNS:

```text
http://keycloak.security.svc.cluster.local:8080
```

Expected local-dev PostgreSQL service DNS:

```text
postgres.scaffoldops.svc.cluster.local:5432
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

Keycloak's database password is stored separately in `k8s/base/security/keycloak-db-secret.yaml` because the Keycloak pod runs in the `security` namespace while PostgreSQL runs in `scaffoldops`, and Kubernetes secrets are namespace-scoped.

Shared PostgreSQL credentials are stored in `k8s/base/database/postgres-secret.yaml`. The bootstrap script creates one logical database per service inside the same PostgreSQL instance:

- `keycloakdb` owned by `keycloakuser`
- `generatorapidb` owned by `generatorapiuser`
- `generatorworkerdb` owned by `generatorworkeruser`
- `deploymentworkerdb` owned by `deploymentworkeruser`

## Assumptions

- Minikube is already running and `kubectl` points to that cluster.
- The active platform namespaces are `security` and `scaffoldops`.
- Energyco-specific namespace manifests have been removed from the active platform-infra kustomization path.
- A single local-dev PostgreSQL instance is used in namespace `scaffoldops`.
- A single local-dev Keycloak instance is used in namespace `security`.
- Keycloak runs in dev mode with the container image `quay.io/keycloak/keycloak:26.4.7`.
- PostgreSQL runs from `postgres:16` with one PVC and initializes logical databases only on first startup.
- No production HA, ingress, or external PostgreSQL is configured here.
