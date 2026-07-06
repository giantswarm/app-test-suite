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
- `pre_upgrade` (`ATS_HOOK_STAGE=pre_upgrade`): runs after stable tests, before `helm upgrade`.
- `post_upgrade` (`ATS_HOOK_STAGE=post_upgrade`): runs after `helm upgrade`, before post-upgrade tests.

Both stages run the executable given by `--upgrade-tests-upgrade-hook`.

## Test labels

| Label | Pytest marker | Go build tag | When to use |
|---|---|---|---|
| `smoke` | `@pytest.mark.smoke` | `//go:build smoke` | Fast, fail-fast sanity checks. Run first. |
| `functional` | `@pytest.mark.functional` | `//go:build functional` | Full feature tests. Run after smoke. |
| `upgrade` | `@pytest.mark.upgrade` | `//go:build upgrade` | Tests that run during the upgrade scenario (pre and post). |

A single test can carry multiple markers. ATS runs one scenario per label; each scenario selects only its own label.

Exit code 5 from pytest ("no tests matched the marker") is treated as success. Go's "build constraints exclude all Go files" is also treated as success.

## Environment variables

ATS sets these variables for both test code and hooks:

| Variable | Value |
|---|---|
| `KUBECONFIG` | Absolute path to the cluster kubeconfig. |
| `ATS_CHART_PATH` | Path to the chart `.tgz` under test. |
| `ATS_CHART_VERSION` | Version string from `Chart.yaml`. |
| `ATS_CLUSTER_TYPE` | Cluster type (`kind`, `external`, …). |
| `ATS_CLUSTER_VERSION` | Kubernetes server version. |
| `ATS_TEST_TYPE` | Active label (`smoke`, `functional`, `upgrade`). |
| `ATS_TEST_DIR` | Directory where the test source lives. |
| `ATS_RELEASE_NAME` | Helm release name (set when a release was deployed). |
| `ATS_RELEASE_NAMESPACE` | Kubernetes namespace the release was deployed into. |
| `ATS_APP_CONFIG_FILE_PATH` | Values file path (set when `--app-tests-app-config-file` is provided). |

Hooks additionally receive:

| Variable | Value |
|---|---|
| `ATS_HOOK_STAGE` | `pre` or `post`. |

The upgrade-stage hook receives context via environment variables, the same way the pre/post hooks do. In addition to the variables above (`ATS_HOOK_STAGE` is `pre_upgrade` or `post_upgrade`), it receives:

| Variable | Value |
|---|---|
| `ATS_UPGRADE_FROM_VERSION` | Chart version the release is upgraded from (the stable version). |
| `ATS_UPGRADE_TO_VERSION` | Chart version the release is upgraded to (the version under test). |

## pytest marker registration

Register all markers in your `pyproject.toml` to avoid `PytestUnknownMarkWarning`:

```toml
[tool.pytest.ini_options]
markers = [
    "smoke: fast sanity checks run first",
    "functional: full feature tests",
    "upgrade: run during upgrade scenario (before and after helm upgrade)",
]
```

## Go build tag convention

Gate each test file on exactly one label:

```go
//go:build smoke
```

## ATS vs ATF

| Dimension | ATS (this tool) | ATF |
|---|---|---|
| Cluster | Local kind, spun up per run | Real CAPI workload cluster |
| Trigger | Developer laptop / PR | Nightly / post-release |
| Deploy | `helm upgrade --install` | HelmRelease |
| Labels used today | smoke, functional, upgrade | smoke, functional (no label system yet) |

The labels and env-var contract are intentionally identical so the same test code runs in both environments. ATF label support (Ginkgo `Label(...)` annotations) is tracked separately.
