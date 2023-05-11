# Changelog

Based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
following [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Changed
  - Update `apptestctl` to 0.16.0 for support of kubernetes 1.25
  - Install the App CR into the target namespace. This is required because newer app-operators contain a security check to prevent installing outside of `giantswarm`, the org namespace or the same namespace as the App CR is located in. This security check is only present for App CRs that specify `inCluster: true`.
  - Always ensure the App CR target namespace before creating the App CR
  - Upgrade the python version in the container image to 3.9.16

## [0.2.9] - 2022-10-20

- Added
  - Add `--kind-cluster-image` flag to configure the image used to create kind clusters, defaults to `kindest/node:v1.24.6` because that is the last version that supports PSPs that we still use in some places

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
  - Add `--kind-cluster-image-override` flag make it possible to augment an existing kind config
    file to override the used kind node container image.
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
  - Test executors can now get extra info about the test run. Currently, used to provide info about
    upgrade test execution stage.

## [0.2.2] - 2021-11-17

- Fixed
  - try to better handle `index.yaml` Helm repo files, where incorrect subset of UTF-8 is used
  - use better library for parsing and sorting semvers of apps in the catalog

## [0.2.1] - 2021-10-28

- Changed
  - App Platform is now initialized only once per cluster
  - test scenarios use now Catalog CR instead of deprecated AppCatalog CR

- Fixed
  - correctly handle upgrade test scenarios where only 1 out of (stable, under-test) app versions was
    using a config file
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
    - Please note: this includes update of the python packed inside the docker image. If you use
      `dats.sh` to run your tests, your projects must require and run on python 3.9 as well.
      Check and update your `Pipfile`!
  - Updated binaries used in the `dats.sh` docker image
    - kind to 0.11.1
    - docker to 20.10.9
    - kubectl to 1.21.2

- Fixed
  - [pytest executor] If no tests match the scenario running, `ats` was returning non-successful
    exit code itself. This is now fixed and such case (no tests matching a scenario) is considered
    a success and 0 is returned as exit code.

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

[Unreleased]: https://github.com/giantswarm/app-test-suite/compare/v0.2.9...HEAD
[0.2.9]: https://github.com/giantswarm/app-test-suite/compare/v0.2.6...v0.2.9
[0.2.6]: https://github.com/giantswarm/app-test-suite/compare/v0.2.4...v0.2.6
[0.2.4]: https://github.com/giantswarm/app-test-suite/compare/v0.2.0...v0.2.4
[0.2.0]: https://github.com/giantswarm/app-test-suite/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/giantswarm/app-test-suite/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/giantswarm/app-test-suite/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/giantswarm/app-test-suite/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/giantswarm/app-test-suite/releases/tag/v0.1.1
