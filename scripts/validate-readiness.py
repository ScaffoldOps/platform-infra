#!/usr/bin/env python3
"""Render isolation checks and key-only runtime-secret preflight (requires PyYAML)."""
import argparse
from pathlib import Path
import subprocess
import shlex
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOPICS = {
    "generation-requested", "generation-requested-dlt", "artifact-cleanup-requested",
    "deployment-requested", "undeployment-requested", "image-build-retry-requested",
}
POSTGRES_KEYS = {
    "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_KEYCLOAK_PASSWORD",
    "POSTGRES_GENERATOR_API_PASSWORD", "POSTGRES_GENERATOR_WORKER_PASSWORD",
    "POSTGRES_DEPLOYMENT_WORKER_PASSWORD",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def render(environment):
    rendered = subprocess.check_output(
        ["kubectl", "kustomize", str(ROOT / "k8s/overlays" / environment)], text=True
    )
    objects = [obj for obj in yaml.safe_load_all(rendered) if obj]
    index = {}
    for obj in objects:
        kind, meta = obj["kind"], obj["metadata"]
        namespace, name = meta.get("namespace", ""), meta["name"]
        identity = (kind, namespace, name)
        require(identity not in index, f"Duplicate resource: {identity}")
        index[identity] = obj
        if kind == "Namespace":
            allowed = {"scaffoldops-pre", "generated-pre"} if environment == "pre" else {
                "scaffoldops", "scaffoldops-dev", "security"
            }
            require(name in allowed, f"{environment}: forbidden Namespace {name}")
        elif environment == "pre":
            require(namespace == "scaffoldops-pre" or (
                namespace == "security" and name == "keycloak-pre"
                and kind in {"Deployment", "Service"}
            ), f"PRE resource outside isolation boundary: {identity}")
            require(kind != "Secret", "PRE must not manage runtime Secrets")
        else:
            require(namespace in {"scaffoldops", "scaffoldops-dev", "security"},
                    f"DEV resource outside isolation boundary: {identity}")
            require(namespace != "security" or name.startswith("keycloak-dev"),
                    f"DEV must not manage PRE security resources: {identity}")
        require("scaffoldops-dev" not in yaml.safe_dump(obj) if environment == "pre"
                else "scaffoldops-pre" not in yaml.safe_dump(obj),
                f"Cross-environment reference: {identity}")

    ns = "scaffoldops-pre" if environment == "pre" else "scaffoldops-dev"
    required = {("Namespace", "", ns)}
    required |= {("Deployment", ns, name) for name in ("postgres", "kafka", "kafka-ui", "minio")}
    required |= {("Service", ns, name) for name in ("postgres", "kafka", "kafka-ui", "minio")}
    required |= {("PersistentVolumeClaim", ns, name) for name in ("postgres-data", "kafka-data", "minio-data")}
    required |= {("Job", ns, name) for name in ("kafka-topic-bootstrap", "minio-create-bucket")}
    kc = "keycloak-pre" if environment == "pre" else "keycloak-dev"
    required |= {(kind, "security", kc) for kind in ("Deployment", "Service")}
    if environment == "pre":
        required.add(("Namespace", "", "generated-pre"))
    else:
        required |= {(kind, "scaffoldops", name) for kind, name in (
            ("Deployment", "postgres"), ("Service", "postgres"),
            ("PersistentVolumeClaim", "postgres-data"))}
        required.add(("Service", ns, "postgres-dev"))
    require(required <= index.keys(), f"{environment}: missing resources {required - index.keys()}")
    for name in ("postgres", "postgres-dev") if environment != "pre" else ("postgres",):
        service = index[("Service", ns, name)]
        require(service["spec"].get("type", "ClusterIP") == "ClusterIP", "Postgres aliases must remain ClusterIP")
        labels = index[("Deployment", ns, "postgres")]["spec"]["template"]["metadata"]["labels"]
        require(service["spec"]["selector"].items() <= labels.items(), "Postgres alias selector has no workload")
    kafka = index[("Deployment", ns, "kafka")]["spec"]["template"]["spec"]["containers"][0]
    require(kafka["image"] == "confluentinc/cp-kafka:7.7.7", "Unexpected Kafka version")
    env = {item["name"]: item.get("value") for item in kafka["env"]}
    require(env["KAFKA_CONTROLLER_QUORUM_VOTERS"] == "1@localhost:9093", "Invalid single-node quorum")
    job = index[("Job", ns, "kafka-topic-bootstrap")]
    command = job["spec"]["template"]["spec"]["containers"][0]["command"][-1]
    tokens = shlex.shlex(command, posix=True, punctuation_chars=True)
    tokens.whitespace_split = True
    require(TOPICS <= set(tokens), "Topic bootstrap must include all six platform topics")
    for name in ("kafka-topic-bootstrap", "minio-create-bucket"):
        require("ttlSecondsAfterFinished" not in index[("Job", ns, name)]["spec"],
                "Retain bootstrap evidence until explicit job recreation")
    for identity, obj in index.items():
        if identity[0] != "ConfigMap":
            continue
        scripts = "\n".join(obj.get("data", {}).values())
        require("ALTER ROLE" not in scripts, "Bootstrap must not rotate existing role passwords")
        require("DO $$" not in scripts, "Use top-level psql substitution, not dollar-quoted DO")
    if environment == "pre":
        container = index[("Deployment", "security", kc)]["spec"]["template"]["spec"]["containers"][0]
        env = {item["name"]: item.get("value") for item in container["env"]}
        require(env["KC_DB_URL_DATABASE"] == "keycloakpredb", "Preserve legacy keycloakdb")
        require(env["KC_DB_URL_HOST"] == "postgres.scaffoldops-pre.svc.cluster.local", "Wrong PRE database host")
        require(env.get("KC_HEALTH_ENABLED") == "true" and env.get("KC_METRICS_ENABLED") == "true",
                "PRE Keycloak must expose readiness including database health")
        for probe, path in (("startupProbe", "/health/started"), ("readinessProbe", "/health/ready")):
            require(container.get(probe, {}).get("httpGet") == {"path": path, "port": "management"},
                    f"Missing PRE Keycloak {probe}")
    return rendered, index


def preflight(environment):
    _, index = render(environment)
    if environment != "pre":
        print("DEV uses its existing checked-in credential manifests; no PRE Secrets queried")
        return
    required = {
        ("scaffoldops-pre", "postgres-credentials"): set(POSTGRES_KEYS),
        ("scaffoldops-pre", "minio-credentials"): {"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"},
        ("scaffoldops-pre", "generator-worker-minio"): {"access-key", "secret-key"},
    }
    for (kind, ns, _), obj in index.items():
        if kind not in {"Deployment", "Job"}:
            continue
        pod = obj["spec"]["template"]["spec"]
        for container in pod.get("containers", []) + pod.get("initContainers", []):
            for env in container.get("env", []):
                ref = env.get("valueFrom", {}).get("secretKeyRef")
                if ref and not ref.get("optional"):
                    required.setdefault((ns, ref["name"]), set()).add(ref["key"])
            for env in container.get("envFrom", []):
                ref = env.get("secretRef")
                if ref and not ref.get("optional"):
                    require((ns, ref["name"]) in required, f"Declare envFrom key contract for {ref['name']}")
    failed = False
    # The API returns only names of nonempty keys, never encoded or decoded values.
    template = '{{range $k, $v := .data}}{{if $v}}{{printf "%s\\n" $k}}{{end}}{{end}}'
    for (ns, name), keys in sorted(required.items()):
        result = subprocess.run(["kubectl", "-n", ns, "get", "secret", name,
                                 "-o", "go-template=" + template], text=True, capture_output=True)
        missing = keys - set(result.stdout.splitlines())
        if result.returncode or missing:
            failed = True
            print(f"MISSING {ns}/{name}: {', '.join(sorted(missing or keys))}", file=sys.stderr)
        else:
            print(f"OK {ns}/{name}: {', '.join(sorted(keys))}")
    require(not failed, "Runtime secret preflight failed; no infrastructure has been changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "preflight"))
    parser.add_argument("environment", nargs="?", choices=("dev", "local-dev", "pre"))
    parser.add_argument("--output", type=Path, help="Save one validated render")
    args = parser.parse_args()
    require(not args.output or args.environment, "--output requires an environment")
    if args.action == "preflight":
        require(args.environment is not None, "preflight requires an environment")
        preflight(args.environment)
    else:
        for environment in [args.environment] if args.environment else ("dev", "local-dev", "pre"):
            rendered, index = render(environment)
            if args.output:
                args.output.write_text(rendered)
            print(f"PASS {environment}: {len(index)} resources, isolation and readiness contracts verified")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
