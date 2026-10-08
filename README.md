# platform-infra

Kubernetes infrastructure source of truth for ScaffoldOps shared platform environments.

## Scope

This repository currently owns the shared platform infrastructure that is visible in the cluster:

- bootstrap namespaces used by the ScaffoldOps platform
- shared PostgreSQL for platform services in the `scaffoldops` namespace
- Keycloak in the `security` namespace
- Kafka, Kafka UI, and topic bootstrap manifests in the `scaffoldops-dev` namespace
- MinIO Artifact Store, bucket bootstrap, and PostgreSQL DNS aliases in `scaffoldops-dev`

This repository does not define product-specific application namespaces or workloads. Application repositories consume the shared infrastructure managed here.

Generated artifacts can use the shared MinIO Artifact Store. Filesystem storage
and its PVC remain application-owned when that backend is selected. PostgreSQL
stores ScaffoldOps request metadata, including artifactRef, imageRef,
deploymentStatus, and deploymentNamespace. Generated container images belong
in Docker Registry; MinIO stores artifacts, not Docker images.

## Structure

```text
k8s/
  base/
    kustomization.yaml
    database/
    database-dev-aliases/
    minio/
    kafka/
    namespaces/
    security/
  overlays/
    dev/
    local-dev/
```

- `k8s/base/database`: shared PostgreSQL instance, PVC, service, secret, and init scripts
- `k8s/base/database-dev-aliases`: dev PostgreSQL Services selecting the PostgreSQL workload in `scaffoldops-dev`
- `k8s/base/minio`: local/dev MinIO, data PVC, credentials, and bucket bootstrap job
- `k8s/base/kafka`: single-node Kafka deployment, Kafka UI, service manifests, PVC, and topic bootstrap job
- `k8s/base/namespaces`: namespace bootstrap manifests
- `k8s/base/security`: shared security infrastructure for local dev
- `k8s/overlays/local-dev`: local Minikube entrypoint for namespaces, PostgreSQL, Keycloak, Kafka, Kafka UI, and MinIO
- `k8s/overlays/dev`: complete DEV entrypoint for the shared base infrastructure; PRE Keycloak is scaled to zero

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

## GitHub Actions

**platform-infra** is validation only. Pushes to `main` and `develop` and pull
requests render and client-dry-run both `local-dev` and `dev`. It has no deploy
job. The self-hosted runner uses `/home/victor/.kube/config`; API discovery and
schema access are needed for client dry-runs.

To restore infrastructure, open **GitHub Actions > deploy > Run workflow**.
Choose the branch (for example `develop`) with GitHub's **Use workflow from**
selector, then select the `environment` input:

- `dev` (default) applies `k8s/overlays/dev`, restoring namespaces, shared
  platform resources, dev PostgreSQL Services, Kafka, Kafka UI, Keycloak,
  MinIO, and bootstrap Jobs. DEV Keycloak runs in `security`; PRE Keycloak is
  kept scaled to zero.
- `pre` maps exclusively to `k8s/overlays/pre`. That overlay is not implemented
  yet: only partial PRE Keycloak resources exist. Selecting PRE fails clearly
  before any cluster changes; it never falls back to DEV.

The separate `deploy.yml` workflow runs only on `workflow_dispatch`. It
validates the selected overlay before applying and serializes manual deploys
on the Minikube runner. Pushes and PRs never deploy.

`runBootstrapJobs` defaults to true. It deletes only `minio-create-bucket` and
`kafka-topic-bootstrap` Jobs in the selected `scaffoldops-dev` or
`scaffoldops-pre` namespace, using `--ignore-not-found`, then reapplies the
overlay. Both jobs initialize resources idempotently. With false, existing
Jobs are retained; missing Jobs are still created by apply. The workflow
waits for both Jobs when requested and checks present deployments; rollout
failures are reported instead of ignored.

