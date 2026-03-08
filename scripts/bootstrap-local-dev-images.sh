#!/usr/bin/env bash

set -euo pipefail

images=(
  "postgres:16"
  "quay.io/keycloak/keycloak:latest"
)

for image in "${images[@]}"; do
  echo "Loading ${image} into Minikube..."
  minikube image load "${image}"
done

echo "Minikube image preload complete."
