# container-crds

CRD manifests applied to the test cluster during bootstrap via
`kubectl apply --server-side -f /etc/ats/crds` (see
`app_test_suite/steps/scenarios/simple.py:_ensure_cluster_prerequisites`). The
Dockerfile copies this directory to `/etc/ats/crds/`.

`--server-side` is required: several of these CRDs (e.g. `clusterpolicies.yaml`,
`prometheuses.yaml`) exceed the 256 KiB limit of the client-side
`last-applied-configuration` annotation.

## Provenance

These manifests are vendored verbatim from
[`giantswarm/apptestctl`](https://github.com/giantswarm/apptestctl) `pkg/crds/`,
pinned to **v0.25.1**. apptestctl in turn syncs them from their upstream projects
(App platform, Cilium, Prometheus Operator, VPA, Kyverno, Gateway API + inference
extension, KEDA) via its own `hack/sync-crds.sh`.

## Refreshing

```bash
make update-crds                          # uses APPTESTCTL_CRDS_VER (default v0.25.1)
make update-crds APPTESTCTL_CRDS_VER=v0.26.0
```

After bumping, update the pinned version above and in `Makefile.ats.mk`
(`APPTESTCTL_CRDS_VER`), and review the diff: these are not tracked by Renovate,
so refreshing is a manual step.
