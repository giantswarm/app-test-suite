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
