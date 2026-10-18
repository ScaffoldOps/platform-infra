# platform-infra

Kubernetes infrastructure source of truth for ScaffoldOps shared platform environments.

This repository is the infrastructure source of truth for the shared platform components that support ScaffoldOps in Kubernetes. It does not own application business logic or per-service application manifests. Its job is to provide the common platform layer that application repositories depend on.

This repository currently owns the shared platform infrastructure that is visible in the cluster:

- bootstrap namespaces used by the ScaffoldOps platform
- shared PostgreSQL for platform services in the `scaffoldops` namespace
- Keycloak in the `security` namespace
- Kafka, Kafka UI, and topic bootstrap manifests in the `scaffoldops-dev` namespace
- MinIO Artifact Store, bucket bootstrap, and PostgreSQL DNS aliases in `scaffoldops-dev`

`platform-infra` exists to define and deploy the shared platform infrastructure used by ScaffoldOps. Today that includes:

Generated artifacts can use the shared MinIO Artifact Store. Filesystem storage
and its PVC remain application-owned when that backend is selected. PostgreSQL
stores ScaffoldOps request metadata, including artifactRef, imageRef,
deploymentStatus, and deploymentNamespace. Generated container images belong
in Docker Registry; MinIO stores artifacts, not Docker images.

## Structure

```text
.github/
  workflows/
    deploy.yml
    platform-infra.yml
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
    pre/
scripts/
  bootstrap-local-dev-images.sh
  deploy-environment.sh
  provision-pre.py
  validate-readiness.py
```

- `k8s/base/database`: shared PostgreSQL instance, PVC, service, secret, and init scripts
- `k8s/base/database-dev-aliases`: dev PostgreSQL Services selecting the PostgreSQL workload in `scaffoldops-dev`
- `k8s/base/minio`: local/dev MinIO, data PVC, credentials, and bucket bootstrap job
- `k8s/base/kafka`: single-node Kafka deployment, Kafka UI, service manifests, PVC, and topic bootstrap job
- `k8s/base/namespaces`: namespace bootstrap manifests
- `k8s/base/security`: shared security infrastructure for local dev
- `k8s/overlays/local-dev`: local Minikube entrypoint for namespaces, PostgreSQL, Keycloak, Kafka, Kafka UI, and MinIO
- `k8s/overlays/dev`: shared compatibility PostgreSQL plus isolated DEV infrastructure; never manages PRE
- `k8s/overlays/pre`: PRE-only infrastructure, external runtime Secrets, and `keycloak-pre` in `security`

- `.github/workflows`
  - `platform-infra.yml`: validation workflow for push and pull request events
  - `deploy.yml`: manual deployment workflow for the selected DEV or PRE overlay

- `k8s/base`
  - shared base Kustomize entrypoint that composes namespaces, database, and security resources

- `k8s/base/namespaces`
  - namespace manifests for `security` and `scaffoldops`

- `k8s/base/database`
  - shared PostgreSQL Deployment, Service, PVC, secret, and bootstrap ConfigMap
  - first-initialization bootstrap for roles and logical databases on new PVCs

- `k8s/base/security`
  - Keycloak Deployment, Service, and secrets

- `k8s/overlays/local-dev`
  - local Minikube overlay that points to the shared base
  - adds local-only PostgreSQL external access through a `NodePort` Service

- `scripts/bootstrap-local-dev-images.sh`
  - helper script to preload required images into Minikube before deploy

## Kustomize Structure

The repository currently follows this composition chain:

```text
k8s/overlays/local-dev
  -> ../dev
    -> ../../base
    -> namespaces
    -> database
    -> security
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
requests validate isolation, render and client-dry-run `local-dev`, `dev`, and `pre`. It has no deploy
job. The self-hosted runner uses `/home/victor/.kube/config`; API discovery and
schema access are needed for client dry-runs.

To restore infrastructure, open **GitHub Actions > deploy > Run workflow**.
Choose the branch (for example `develop`) with GitHub's **Use workflow from**
selector, then select the `environment` input:

- `dev` (default) applies `k8s/overlays/dev`, restoring namespaces, shared
  platform resources, dev PostgreSQL Services, Kafka, Kafka UI, Keycloak,
  MinIO, and bootstrap Jobs. DEV Keycloak runs in `security`; no PRE objects
  are rendered or scaled by DEV.
- `pre` maps exclusively to `k8s/overlays/pre`, creates `scaffoldops-pre` and
  `generated-pre`, and manages only PRE infrastructure plus the `keycloak-pre`
  Deployment and Service in `security`. It never applies Secret objects.

The separate `deploy.yml` workflow runs only on `workflow_dispatch`. It
validates the selected overlay before applying and serializes manual deploys
on the Minikube runner. Pushes and PRs never deploy.

`runBootstrapJobs` defaults to true. It deletes only `minio-create-bucket` and
`kafka-topic-bootstrap` Jobs in the selected `scaffoldops-dev` or
`scaffoldops-pre` namespace, using `--ignore-not-found`, then reapplies the
overlay. Both jobs initialize resources idempotently. With false, existing
Jobs are retained; missing Jobs are still created by apply. The workflow
always waits for both Jobs and all expected deployments; missing objects and
rollout failures are errors. Completed Jobs are retained until explicit
recreation, so their absence is never treated as evidence of success.

Applying restores missing declared resources. DEV includes its existing
credential manifests; PRE only references externally provisioned Secrets.
The workflow does not delete namespaces, PVCs, or
persisted MinIO, PostgreSQL, or Kafka data. Existing PVCs are reused. If storage
was deleted separately, applying cannot recover lost data.

## Verify

## Deployment Model

The infrastructure is deployed with Kustomize:

```bash
kubectl apply -k k8s/overlays/local-dev
```

The current deployment model is local-dev oriented:

- the active overlay is `k8s/overlays/local-dev`
- the target cluster is expected to be a local Minikube cluster
- the manual GitHub Actions deploy workflow assumes a self-hosted runner with access to the same local kubeconfig and Minikube environment

The workflows currently behave as follows:

- validation workflow:
  - validates isolation and renders local-dev, DEV and PRE overlays
  - performs client-side `kubectl apply --dry-run=client`

- manual deploy workflow:
  - renders the selected DEV or PRE overlay
  - preflights PRE runtime Secrets before changing infrastructure
  - validates manifests client-side
  - applies the overlay to the cluster

## Common Commands

Check the current Kubernetes context:

```bash
kubectl config current-context
kubectl cluster-info
```

Render manifests:

```bash
kubectl kustomize k8s/overlays/local-dev
```

Validate manifests locally:

```bash
kubectl kustomize k8s/overlays/local-dev > rendered-local-dev.yaml
kubectl apply --dry-run=client -f rendered-local-dev.yaml
```

Preload local-dev images into Minikube:

```bash
./scripts/bootstrap-local-dev-images.sh
```

Apply the overlay:

```bash
kubectl apply -k k8s/overlays/local-dev
```

Inspect platform resources:

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
PRE-specific credentials and a separate `keycloakpredb` database. The legacy
PRE `keycloakdb` database must remain unchanged.
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
generation-requested-dlt
artifact-cleanup-requested
deployment-requested
undeployment-requested
image-build-retry-requested
```

## MinIO Artifact Store

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
safe. It has a ten-minute deadline and completed Jobs are retained. Inspect a
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
`minio-credentials` is the canonical infrastructure Secret. DEV and local-dev also
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
the Job to complete; inspect its retained status and logs for evidence.

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

```bash
minikube ip
```

Keycloak's database password is stored separately in `k8s/base/security/keycloak-dev-db-secret.yaml` because the Keycloak pod runs in the `security` namespace while dev PostgreSQL runs in `scaffoldops-dev`, and Kubernetes secrets are namespace-scoped.

PostgreSQL is managed here as shared platform infrastructure.