Applying restores missing Deployments, Services, ConfigMaps, Secrets, and
other declared resources. The workflow does not delete namespaces, PVCs, or
persisted MinIO, PostgreSQL, or Kafka data. Existing PVCs are reused. If storage
was deleted separately, applying cannot recover lost data.

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

Expected DEV Keycloak service DNS for the MVP:

```text
http://keycloak-dev.security.svc.cluster.local:8080
```

The active MVP realm is `scaffoldops-dev`. Application resource servers should
use the realm JWKS endpoint directly when they need to accept tokens issued via
a local Keycloak port-forward:

```text
http://keycloak-dev.security.svc.cluster.local:8080/realms/scaffoldops-dev/protocol/openid-connect/certs
```

Expected local-dev PostgreSQL service DNS:

```text
postgres.scaffoldops.svc.cluster.local:5432
```

Development uses the PostgreSQL workload and `postgres-data` PVC in
`scaffoldops-dev`. Both `postgres:5432` and `postgres-dev:5432` Services in
that namespace select its `app=postgres` pods. `keycloak-dev` connects to
`postgres.scaffoldops-dev.svc.cluster.local`, database `keycloakdb`, with the
`keycloak-dev-db` Secret. Do not point dev Keycloak at
`postgres.scaffoldops.svc.cluster.local`: that is the separate shared
PostgreSQL instance and contains different realm state. The `scaffoldops`
PostgreSQL Deployment and PVC remain unchanged.

The active dev realm is `scaffoldops-dev`, matching generator-api JWKS
validation and generator-worker token requests. PRE Keycloak is configured for
`postgres.scaffoldops-pre.svc.cluster.local` and database `keycloakdb`, with
PRE-specific credentials; a complete PRE overlay is not yet implemented.
Local/dev Keycloak admin credentials are `admin` / `admin123` from
`keycloak-dev-admin`. Keycloak bootstrap admin environment settings only
create the account when the master realm is first initialized. If an existing
database has incompatible or stale Keycloak state, investigate and back up
that data before any manual reset. Do not delete PVCs as part of deployment.

Expected dev Kafka service DNS:

```text
kafka.scaffoldops-dev.svc.cluster.local:9092
```

Expected dev Kafka UI service DNS:

```text
kafka-ui.scaffoldops-dev.svc.cluster.local:8080
```

Expected Kafka topics ensured by platform-infra:

```text
generation-requested
artifact-cleanup-requested
```

## MinIO Artifact Store (local/dev only)

