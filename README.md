# platform-infra

Kubernetes infrastructure source of truth for ScaffoldOps shared platform environments.

## Scope

This repository currently owns the shared platform infrastructure that is visible in the cluster:

- bootstrap namespaces used by the ScaffoldOps platform
- shared PostgreSQL for platform services in the `scaffoldops` namespace
- Keycloak in the `security` namespace
- Kafka and topic bootstrap manifests in the `scaffoldops-dev` namespace

This repository does not define product-specific application namespaces or workloads. Application repositories consume the shared infrastructure managed here.

## Structure

```text
k8s/
  base/
    kustomization.yaml
    database/
    kafka/
    namespaces/
    security/
  overlays/
    dev/
    local-dev/
```

- `k8s/base/database`: shared PostgreSQL instance, PVC, service, secret, and init scripts
- `k8s/base/kafka`: single-node Kafka deployment, service, PVC, and topic bootstrap job
- `k8s/base/namespaces`: namespace bootstrap manifests
- `k8s/base/security`: shared security infrastructure for local dev
- `k8s/overlays/local-dev`: local Minikube entrypoint for namespaces, PostgreSQL, Keycloak, and Kafka
- `k8s/overlays/dev`: dev entrypoint for namespaces, Kafka, and topic bootstrap

## Deploy

Apply the local-dev overlay:

```bash
kubectl apply -k k8s/overlays/local-dev
```

Apply the dev overlay:

```bash
kubectl apply -k k8s/overlays/dev
```

Preview the rendered manifests:

```bash
kubectl kustomize k8s/overlays/local-dev
kubectl kustomize k8s/overlays/dev
```

## Verify

Check that the expected namespaces, PostgreSQL resources, and Keycloak resources exist:

```bash
kubectl get ns
kubectl -n scaffoldops get deploy,svc,secret,pvc,configmap
kubectl -n security get deploy,svc,secret,pvc,configmap
kubectl -n scaffoldops-dev get deploy,svc,pvc,job
kubectl -n security get pods
kubectl -n scaffoldops get pods
kubectl -n scaffoldops-dev get pods
```

Expected local-dev Keycloak service DNS:

```text
http://keycloak.security.svc.cluster.local:8080
```

Expected local-dev PostgreSQL service DNS:

```text
postgres.scaffoldops.svc.cluster.local:5432
```

Expected dev Kafka service DNS:

```text
kafka.scaffoldops-dev.svc.cluster.local:9092
```

Expected Kafka topic ensured by platform-infra:

```text
generation-requested
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

Kafka is included in the active base render path, so `k8s/overlays/local-dev` and `k8s/overlays/dev` both render the broker resources in `scaffoldops-dev`.

The topic bootstrap job creates `generation-requested` against `kafka:9092` with `--if-not-exists`, `partitions=1`, and `replication-factor=1`. The job is intentionally infra-owned so application deployments do not depend on manual topic creation.

## Assumptions

- `kubectl` points to the target cluster before applying an overlay.
- The active platform namespaces managed here are `security`, `scaffoldops`, and `scaffoldops-dev`.
- `k8s/overlays/local-dev` deploys namespaces, PostgreSQL, Keycloak, Kafka, and the Kafka topic bootstrap job.
- `k8s/overlays/dev` deploys namespaces, Kafka, and the Kafka topic bootstrap job.
- PostgreSQL runs from `postgres:16` with one PVC in `scaffoldops`.
- The PostgreSQL init script is mounted from a ConfigMap and runs through `/docker-entrypoint-initdb.d`.
- Keycloak runs in dev mode with the container image `quay.io/keycloak/keycloak:latest` in `security`.
- Kafka runs as a single-node KRaft broker from `confluentinc/cp-kafka:7.7.7` in `scaffoldops-dev`.
- The `generation-requested` topic is bootstrap-created by a Kubernetes Job in `scaffoldops-dev`.
- No ingress, HA topology, or external managed services are configured in this repository.
