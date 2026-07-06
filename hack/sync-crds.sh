#!/usr/bin/env bash
# Refreshes container-crds/*.yaml directly from upstream sources. This replaces vendoring the
# files from giantswarm/apptestctl's pkg/crds/, mirroring the same upstreams that apptestctl's
# own hack/sync-crds.sh pulls from. Files are written verbatim, no transformations.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
OUT="container-crds"

# NOTE: The Giant Swarm App Platform CRDs (App, Chart, Catalog, AppCatalog, AppCatalogEntry from
# giantswarm/apiextensions-application) are deliberately NOT synced. ATS deploys charts directly
# with Helm (no App CR), so those CRDs are not needed on the test cluster.

# renovate: datasource=github-tags depName=cilium/cilium
CILIUM_REF="v1.19.5"
for crd in ciliumnetworkpolicies ciliumclusterwidenetworkpolicies; do
  curl -fsSL "https://raw.githubusercontent.com/cilium/cilium/${CILIUM_REF}/pkg/k8s/apis/cilium.io/client/crds/v2/${crd}.yaml" >"${OUT}/${crd}.yaml"
done

# renovate: datasource=github-tags depName=prometheus-operator/prometheus-operator
PROMETHEUS_OPERATOR_REF="v0.92.1"
for crd in servicemonitors podmonitors prometheuses prometheusrules; do
  curl -fsSL "https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/${PROMETHEUS_OPERATOR_REF}/example/prometheus-operator-crd/monitoring.coreos.com_${crd}.yaml" >"${OUT}/${crd}.yaml"
done

# VPA: FairwindsOps/charts has no git tags to pin via Renovate, so this is pinned to a commit SHA
# and refreshed manually. Re-check periodically:
# https://github.com/FairwindsOps/charts/commits/master/stable/vpa/crds/vpa-v1-crd.yaml
VPA_REF="98d448de4ef7507f6cd476f9d1218d0525254c4c"
curl -fsSL "https://raw.githubusercontent.com/FairwindsOps/charts/${VPA_REF}/stable/vpa/crds/vpa-v1-crd.yaml" >"${OUT}/verticalpodautoscalers.yaml"

# renovate: datasource=github-tags depName=kyverno/kyverno
KYVERNO_REF="v1.14.4"
curl -fsSL "https://raw.githubusercontent.com/kyverno/kyverno/refs/tags/${KYVERNO_REF}/config/crds/kyverno/kyverno.io_policyexceptions.yaml" >"${OUT}/policyexception.yaml"
curl -fsSL "https://raw.githubusercontent.com/kyverno/kyverno/refs/tags/${KYVERNO_REF}/config/crds/kyverno/kyverno.io_clusterpolicies.yaml" >"${OUT}/clusterpolicies.yaml"

# renovate: datasource=github-tags depName=giantswarm/prometheus-meta-operator
PROMETHEUS_META_OPERATOR_REF="v4.88.0"
curl -fsSL "https://raw.githubusercontent.com/giantswarm/prometheus-meta-operator/${PROMETHEUS_META_OPERATOR_REF}/config/crd/monitoring.giantswarm.io_remotewrites.yaml" >"${OUT}/remotewrites.yaml"

# renovate: datasource=github-tags depName=kedacore/keda
KEDA_REF="v2.20.1"
curl -fsSL "https://raw.githubusercontent.com/kedacore/keda/${KEDA_REF}/config/crd/bases/keda.sh_scaledobjects.yaml" >"${OUT}/scaledobjects.yaml"

# Gateway API + Gateway API Inference Extension.
# Private OCI registry -- Renovate can't reach it, bump manually. Keep aligned with
# giantswarm/gateway-api-bundle.
GATEWAY_API_CRDS_CHART_VER="1.8.1"
helm template "oci://gsoci.azurecr.io/charts/giantswarm/gateway-api-crds:${GATEWAY_API_CRDS_CHART_VER}" --set install.inferencepools=standard >"${OUT}/gateway-api.yaml"