Local/dev Minikube uses the public community-maintained images
`pgsty/minio:latest` and `pgsty/mc:latest` from Docker Hub. The requested
`quay.io/minio/minio:latest` and `quay.io/minio/mc:latest` returned unauthorized
when tested, so these compatible MinIO community images are used instead.
Both images were pulled successfully and tested with `minio server /data
--console-address :9001`, `mc alias set`, `mc ready`, and repeated
`mc mb --ignore-existing` bucket creation. See the publisher's
[server image](https://hub.docker.com/r/pgsty/minio) and
[client image](https://hub.docker.com/r/pgsty/mc) documentation.
Production should pin tested image versions or digests rather than `latest`.
The current `IfNotPresent` pull policy can reuse a node's cached `latest` image.

MinIO runs as a single replica in `scaffoldops-dev`, persists data on
`minio-data` (5Gi), and exposes the S3 API at `http://minio:9000` to workloads
in that namespace. Cross-namespace clients use
`http://minio.scaffoldops-dev.svc.cluster.local:9000`.
The `minio-create-bucket` Job retries until MinIO is ready and creates
`scaffoldops-artifacts` with `mc mb --ignore-existing`, so repeated runs are
safe. It has a ten-minute deadline and completed Jobs are removed after five
minutes. Reapplying the overlay after removal runs bootstrap again. Inspect a
failed Job's logs; after resolving the cause, delete only the Job and reapply:

```bash
kubectl -n scaffoldops-dev logs job/minio-create-bucket
kubectl -n scaffoldops-dev delete job minio-create-bucket
kubectl apply -k k8s/overlays/dev
```

Configure `generator-worker` in its own repository with:

```yaml
env:
  - name: GENERATOR_ARTIFACT_STORAGE_TYPE
    value: minio
  - name: GENERATOR_ARTIFACT_MINIO_ENDPOINT
    value: http://minio:9000
  - name: GENERATOR_ARTIFACT_MINIO_BUCKET
    value: scaffoldops-artifacts
  - name: GENERATOR_MINIO_ACCESS_KEY
    valueFrom:
      secretKeyRef:
        name: minio-credentials
        key: MINIO_ROOT_USER
  - name: GENERATOR_MINIO_SECRET_KEY
    valueFrom:
      secretKeyRef:
        name: minio-credentials
        key: MINIO_ROOT_PASSWORD
```

The requested endpoint/bucket names above describe the target configuration.
The current sibling `generator-worker` checkout instead binds
`GENERATOR_MINIO_ENDPOINT` and `GENERATOR_MINIO_BUCKET`; use those names with
the same values until it supports `GENERATOR_ARTIFACT_MINIO_ENDPOINT` and
`GENERATOR_ARTIFACT_MINIO_BUCKET`. Its credential variables are
`GENERATOR_MINIO_ACCESS_KEY` and `GENERATOR_MINIO_SECRET_KEY`, as shown above.
`minio-credentials` is the canonical infrastructure Secret. Both overlays also
provide a compatibility Secret named `generator-worker-minio` in
`scaffoldops-dev`, matching the current worker deployment's `access-key` and
`secret-key` references. Kustomize copies these values from `MINIO_ROOT_USER`
and `MINIO_ROOT_PASSWORD` in the canonical Secret when rendering; this is a
separate Secret, not a live Kubernetes alias. Edit the canonical manifest and
reapply the overlay to keep both synchronized. Apply the overlay before
rolling out the worker to resolve its missing-Secret error. The worker should
eventually reference `minio-credentials` directly using its canonical keys,
as in the example above.
No worker manifests are changed here.

The Secret and worker must be in the same namespace for these references.
The checked-in `minioadmin` / `minioadmin` credentials are public, local
Minikube defaults only, and are unsuitable for production. This setup has no
TLS or HA and does not provision a Docker Registry. Application workloads and
backend selection are managed outside this repository.

Check MinIO and bucket initialization:

```bash
kubectl -n scaffoldops-dev rollout status deployment/minio
kubectl -n scaffoldops-dev wait --for=condition=complete job/minio-create-bucket --timeout=600s
kubectl -n scaffoldops-dev port-forward svc/minio 9000:9000 9001:9001
```

The console is available at `http://localhost:9001` while forwarding. Wait for
the Job before its five-minute cleanup window expires; if it has already been
removed, inspect the bucket in the console or reapply the overlay.

Artifact cleanup is application-owned and asynchronous:

```text
DELETE /generation-requests/{id}
  -> generator-api deletes the request record and publishes artifact-cleanup-requested
  -> Kafka topic artifact-cleanup-requested
  -> generator-worker consumes the event
  -> generator-worker deletes the artifact using its configured storage backend
```

`generator-api` owns request lifecycle state and the deletion API.
`generator-worker` owns generated artifacts and storage cleanup. `generator-api`
must not access the worker PVC directly. Cleanup is eventually consistent, not
transactional with the PostgreSQL delete. If `generator-worker` is down,
cleanup waits until Kafka is consumed; full reconciliation of stuck cleanup or
generation states remains future work.

Operational cleanup check for the filesystem backend (for MinIO, inspect the artifact in the bucket instead):

```bash
kubectl -n scaffoldops-dev exec deploy/generator-worker -- ls -la /var/lib/generator-worker/manifests
curl -fsS -X DELETE \
  -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8081/api/generator/v1/generation-requests/<requestId>"
kubectl -n scaffoldops-dev logs deploy/generator-worker --tail=150 | grep -i cleanup
kubectl -n scaffoldops-dev exec deploy/generator-worker -- test ! -d /var/lib/generator-worker/manifests/<serviceName>-<requestId>
```

## Port Forward Keycloak

Forward Keycloak to your workstation:

```bash
kubectl -n security port-forward svc/keycloak-dev 8080:8080
```

Then open:

```text
http://localhost:8080
```

Default local-dev admin credentials are stored in `k8s/base/security/keycloak-dev-admin-secret.yaml` and currently match the live Minikube deployment:

- username: `admin`
- password: `admin`

Keycloak's database password is stored separately in `k8s/base/security/keycloak-dev-db-secret.yaml` because the Keycloak pod runs in the `security` namespace while dev PostgreSQL runs in `scaffoldops-dev`, and Kubernetes secrets are namespace-scoped.

Shared PostgreSQL credentials are stored in `k8s/base/database/postgres-secret.yaml`. The bootstrap script creates one logical database per service inside the same PostgreSQL instance:

- `keycloakdb` owned by `keycloakuser`
- `generatorapidb` owned by `generatorapiuser`
- `generatorworkerdb` owned by `generatorworkeruser`
- `deploymentworkerdb` owned by `deploymentworkeruser`

Kafka is included in the active base render path, so `k8s/overlays/local-dev` and `k8s/overlays/dev` both render the broker resources in `scaffoldops-dev`.

The topic bootstrap job creates `generation-requested` and
`artifact-cleanup-requested` against `kafka:9092` with `--if-not-exists`,
`partitions=1`, and `replication-factor=1`. The job is intentionally
infra-owned so application deployments do not depend on manual topic creation.

Kafka UI runs in `scaffoldops-dev` for local and dev inspection. Use it to
browse brokers, topics, consumer groups, inspect messages, and publish test
messages manually to topics such as `generation-requested` and
`artifact-cleanup-requested`.

## Port Forward Kafka UI

Forward Kafka UI to your workstation:

```bash
kubectl -n scaffoldops-dev port-forward svc/kafka-ui 8080:8080
```

Then open:

```text
http://localhost:8080
```

## Assumptions

- `kubectl` points to the target cluster before applying an overlay.
- The active platform namespaces managed here are `security`, `scaffoldops`, and `scaffoldops-dev`.
- `k8s/overlays/local-dev` deploys namespaces, PostgreSQL, Keycloak, Kafka, Kafka UI, MinIO, PostgreSQL aliases, and both bootstrap jobs.
- `k8s/overlays/dev` deploys the full shared base infrastructure and scales PRE Keycloak to zero.
- PostgreSQL runs from `postgres:16` with one PVC in `scaffoldops`.
- The PostgreSQL init script is mounted from a ConfigMap and runs through `/docker-entrypoint-initdb.d`.
- Keycloak runs in dev mode with the container image `quay.io/keycloak/keycloak:latest` in `security`.
- Kafka runs as a single-node KRaft broker from `confluentinc/cp-kafka:7.7.7` in `scaffoldops-dev`.
- Kafka UI runs from `provectuslabs/kafka-ui:v0.7.2` in `scaffoldops-dev` and connects to `kafka:9092`.
- The `generation-requested` and `artifact-cleanup-requested` topics are bootstrap-created by a Kubernetes Job in `scaffoldops-dev`.
- No ingress, HA topology, or external managed services are configured in this repository.

## MVP Environment

For the MVP only DEV is active:

- Keycloak service: `keycloak-dev.security.svc.cluster.local`
- Keycloak realm: `scaffoldops-dev`
- PRE can stay powered off unless it is explicitly needed later.

Scale PRE Keycloak down with:

```bash
kubectl -n security scale deploy/keycloak-pre --replicas=0
```
