#!/usr/bin/env bash
# Refreshes container-gitops/*.yaml, the GitOps engine install manifests applied to the test
# cluster when a bundle chart needs an engine (see app_test_suite/gitops.py). Files are
# generated from pinned upstream releases; the Dockerfile copies the directory to
# /etc/ats/gitops/.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
OUT="container-gitops"
mkdir -p "${OUT}"

# renovate: datasource=github-releases depName=fluxcd/flux2
FLUX_VER="v2.9.0"

# The manifest is trimmed to the controllers a bundle chart needs (source, kustomize, helm);
# notification-controller and the image-automation controllers are deliberately excluded.
ARCH="$(uname -m)"
case "${ARCH}" in
x86_64) ARCH="amd64" ;;
aarch64) ARCH="arm64" ;;
esac
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
curl -fsSL "https://github.com/fluxcd/flux2/releases/download/${FLUX_VER}/flux_${FLUX_VER#v}_linux_${ARCH}.tar.gz" |
  tar -xz -C "${TMP_DIR}" flux
"${TMP_DIR}/flux" install --export \
  --components=source-controller,kustomize-controller,helm-controller >"${OUT}/flux.yaml"

# renovate: datasource=github-releases depName=argoproj/argo-cd
ARGO_VER="v3.4.4"

# Argo CD Core (core-install.yaml): the application-controller, repo-server and redis needed to
# reconcile Applications, without the API server, UI, dex or notifications controller. The upstream
# manifest carries no namespace and its ClusterRoleBinding subjects hardcode 'argocd', so it must
# land in that namespace; kustomize stamps the namespace on the namespaced resources and adds the
# Namespace object, making the result self-contained for a plain 'kubectl apply -f'.
ARGO_BUILD="${TMP_DIR}/argo"
mkdir -p "${ARGO_BUILD}"
curl -fsSL "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGO_VER}/manifests/core-install.yaml" \
  -o "${ARGO_BUILD}/core-install.yaml"
cat >"${ARGO_BUILD}/namespace.yaml" <<'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: argocd
EOF
cat >"${ARGO_BUILD}/kustomization.yaml" <<'EOF'
namespace: argocd
resources:
  - namespace.yaml
  - core-install.yaml
EOF
kubectl kustomize "${ARGO_BUILD}" >"${OUT}/argo.yaml"
