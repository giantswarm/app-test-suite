# container-crds

CRD manifests applied to the test cluster during bootstrap via
`kubectl apply --server-side -f /etc/ats/crds` (see
`app_test_suite/steps/scenarios/simple.py:_ensure_cluster_prerequisites`). The
Dockerfile copies this directory to `/etc/ats/crds/`.

`--server-side` is required: several of these CRDs (e.g. `clusterpolicies.yaml`,
`prometheuses.yaml`) exceed the 256 KiB limit of the client-side
`last-applied-configuration` annotation.

## Provenance

These manifests are downloaded verbatim, straight from their upstream projects (App platform,
Cilium, Prometheus Operator, VPA, Kyverno, Gateway API + inference extension, KEDA), by
`hack/sync-crds.sh`. Version pins live in variables at the top of that script.

Most pins are tracked by Renovate via inline `# renovate:` comments in the script and get bumped
automatically as PRs. Two are pinned manually and need periodic manual bumps:

- `verticalpodautoscalers.yaml` (FairwindsOps/charts) — that repo has no git tags, so there's
  nothing for Renovate to track; pinned to a commit SHA instead.
- `gateway-api.yaml` — pulled via `helm template` from a private OCI registry Renovate can't reach.

## Refreshing

```bash
make update-crds
```

Review the diff before committing.
