# Changelog

Based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), following
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Test executor auto-detection: with `--test-executor` left at its new default `auto`, the executor is chosen from the test directory — a `go.mod` selects `gotest`, a `pyproject.toml` selects `pytest`. Pass `pytest`/`gotest` explicitly to override (for example when the directory is empty or contains both markers). The bundled example app (`examples/apps/hello-world-app`) now ships a `tests/ats` Python suite and a `tests/ats-gotest` Go suite you can switch between with `--tests-dir`.
- `ats` can now be installed directly as a Python CLI tool with `uv tool install app-test-suite` (published to PyPI on every `v*` tag via OIDC trusted publishing). In this mode you provide the required binaries (`helm`, `kubectl`, and `kind`/`docker` or `go` as needed) yourself, without pulling the Docker image. See the README "With uv" section.
- OCI catalog URLs (`oci://...`) are now supported for `--upgrade-tests-app-catalog-url`; `helm pull oci://<url>/<chart>` is used automatically.
- `--upgrade-tests-app-version stable` (the new default) discovers the latest stable (non-prerelease) version to upgrade from, for both HTTP(S) chart repositories (via `index.yaml`) and OCI registries (via the registry tags API).
- Test suites receive `ATS_RELEASE_NAME` and `ATS_RELEASE_NAMESPACE` environment variables identifying the deployed Helm release and the namespace it was installed into.
- `helm` is now bundled in the ATS Docker image (renovate-pinned).
- `--app-tests-pre-hook`: executable run after chart install but before the label-filtered tests; `KUBECONFIG`, `ATS_*`, and `ATS_HOOK_STAGE=pre` are set in the environment.
- `--app-tests-post-hook`: executable run after tests complete (pass or no-match); same env contract as pre-hook with `ATS_HOOK_STAGE=post`.
- `docs/TEST_CONTRACT.md`: documents the phases, labels, environment-variable contract, and the relationship between scenario-level hooks and upgrade-stage hooks.
- Keep-going mode: all test steps run to completion even when earlier steps fail; errors are reported together at the end. Enabled by default; use `--no-keep-going` to stop on first failure. Requires `step-exec-lib >= 0.5.0`.
- Docker image is now published for `linux/amd64` and `linux/arm64`.

### Changed

- **BREAKING:** The per-executor `--app-tests-pytest-tests-dir` and `--app-tests-gotest-tests-dir` options were removed and merged into a single `--tests-dir` option (default `tests/ats`), used by whichever executor runs. In addition, `--test-executor` now defaults to `auto` (was `pytest`) and auto-detects the executor from that directory (see "Added"). **Migration:** replace `--app-tests-pytest-tests-dir` / `--app-tests-gotest-tests-dir` (and the matching `ATS_APP_TESTS_*` env vars / `app-tests-*-tests-dir:` config-file keys) with `--tests-dir` (`ATS_TESTS_DIR` env var / `tests-dir:` config-file key). If your test directory contains both a `go.mod` and a `pyproject.toml`, set `--test-executor` explicitly, since auto-detection is ambiguous there and falls back to `pytest`.
- **BREAKING:** The upgrade-stage hook (`--upgrade-tests-upgrade-hook`) now receives its context through environment variables instead of positional arguments, matching the `pre`/`post` scenario hooks. It gets `ATS_HOOK_STAGE` (`pre_upgrade` or `post_upgrade`), `ATS_RELEASE_NAME`, `ATS_RELEASE_NAMESPACE`, `ATS_UPGRADE_FROM_VERSION`, `ATS_UPGRADE_TO_VERSION`, and `KUBECONFIG`. Hook scripts reading positional `$1`..`$6` must read these variables instead.
- **BREAKING:** The `--upgrade-tests-app-version` magic value `latest` is renamed to `stable` and now resolves to the latest stable (non-prerelease) version instead of the latest version overall. The default changed from `latest` to `stable`. Pass an explicit version to pin one.
- **BREAKING:** Smoke, functional, and upgrade scenarios now deploy the chart under test directly with Helm (`helm upgrade --install`, `helm uninstall`) instead of creating an `App` CR. The upgrade scenario installs the stable chart, runs `helm upgrade` to the version under test, and uninstalls with Helm. Test suites that read the `App` CR must instead assert against the deployed workloads via the kube client, using `ATS_RELEASE_NAME` / `ATS_RELEASE_NAMESPACE`. Values files continue to be passed through `--app-tests-app-config-file` (forwarded to `helm --values`).
- **BREAKING:** During the pre-upgrade test phase, `ATS_CHART_PATH` is now the local path of the stable chart `.tgz` instead of a remote chartmuseum URL. Test suites that fetched it as a URL must read it as a filesystem path.
- **BREAKING:** `PytestExecutor` now uses `uv sync` / `uv run pytest` instead of `pipenv install --deploy` /
  `pipenv run pytest`. App test directories must provide `pyproject.toml` + `uv.lock` instead of `Pipfile` /
  `Pipfile.lock`. `pipenv` is no longer installed in the ATS Docker image.

  **Migration:** in your chart's `tests/ats/` directory run:

  ```bash
  uv init --no-workspace --no-readme
  uv add "pytest-helm-charts>=0.5"   # re-add your deps from Pipfile [packages]
  rm Pipfile Pipfile.lock
  ```

  Commit `pyproject.toml` and `uv.lock`. See [docs/pytest-test-pipeline.md](docs/pytest-test-pipeline.md)
  for full instructions.

