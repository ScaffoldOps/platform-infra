# platform-infra

Shared Kubernetes platform infrastructure for ScaffoldOps.

This repository is the infrastructure source of truth for the shared platform components that support ScaffoldOps in Kubernetes. It does not own application business logic or per-service application manifests. Its job is to provide the common platform layer that application repositories depend on.

ScaffoldOps is the platform project responsible for automated generation and deployment of microservices on Kubernetes. This repository exists so that the shared infrastructure for that platform can be managed independently from the generated services themselves.

## Repository Purpose

`platform-infra` exists to define and deploy the shared platform infrastructure used by ScaffoldOps. Today that includes:

- Kubernetes namespaces used by the platform
- shared PostgreSQL infrastructure
- Keycloak infrastructure and configuration
- Kustomize base and overlays for the platform layer
- GitHub Actions workflows for validation and manual deployment

This repository is intentionally infrastructure-focused. It is the place for cluster-level shared services that multiple ScaffoldOps services will consume.

## Ownership And Scope

This repository owns:

- shared platform namespaces
- PostgreSQL manifests, secrets, service, PVC, and bootstrap configuration
- Keycloak manifests and supporting secrets
- Kustomize base and overlays for shared infrastructure
- platform infrastructure deployment workflows

This repository does not own:

- business logic for application services
- per-application Deployments, Services, or ConfigMaps for product services
- service-specific CI/CD logic outside shared platform infrastructure
- unrelated future project infrastructure that is not part of the active ScaffoldOps MVP

Boundary rule:

- `platform-infra` owns shared infrastructure
- application repositories such as `generator-api` own only their own service deployment and runtime configuration

Architectural note:

- PostgreSQL is shared infrastructure and belongs here
- Keycloak is a supporting platform component and belongs here
- Energyco is a separate future project and should not be mixed into the active ScaffoldOps MVP unless that is explicitly intended later

## Current Platform Components

The repository currently manages the following platform components:

- `security` namespace
- `scaffoldops` namespace
- one shared PostgreSQL instance in `scaffoldops`
- one Keycloak instance in `security`
- a local-dev Kustomize overlay
- GitHub Actions workflows for validation and manual deployment

## Kubernetes Architecture

The current intended local-dev architecture is:

- `security` namespace:
  - Keycloak Deployment
  - Keycloak Service
  - Keycloak admin secret
  - Keycloak database password secret

- `scaffoldops` namespace:
  - shared PostgreSQL Deployment
  - PostgreSQL Service
  - PostgreSQL NodePort Service for local external access
  - PostgreSQL PVC
  - PostgreSQL credentials secret
  - PostgreSQL bootstrap ConfigMap

The PostgreSQL model is shared-instance, multi-database:

- one PostgreSQL instance serves multiple platform services
- each service gets its own logical database and database user
- Keycloak uses the shared PostgreSQL instance through the in-cluster DNS name `postgres.scaffoldops.svc.cluster.local`

This keeps local-dev simple while preserving separation at the database level for platform services.

## Directory Structure

```text
.github/
  workflows/
    deploy.yml
    platform-infra.yml
k8s/
  base/
    kustomization.yaml
    database/
    namespaces/
    security/
  overlays/
    local-dev/
scripts/
  bootstrap-local-dev-images.sh
```

Directory purpose:

- `.github/workflows`
  - `platform-infra.yml`: validation workflow for push and pull request events
  - `deploy.yml`: manual deployment workflow for the local-dev overlay

- `k8s/base`
  - shared base Kustomize entrypoint that composes namespaces, database, and security resources

- `k8s/base/namespaces`
  - namespace manifests for `security` and `scaffoldops`

- `k8s/base/database`
  - shared PostgreSQL Deployment, Service, PVC, secret, and bootstrap ConfigMap
  - database bootstrap logic that reconciles roles and logical databases for platform services

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
  -> ../../base
    -> namespaces
    -> database
    -> security