Current model:

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
- `k8s/overlays/dev` deploys shared compatibility PostgreSQL and DEV infrastructure without touching PRE.
- PostgreSQL runs from `postgres:16` with one PVC in `scaffoldops`.
- The PostgreSQL init script is mounted from a ConfigMap and runs through `/docker-entrypoint-initdb.d`.
- Keycloak runs in dev mode with the container image `quay.io/keycloak/keycloak:26.1.4` in `security`.
- Kafka runs as a single-node KRaft broker from `confluentinc/cp-kafka:7.7.7` in `scaffoldops-dev`.
- Kafka UI runs from `provectuslabs/kafka-ui:v0.7.2` in `scaffoldops-dev` and connects to `kafka:9092`.
- The `generation-requested` and `artifact-cleanup-requested` topics are bootstrap-created by a Kubernetes Job in `scaffoldops-dev`.
- No ingress, HA topology, or external managed services are configured in this repository.

## MVP Environment

DEV identity:

- Keycloak service: `keycloak-dev.security.svc.cluster.local`
- Keycloak realm: `scaffoldops-dev`
- PRE is independently deployed and is never scaled by the DEV overlay.

## PRE Runbook

Use the selected cluster context deliberately. Requirements: `kubectl`, Bash,
Python 3 and PyYAML (`python3 -c 'import yaml'`); the provisioning utility uses
only the Python standard library. Validation does not deploy. The manual
workflow uses the same deployment script as these commands.

### Ownership and Storage

PRE owns infrastructure in `scaffoldops-pre`, creates `generated-pre` for
application-generated workloads, and manages only the `keycloak-pre`
Deployment/Service in existing namespace `security`. DEV and local-dev retain
the shared PostgreSQL instance in `scaffoldops` plus their separate DEV
PostgreSQL and `postgres`/`postgres-dev` ClusterIP Services in `scaffoldops-dev`.
Local-dev additionally exposes `postgres-external` on NodePort 30432.

Reuse PRE PVCs `postgres-data` and `kafka-data`; MinIO adds `minio-data` (5Gi).
Never delete PVCs, reset data directories, or run prune/namespace deletion to
recover a rollout. Back up existing data before database maintenance.
The PostgreSQL init scripts run only on an empty PVC, use top-level psql
`SELECT ... WHERE NOT EXISTS ... \gexec` (not variables inside dollar-quoted
DO blocks), and never rotate existing role passwords on restart or apply.

PRE Keycloak uses `postgres.scaffoldops-pre.svc.cluster.local:5432`, database
`keycloakpredb`, owner `keycloakuser`, and realm `scaffoldops-pre`. Do not point
it at legacy `keycloakdb`: that database has incompatible Liquibase checksums
and legacy realm state and must remain unchanged. For an existing PVC, create
only the new empty database with the explicit provisioner phase below. Fresh
PRE PVC initialization creates both databases without migrating the legacy one.

### Runtime Secret Contract

The PRE overlay emits **zero Secrets** and never overwrites PostgreSQL or
Keycloak credentials. The infrastructure preflight checks existence and
nonempty keys without printing values:

| Namespace | Secret | Required keys |
| --- | --- | --- |
| scaffoldops-pre | postgres-credentials | POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_KEYCLOAK_PASSWORD, POSTGRES_GENERATOR_API_PASSWORD, POSTGRES_GENERATOR_WORKER_PASSWORD, POSTGRES_DEPLOYMENT_WORKER_PASSWORD |
| scaffoldops-pre | minio-credentials | MINIO_ROOT_USER, MINIO_ROOT_PASSWORD |
| scaffoldops-pre | generator-worker-minio | access-key, secret-key |
| security | keycloak-pre-admin | KC_BOOTSTRAP_ADMIN_USERNAME, KC_BOOTSTRAP_ADMIN_PASSWORD |
| security | keycloak-pre-db | KC_DB_PASSWORD |

The database role password and `keycloak-pre-db` must already agree. Preflight
does not inspect password values or rotate credentials. Bootstrap admin
variables do not reset an existing Keycloak admin account.

