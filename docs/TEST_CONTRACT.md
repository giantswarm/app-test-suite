# ATS Test Contract

This document defines the phases, labels, environment variables, and hook contract that test code must follow to run under ATS (local kind loop) and, in the future, under ATF (E2E CAPI clusters).

## Scenario phases

Each ATS scenario runs in three phases:

```
pre-hook  →  label-filtered tests  →  post-hook
```

1. **pre-hook** (`--app-tests-pre-hook`): optional executable run after chart install but before tests. Use it to seed data, wait for external deps, or configure the release.
2. **label-filtered tests**: your pytest/go test suite, filtered to the scenario's label (see below).
3. **post-hook** (`--app-tests-post-hook`): optional executable run after tests complete (pass or "no tests matched"). Use it to export metrics, clean up external resources, etc.

The upgrade scenario wraps the full stable → upgrade flow with the scenario-level hooks and additionally fires two finer-grained hooks **around the `helm upgrade`** step:
- `--upgrade-tests-upgrade-hook <cmd> pre_upgrade ...` — after stable tests, before `helm upgrade`.
- `--upgrade-tests-upgrade-hook <cmd> post_upgrade ...` — after `helm upgrade`, before post-upgrade tests.

## Test labels

| Label | Pytest marker | Go build tag | When to use |
|---|---|---|---|
| `smoke` | `@pytest.mark.smoke` | `//go:build smoke` | Fast, fail-fast sanity checks. Run first. |
| `functional` | `@pytest.mark.functional` | `//go:build functional` | Full feature tests. Run after smoke. |
| `integration` | `@pytest.mark.integration` | `//go:build integration` | Tests exercising the app from outside (HTTP, gRPC, queue). |
| `upgrade` | `@pytest.mark.upgrade` | `//go:build upgrade` | Tests that run during the upgrade scenario (pre and post). |

A single test can carry multiple markers. ATS runs one scenario per label; each scenario selects only its own label.

Exit code 5 from pytest ("no tests matched the marker") is treated as success. Go's "build constraints exclude all Go files" is also treated as success. It is safe to have a test suite with no `integration`-tagged tests.

## Environment variables

ATS sets these variables for both test code and hooks:

| Variable | Value |
|---|---|
| `KUBECONFIG` | Absolute path to the cluster kubeconfig. |
| `ATS_CHART_PATH` | Path to the chart `.tgz` under test. |
| `ATS_CHART_VERSION` | Version string from `Chart.yaml`. |
| `ATS_CLUSTER_TYPE` | Cluster type (`kind`, `external`, …). |
| `ATS_CLUSTER_VERSION` | Kubernetes server version. |
| `ATS_TEST_TYPE` | Active label (`smoke`, `functional`, `integration`, `upgrade`). |
| `ATS_TEST_DIR` | Directory where the test source lives. |
| `ATS_APP_RELEASE_NAME` | Helm release name (set when a release was deployed). |
| `ATS_DEPLOY_NAMESPACE` | Kubernetes namespace the release was deployed into. |
| `ATS_APP_CONFIG_FILE_PATH` | Values file path (set when `--app-tests-app-config-file` is provided). |

Hooks additionally receive:

| Variable | Value |
|---|---|
| `ATS_HOOK_STAGE` | `pre` or `post`. |

The upgrade-stage hook receives context via **positional arguments** (not env vars):
`<cmd> <stage_name> <app_name> <from_version> <to_version> <kube_config_path> <deploy_namespace>`
where `stage_name` is `pre_upgrade` or `post_upgrade`.

## pytest marker registration

Register all markers in your `pyproject.toml` to avoid `PytestUnknownMarkWarning`:

```toml
[tool.pytest.ini_options]
markers = [
    "smoke: fast sanity checks run first",
    "functional: full feature tests",
    "integration: tests exercising the app from outside the cluster",
    "upgrade: run during upgrade scenario (before and after helm upgrade)",
]
```

## Go build tag convention

Gate each test file on exactly one label:

```go
//go:build smoke
// +build smoke
```

The `// +build` line is kept for Go < 1.17 compatibility.

## ATS vs ATF

| Dimension | ATS (this tool) | ATF |
|---|---|---|
| Cluster | Local kind, spun up per run | Real CAPI workload cluster |
| Trigger | Developer laptop / PR | Nightly / post-release |
| Deploy | `ct install` (Phase 1) / `helm upgrade` (upgrade) | HelmRelease |
| Labels used today | smoke, functional, integration, upgrade | smoke, functional (no label system yet) |

The labels and env-var contract are intentionally identical so the same test code runs in both environments. ATF label support (Ginkgo `Label(...)` annotations) is tracked separately.
