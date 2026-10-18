#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
environment="${1:?Usage: bash scripts/deploy-environment.sh dev|pre [true|false]}"
bootstrap="${2:-true}"
case "$environment" in dev|pre) ;; *) echo 'Expected dev or pre' >&2; exit 1 ;; esac
case "$bootstrap" in true|false) ;; *) echo 'Expected true or false' >&2; exit 1 ;; esac
namespace="scaffoldops-$environment"
rendered=$(mktemp)
trap 'rm -f "$rendered"' EXIT
python3 scripts/validate-readiness.py validate "$environment" --output "$rendered"
python3 scripts/validate-readiness.py preflight "$environment"
kubectl apply --dry-run=client -f "$rendered"
if [ "$bootstrap" = true ] && [ -n "$(kubectl get namespace "$namespace" --ignore-not-found -o name)" ]; then
  kubectl -n "$namespace" delete job minio-create-bucket kafka-topic-bootstrap --ignore-not-found --wait=true --timeout=120s
fi
kubectl apply -f "$rendered"
# Jobs are retained: missing jobs are errors, not assumed TTL-cleaned successes.
for job in minio-create-bucket kafka-topic-bootstrap; do
  kubectl -n "$namespace" get "job/$job" -o name
  kubectl -n "$namespace" wait --for=condition=complete "job/$job" --timeout=660s
done
for deployment in postgres kafka kafka-ui minio; do
  kubectl -n "$namespace" rollout status "deployment/$deployment" --timeout=300s
done
if [ "$environment" = dev ]; then
  kubectl -n scaffoldops rollout status deployment/postgres --timeout=300s
fi
kubectl -n security rollout status "deployment/keycloak-$environment" --timeout=300s