The optional provisioning utility preserves existing MinIO credentials,
creates a unique password only if absent, and synchronizes the worker alias.
It copies `docker-hub-pull-secret` to `scaffoldops-pre` and `generated-pre` and
`docker-hub-credentials` to `scaffoldops-pre` only when missing, using DEV as
the explicitly shared registry credential source. It preserves other pull
secrets on the generated namespace's default ServiceAccount. It never changes
PostgreSQL or Keycloak admin/DB secrets. Do not log/dump Secret JSON.

### Review and Deploy

```bash
python3 scripts/validate-readiness.py validate
python3 scripts/validate-readiness.py validate pre --output /tmp/platform-infra-pre.yaml
python3 scripts/validate-readiness.py preflight pre
kubectl apply --dry-run=client -f /tmp/platform-infra-pre.yaml
```

For first-time provisioning or repair, run only the phases needed. These are
explicit live operations, never invoked by CI or infrastructure deployment:

```bash
python3 scripts/provision-pre.py runtime
# Requires the existing PRE PostgreSQL Deployment; creates only keycloakpredb if absent.
python3 scripts/provision-pre.py database
```

After review and with required secrets ready:

```bash
bash scripts/deploy-environment.sh pre true
```

The script validates the exact render it applies, preflights before mutations,
client-dry-runs, recreates only the two PRE bootstrap Jobs, applies, waits for
both Jobs, and requires rollouts of postgres/kafka/kafka-ui/minio/keycloak-pre.
No PVC or namespace deletion is used. `false` retains Jobs; missing Jobs are
still created and checked. Use `true` after changes to immutable Job templates
or to rerun bootstrap. Manual deployments should not overlap a workflow run.

Kafka uses the same working `confluentinc/cp-kafka:7.7.7` single-node config
as DEV, with quorum voters `1@localhost:9093`. If an existing broker still
crash-loops after apply, inspect logs and persisted cluster ID; do not clear
`kafka-data`. Topic bootstrap ensures all six topics listed above. MinIO uses
`pgsty/minio:latest` and `pgsty/mc:latest`, creates `scaffoldops-artifacts`, and
is reachable at `http://minio.scaffoldops-pre.svc.cluster.local:9000`.

### OAuth and Runtime Verification

After Keycloak starts on `keycloakpredb`:

PRE startup and readiness probes use `/health/started` and `/health/ready` on
management port 9000. Health and metrics are enabled so readiness includes the
database connection check. The Service exposes only application HTTP, not the
management port. See the version-matched
[Keycloak 26.1.4 health guide](https://github.com/keycloak/keycloak/blob/26.1.4/docs/guides/observability/health.adoc).
With these probes, rollout status waits for Keycloak readiness, not just a
running process. OAuth token issuance is checked separately by provisioning.

```bash
python3 scripts/provision-pre.py keycloak
kubectl -n scaffoldops-pre get deploy,svc,pvc,job
kubectl -n scaffoldops-pre logs job/kafka-topic-bootstrap
kubectl -n scaffoldops-pre logs job/minio-create-bucket
kubectl -n security rollout status deployment/keycloak-pre --timeout=300s
```

The utility idempotently creates realm `scaffoldops-pre` and confidential
service-account clients `scaffoldops-generator-worker` and `deployment-worker`.
It reads their existing client secrets without rotating them, synchronizes
`generator-api-worker-client` (`client-secret`) and `deployment-worker-oauth`
(`client-secret`, `token-url`) in `scaffoldops-pre`, and verifies token issuance
without logging tokens. The token URL is
`http://keycloak-pre.security.svc.cluster.local:8080/realms/scaffoldops-pre/protocol/openid-connect/token`.
Use `--port` to choose another local port if 19080 is occupied. Application
images, application deployments, authorization roles, and end-to-end API
checks remain owned by application repositories and runtime provisioning.
Test with published develop images before promoting any branch; no merge is
required to render or review these files.

### Regression Tests

```bash
python3 -m unittest discover -s tests -p test_readiness.py -v
# Includes a disposable Docker postgres:16 integration test; no Kubernetes writes.
python3 -m unittest discover -s tests -v
```

The PostgreSQL integration test exercises quoted passwords, fresh role/database
creation, repeated execution without password rotation, and preservation of a
legacy database marker. Its container uses tmpfs, never any cluster PVC.
