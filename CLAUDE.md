# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**app-test-suite (ATS)** is a Python CLI tool for testing Helm chart apps on the Giant Swarm App Platform. It runs test suites (pytest or Go tests) against a Kubernetes cluster you provide (via a kubeconfig); it does not create or destroy clusters. It deploys the chart under test with Helm and runs the tests against it. It runs inside a Docker container that bundles kubectl, helm, and Go.

## Commands

### Running Tests
```bash
make test                    # Run unit tests locally with uv
make docker-test             # Run tests in Docker (builds images first)
make docker-test-ci          # Run tests in Docker with coverage XML output

# Run a single test file
uv run python -m pytest tests/test_repositories.py --log-cli-level info

# Run a single test
uv run python -m pytest tests/test_repositories.py::test_name --log-cli-level info
```

### Building
```bash
make docker-build            # Build production Docker image
make docker-build-test       # Build test runner Docker image
```

### Linting & Formatting
```bash
ruff check --fix             # Lint and auto-fix
ruff format                  # Format code
pre-commit run --all-files   # Run all pre-commit hooks (ruff, mypy, shell-lint, markdownlint)
```

### Release
```bash
make release TAG=v0.x.x      # Full release: version bump, test, build, tag, commit
```

## Architecture

### Execution Pipeline

The app uses `step-exec-lib` to define a pipeline of `BuildStep`s organized into `BuildStepsFilteringPipeline`s. The entry point (`app_test_suite/__main__.py`) selects a pipeline based on `--test-executor` (pytest or gotest). That option defaults to `auto`, in which case the executor is auto-detected from the `--tests-dir` directory (a `go.mod` → gotest, a `pyproject.toml` → pytest; `pytest` is the fallback). It parses config from CLI args / env vars (prefix `ATS_`) / config file (`.ats/main.yaml`), and runs it via `Runner`.

### Test Scenarios

Three scenario types, executed sequentially within a pipeline:
- **Smoke** — fast, fail-fast sanity checks
- **Functional** — full feature tests (run after smoke passes)
- **Upgrade** — tests the app upgrade path (requires `--upgrade-tests-app-*` options)

Scenarios are in `app_test_suite/steps/scenarios/`. Each scenario is a `BuildStep` that connects to the provided cluster, bootstraps the required dependency CRDs on it, deploys the chart with Helm, runs tests, and uninstalls the release.

### Cluster access

ATS does not manage cluster lifecycle. The user provides a kubeconfig for an existing cluster with `--cluster-kubeconfig` (plus optional `--cluster-type` / `--cluster-version` free-text labels). `ClusterManager` in `cluster_manager.py` validates the kubeconfig and hands all scenarios a single shared `ClusterInfo`; the required dependency CRDs are bootstrapped once per run.

### Test Executors

In `app_test_suite/steps/executors/`:
- `pytest.py` — wraps pytest with `pytest-helm-charts` for Helm chart testing
- `gotest.py` — wraps `go test` for Go-based test suites

Each executor defines its own `BuildStepsFilteringPipeline` containing the scenario steps.

### Configuration

Three-level config precedence (highest wins first):
1. CLI arguments
2. Environment variables (`ATS_` prefix)
3. Config file (`.ats/main.yaml` relative to chart or CWD)

## Testing dev builds via architect-orb

ATS is invoked in CI via the `architect/run-tests-with-ats` job from `giantswarm/architect-orb`. To test a dev build of ATS end-to-end:

1. **Enable dev image push in ATS CI.** By default, `.circleci/config.yml` has `push-dev` set to `false` in the `registries-data` field of `push-to-registries`, so branch builds are not pushed. Temporarily change the last field from `false` to `true`:
   ```
   registries-data: |-
     public gsoci.azurecr.io ACR_GSOCI_USERNAME ACR_GSOCI_PASSWORD true
   ```
   Push this change to the ATS branch. The CI will then push a dev image.

2. **Find the dev image tag.** The tag is determined by `architect project version` and follows the format `<version>-<full-commit-sha>` (no `v` prefix), e.g. `0.12.0-276b493ab6840a31c92d4fabd177d0b4d689afed`. Check the CircleCI `push-to-registries` job output for the exact tag pushed. You can also verify with `crane ls gsoci.azurecr.io/giantswarm/app-test-suite`.

3. **Create a branch in `giantswarm/architect-orb`** and update `src/jobs/run-tests-with-ats.yaml`:
   - `app-test-suite_container_tag` default → set to the dev image tag from step 2

4. **Wait for the architect-orb `publish-branch` CI job** to publish the dev orb. It publishes under two tags: `dev:<commit-sha>` and `dev:alpha`. The exact tags are printed in the last step of the job output.

5. **In the consuming repo** (e.g. `important-service`), temporarily change `.circleci/config.yml` to use the dev orb:
   ```yaml
   orbs:
     architect: giantswarm/architect@dev:alpha
   ```

6. Alternatively, override the ATS image tag directly in the consuming repo without changing the orb version:
   ```yaml
   - architect/run-tests-with-ats:
       app-test-suite_container_tag: "<dev-image-tag>"
   ```

**Remember to revert** the `push-dev: true` change in ATS and close the architect-orb test branch after validation.

## Key Conventions

- **Python >=3.12**, managed with `uv` (not pip/pipenv — docs/CONTRIBUTING.md is outdated on this)
- **Line length**: 120 characters (ruff and flake8)
- **Type checking**: mypy with `disallow_untyped_defs = True`
- **Pre-commit hooks** are centrally maintained at `github.com/giantswarm/github`
- **Makefile**: `Makefile` is auto-generated by devctl (do not edit); project-specific targets are in `Makefile.ats.mk`
- **Dockerfile** uses multi-stage builds; binary versions (kubectl, helm, Go) are pinned as build args. CRDs are vendored in `container-crds/` (see its README) and copied to `/etc/ats/crds/`
- **CHANGELOG.md**: update when making user-visible changes
- Follow Giant Swarm coding standards from `github.com/giantswarm/fmt`