- The bundled `container-crds/` are now synced directly from their upstream projects by
  `hack/sync-crds.sh` (run via `make update-crds`) instead of being vendored from `giantswarm/apptestctl`'s
  `pkg/crds/`. Every source is pinned to an explicit version; most pins are kept up to date automatically by
  Renovate. This drops the last dependency on `apptestctl`.

### Fixed

- Tests are now discovered relative to the executing directory (the current working directory) instead of relative to the location of the `--chart-file` archive, so the chart `.tgz` can live anywhere (e.g. a build output directory) without having to be moved next to your `tests/ats` directory ([#196](https://github.com/giantswarm/app-test-suite/issues/196)). The `.ats/main.yaml` config file is likewise now discovered relative to the working directory. For backward compatibility, if the test directory isn't found relative to the working directory but exists next to the chart file, the old location is used with a deprecation warning; when both a working-directory and a chart-file config exist, the chart-file one still takes precedence.
- `--app-tests-skip-app-delete` now prevents teardown of the deployed chart. It was previously ignored whenever the chart had been deployed (only honored when `--app-tests-skip-app-deploy` was also set).
- The `versions` command no longer fails with `apptestctl: command not found` after the `apptestctl` binary was dropped from the image.
- Errors raised while running a test scenario now preserve the original exception as the cause and no longer report every failure as an "Application deployment failed", so pre-hook, test, and post-hook failures are attributed correctly.

### Removed

- App CR deployment path, app-operator, chart-operator, and chartmuseum support removed.
- `apptestctl` binary dropped from the Docker image. CRDs are now bundled in `container-crds/` and applied via `kubectl apply --server-side` during cluster bootstrap.
- Giant Swarm App Platform CRDs (App, Chart, Catalog, AppCatalog, AppCatalogEntry) are no longer bundled in `container-crds/`. Since charts are deployed directly with Helm instead of via an `App` CR, the test cluster no longer needs them.
- **BREAKING:** `dats.sh` is no longer published as a release asset. Run the image directly: `docker run --rm -it -v "$(pwd):/ats/workdir" -v /var/run/docker.sock:/var/run/docker.sock --network host gsoci.azurecr.io/giantswarm/app-test-suite:<version>`. CI consumers must move to `architect/run-tests-with-ats` v10+, which runs the container directly instead of downloading `dats.sh`.

## [0.15.0] - 2026-04-02

### Changed

- Revert the breaking change from release 0.13.0 for test environments. This means that the project itself is
  kept on `uv`, but to avoid (for now) the cost of migrating all the test setups to `uv` as well, we keep them
  on `pipenv` for the time being.

## [0.14.0] - 2026-03-26

### Added

- Create `policy-exceptions` namespace before app deployment so charts with Kyverno PolicyException
  pre-install hooks can be installed successfully.

## [0.13.0] - 2026-03-19

### Added

- Add diagnostic output in case of failure

### Changed

- the project is now managed with [uv](https://docs.astral.sh/uv/)
- ~BREAKING CHANGE~: python tests ran by app-test-suite have to be migrated from being managed by pipenv to uv
  as well. No code changes in the tests themselves are needed, just the change of the project management tool.
  More information:
    - https://www.chris-wells.net/articles/2025/04/12/pipenv-to-uv/
    - https://github.com/yhino/pipenv-uv-migrate

## [0.12.0] - 2025-11-05

### Changed

- Update conftest to [v0.63.0](https://github.com/open-policy-agent/conftest/releases/tag/v0.63.0)
- Update kindest/node to v1.31.12

## [0.11.0] - 2025-09-15

### Changed

- update kubectl to v1.34.1
- update docker to 28.4.0
- update kind to v0.30.0
- update apptestctl to v0.24.0

## [0.10.6] - 2025-09-01

### Changed

- update apptestctl to v0.23.2.

## [0.10.5] - 2025-07-08

- Changed
    - update apptestctl to v0.23.1.

## [0.10.4] - 2025-07-07

- Changed
    - update apptestctl to v0.23.0.

## [0.10.3] - 2025-03-20

- Update Docker to v28.0.1
- Update KIND to v0.27.0
- Update kubectl to v1.32.3
- Update conftest to v0.58.0
- Go dependency updates

## [0.10.2] - 2024-10-31

- update `pytest-helm-charts` to v1.3.2

## [0.10.1] - 2024-10-29

- Changed
    - update apptestctl to v0.22.1.
    - update dats.sh to v0.10.1.
    - update kindest/node to v1.29.2.

## [0.10.0] - 2024-10-24

- Changed
    - update python to 3.12
    - update apptestctl to v0.22.0 to add Kyverno ClusterPolicy CRD.

## [0.8.1] - 2024-10-09

- Changed
    - chore(deps): update dependency architect to v5.9.0 (#372)
    - chore(deps): update dependency codecov to v4.2.0 (#370)
    - chore(deps): update dependency architect to v5.10.0 (#373)
    - chore(deps): update dependency go to v1.23.2 (#371)
    - chore(deps): update dependency moby/moby to v27.3.1 (#369)
    - Dockerfile: Improve downloads. (#374)

## [0.8.0] - 2024-09-20

- Changed
    - Update `apptestctl` to 0.21.0 to add PrometheusRules CRD.

## [0.7.0] - 2024-09-03

- Changed
    - Update `apptestctl` to 0.20.0 to add Prometheuses and RemoteWrites CRDs.

## [0.6.1] - 2024-06-06

- Go version changed to 1.22.4

## [0.6.0] - 2024-05-15

- Changed
    - Update `apptestctl` to 0.19.0 to update all CRDs.

## [0.5.1] - 2024-05-08

- Changed
    - Update `apptestctl` to 0.18.1 for PolicyException CRD promotion to v2beta1.

## [0.5.0] - 2023-10-10

- Changed
    - Update `apptestctl` to 0.18.0 for VPA and PolicyException CRDs.
    - Update dependencies.

## [0.4.1] - 2023-06-12

- No changes in this release. This release fixes missing version updates forgotten in 0.4.0

## [0.4.0] - 2023-06-12

- Changed
    - Update `apptestctl` to 0.17.0 for ServiceMonitor and PodMonitor CRD

## [0.3.0] - 2023-05-15

- Changed
    - Update `apptestctl` to 0.16.0 for support of kubernetes 1.25
    - Install the App CR into the target namespace. This is required because newer app-operators contain a
      security check to prevent installing outside of `giantswarm`, the org namespace or the same namespace as
      the App CR is located in. This security check is only present for App CRs that specify
      `inCluster: true`.
    - Always ensure the App CR target namespace before creating the App CR
    - Upgrade the python version in the container image to 3.9.16

## [0.2.9] - 2022-10-20

- Added
    - Add `--kind-cluster-image` flag to configure the image used to create kind clusters, defaults to
      `kindest/node:v1.24.6` because that is the last version that supports PSPs that we still use in some
      places

## [0.2.7] - 2022-10-19

- Changed
    - Bump `pytest-helm-charts` to `1.0.2` to fix `KUBECONFIG` path passing to `pytest-helm-charts`

## [0.2.6] - 2022-10-10

- Changed
    - Bump `pytest-helm-charts` to `1.0.1`

## [0.2.5] - 2022-07-29

- Added
    - Add `--app-tests-skip-app-delete` flag to allow skipping App CR and ConfigMap deletion after tests.

## [0.2.4] - 2022-06-16

- Added
    - Display logs for go test commands to make it easier to debug failing tests

## [0.2.3] - 2022-01-04

- Added
    - Add `--kind-cluster-image-override` flag make it possible to augment an existing kind config file to
      override the used kind node container image.
- Changed
    - dependency updates in the Dockerfile
        - apptestctl v0.14.1
        - kubectl v1.23.6
        - docker 20.10.15
        - kind 0.12.0 (the default image is now kubernetes 1.23)
        - golang 1.18.2
        - pipenv 2022.5.2

## [0.2.3-beta.1] - 2022-01-04

- Added
    - Test executors can now get extra info about the test run. Currently, used to provide info about upgrade
      test execution stage.

## [0.2.2] - 2021-11-17

- Fixed
    - try to better handle `index.yaml` Helm repo files, where incorrect subset of UTF-8 is used
    - use better library for parsing and sorting semvers of apps in the catalog

## [0.2.1] - 2021-10-28

- Changed
    - App Platform is now initialized only once per cluster
    - test scenarios use now Catalog CR instead of deprecated AppCatalog CR

- Fixed
    - correctly handle upgrade test scenarios where only 1 out of (stable, under-test) app versions was using
      a config file
    - upgrade `step-exec-lib` to 0.1.5 to fix go test handling

## [0.2.0] - 2021-10-21

- Added
    - New test type - upgrade test
    - New test executor - go test
    - Upgrade tests can now save YAML metadata file for the Giant Swarm App Platform (off by default)

- Changed
    - Changed interface for the `AppRepository` class
    - Update apptestctl to v0.12.0.
    - Update step-exec-lib to v0.1.4
    - Update python to 3.9
        - Please note: this includes update of the python packed inside the docker image. If you use `dats.sh`
          to run your tests, your projects must require and run on python 3.9 as well. Check and update your
          `Pipfile`!
    - Updated binaries used in the `dats.sh` docker image
        - kind to 0.11.1
        - docker to 20.10.9
        - kubectl to 1.21.2

- Fixed
    - [pytest executor] If no tests match the scenario running, `ats` was returning non-successful exit code
      itself. This is now fixed and such case (no tests matching a scenario) is considered a success and 0 is
      returned as exit code.

## [0.1.4] - 2021-09-17

- Changed
    - Fix how app test values are supplied to pytest-helm-charts

## [0.1.3] - 2021-09-16

- Changed
    - Bump container versions
        - python to 3.8.12
        - conftest to 0.27.0
        - alpine to 3.14.2

## [0.1.2] - 2021-08-18

- Added
    - new test type - upgrade test

- Changed
    - changed interface for the `AppRepository` class

## [0.1.1] - 2021-06-28

- Added
    - initial release

[Unreleased]: https://github.com/giantswarm/app-test-suite/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/giantswarm/app-test-suite/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/giantswarm/app-test-suite/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/giantswarm/app-test-suite/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/giantswarm/app-test-suite/compare/v0.10.6...v0.11.0
[0.10.6]: https://github.com/giantswarm/app-test-suite/compare/v0.10.5...v0.10.6
[0.10.5]: https://github.com/giantswarm/app-test-suite/compare/v0.10.4...v0.10.5
[0.10.4]: https://github.com/giantswarm/app-test-suite/compare/v0.10.3...v0.10.4
[0.10.3]: https://github.com/giantswarm/app-test-suite/compare/v0.10.2...v0.10.3
[0.10.2]: https://github.com/giantswarm/app-test-suite/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/giantswarm/app-test-suite/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/giantswarm/app-test-suite/compare/v0.8.1...v0.10.0
[0.8.1]: https://github.com/giantswarm/app-test-suite/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/giantswarm/app-test-suite/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/giantswarm/app-test-suite/compare/v0.6.1...v0.7.0
[0.6.1]: https://github.com/giantswarm/app-test-suite/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/giantswarm/app-test-suite/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/giantswarm/app-test-suite/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/giantswarm/app-test-suite/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/giantswarm/app-test-suite/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/giantswarm/app-test-suite/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/giantswarm/app-test-suite/compare/v0.2.9...v0.3.0
[0.2.9]: https://github.com/giantswarm/app-test-suite/compare/v0.2.6...v0.2.9
[0.2.6]: https://github.com/giantswarm/app-test-suite/compare/v0.2.4...v0.2.6
[0.2.4]: https://github.com/giantswarm/app-test-suite/compare/v0.2.0...v0.2.4
[0.2.0]: https://github.com/giantswarm/app-test-suite/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/giantswarm/app-test-suite/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/giantswarm/app-test-suite/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/giantswarm/app-test-suite/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/giantswarm/app-test-suite/releases/tag/v0.1.1