```

Render the full local-dev manifest with:

```bash
kubectl kustomize k8s/overlays/local-dev
```

The local-dev overlay keeps the in-cluster PostgreSQL `ClusterIP` Service at
`postgres.scaffoldops.svc.cluster.local:5432` and adds a second Service named
`postgres-external` exposed as `NodePort` `30432` for local tools running
outside Kubernetes.

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
  - renders the local-dev overlay
  - performs client-side `kubectl apply --dry-run=client`

- manual deploy workflow:
  - preloads required images into Minikube
  - renders the local-dev overlay
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
kubectl -n scaffoldops get deploy,svc,pvc,configmap,secret,pods
kubectl -n security get deploy,svc,secret,pods
```

Debug pods:

```bash
kubectl -n scaffoldops describe pod <pod-name>
kubectl -n security describe pod <pod-name>
kubectl -n scaffoldops logs deploy/postgres
kubectl -n security logs deploy/keycloak
```

Port-forward Keycloak locally:

```bash
kubectl -n security port-forward svc/keycloak 8080:8080
```

Then open:

```text
http://localhost:8080
```

Get the Minikube IP for external PostgreSQL access:

```bash
minikube ip
```

## PostgreSQL

PostgreSQL is managed here as shared platform infrastructure.

Current model:

- one PostgreSQL instance in namespace `scaffoldops`
- one persistent volume claim for the shared instance
- one logical database per platform service
- one service-specific database user per logical database

Current logical databases created by the bootstrap script:

- `keycloakdb`
- `generatorapidb`
- `generatorworkerdb`
- `deploymentworkerdb`

Current service users created by the bootstrap script:

- `keycloakuser`
- `generatorapiuser`
- `generatorworkeruser`
- `deploymentworkeruser`

Operational note:

- the bootstrap ConfigMap is designed to reconcile roles and logical databases on container start so reused PVCs do not leave the platform in an inconsistent state

## Keycloak

Keycloak is managed here as a supporting platform component.

In ScaffoldOps, Keycloak is intended to provide:

- authentication
- token issuance
- identity and access management for platform APIs
- a shared auth component for services that need platform-level access control

Keycloak is not the thesis or product core by itself. It is supporting infrastructure that enables authentication and protected service access across the platform.

Current local-dev configuration:

- namespace: `security`
- service name: `keycloak`
- image: `quay.io/keycloak/keycloak:26.4.7`
- dev startup mode: `start-dev`
- backing database: `keycloakdb` on the shared PostgreSQL instance

Expected in-cluster endpoints:

- Keycloak: `http://keycloak.security.svc.cluster.local:8080`
- PostgreSQL: `postgres.scaffoldops.svc.cluster.local:5432`

## Secrets And Credentials

The repository currently stores local-dev secrets directly in manifests. This is acceptable for the current MVP local-dev setup, but it is not a production-grade secret-management model.

Current examples:

- Keycloak admin credentials in `k8s/base/security/keycloak-admin-secret.yaml`
- Keycloak database password in `k8s/base/security/keycloak-db-secret.yaml`
- shared PostgreSQL credentials and service passwords in `k8s/base/database/postgres-secret.yaml`

## Operational Notes

- Minikube lifecycle matters. `minikube stop`, `minikube start`, and especially `minikube delete` can affect PVC state, image cache availability, and platform startup behavior.
- The local-dev overlay assumes Minikube is already running and `kubectl` points to that cluster.
- The manual deploy workflow depends on a self-hosted runner that has access to `/home/victor/.kube/config` and the local Minikube environment.
- Shared infrastructure should be changed here. Application-specific runtime config should be changed in the owning app repository.
- Do not mix Energyco resources into this repository unless they are intentionally part of the active ScaffoldOps platform scope.
- This repository currently documents and deploys local-dev infrastructure only. It does not yet provide a separate staging or production overlay.

## Future Improvements

Likely future additions for this repository include:

- staging and possibly production overlays
- ingress or API gateway configuration
- stronger secret management such as Sealed Secrets, External Secrets, or another managed approach
- additional shared platform components such as Kafka if the platform requires event-driven messaging
- stronger readiness, monitoring, and operational policies for shared services

## Current Assumptions And Limits

- Minikube is the active target cluster for local development
- the main shared namespaces are `security` and `scaffoldops`
- PostgreSQL and Keycloak are the only shared platform components currently defined here
- no ingress, no HA database setup, and no external managed PostgreSQL are configured in this repository today
