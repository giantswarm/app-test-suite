# Changelog

Based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
following [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

-   Changed
    -   update apptestctl to v0.23.1.

## [0.10.4] - 2025-07-07

-   Changed
    -   update apptestctl to v0.23.0.

## [0.10.3] - 2025-03-20

- Update Docker to v28.0.1
- Update KIND to v0.27.0
- Update kubectl to v1.32.3
- Update conftest to v0.58.0
- Go dependency updates

## [0.10.2] - 2024-10-31

-   update `pytest-helm-charts` to v1.3.2

## [0.10.1] - 2024-10-29

-   Changed
    -   update apptestctl to v0.22.1.
    -   update dats.sh to v0.10.1.
    -   update kindest/node to v1.29.2.

## [0.10.0] - 2024-10-24

-   Changed
    -   update python to 3.12
    -   update apptestctl to v0.22.0 to add Kyverno ClusterPolicy CRD.

## [0.8.1] - 2024-10-09

-   Changed
    -   chore(deps): update dependency architect to v5.9.0 (#372)
    -   chore(deps): update dependency codecov to v4.2.0 (#370)
    -   chore(deps): update dependency architect to v5.10.0 (#373)
    -   chore(deps): update dependency go to v1.23.2 (#371)
    -   chore(deps): update dependency moby/moby to v27.3.1 (#369)
    -   Dockerfile: Improve downloads. (#374)

## [0.8.0] - 2024-09-20

-   Changed
    -   Update `apptestctl` to 0.21.0 to add PrometheusRules CRD.

## [0.7.0] - 2024-09-03

-   Changed
    -   Update `apptestctl` to 0.20.0 to add Prometheuses and RemoteWrites CRDs.

## [0.6.1] - 2024-06-06

-   Go version changed to 1.22.4

## [0.6.0] - 2024-05-15

-   Changed
    -   Update `apptestctl` to 0.19.0 to update all CRDs.

## [0.5.1] - 2024-05-08

-   Changed
    -   Update `apptestctl` to 0.18.1 for PolicyException CRD promotion to v2beta1.

## [0.5.0] - 2023-10-10

-   Changed
    -   Update `apptestctl` to 0.18.0 for VPA and PolicyException CRDs.
    -   Update dependencies.

## [0.4.1] - 2023-06-12

-   No changes in this release. This release fixes missing version updates forgotten in 0.4.0

## [0.4.0] - 2023-06-12

-   Changed
    -   Update `apptestctl` to 0.17.0 for ServiceMonitor and PodMonitor CRD

## [0.3.0] - 2023-05-15

-   Changed
    -   Update `apptestctl` to 0.16.0 for support of kubernetes 1.25
    -   Install the App CR into the target namespace. This is required because newer app-operators
        contain a security check to prevent installing outside of `giantswarm`, the org namespace
        or the same namespace as the App CR is located in. This security check is only present for
        App CRs that specify `inCluster: true`.
    -   Always ensure the App CR target namespace before creating the App CR
    -   Upgrade the python version in the container image to 3.9.16

## [0.2.9] - 2022-10-20

-   Added
    -   Add `--kind-cluster-image` flag to configure the image used to create kind clusters, defaults
        to `kindest/node:v1.24.6` because that is the last version that supports PSPs that we still use in some places

## [0.2.7] - 2022-10-19

-   Changed
    -   Bump `pytest-helm-charts` to `1.0.2` to fix `KUBECONFIG` path passing to `pytest-helm-charts`

## [0.2.6] - 2022-10-10

-   Changed
    -   Bump `pytest-helm-charts` to `1.0.1`

## [0.2.5] - 2022-07-29

-   Added
    -   Add `--app-tests-skip-app-delete` flag to allow skipping App CR and ConfigMap deletion after tests.

## [0.2.4] - 2022-06-16

-   Added
    -   Display logs for go test commands to make it easier to debug failing tests

## [0.2.3] - 2022-01-04

-   Added
    -   Add `--kind-cluster-image-override` flag make it possible to augment an existing kind config
        file to override the used kind node container image.
-   Changed
    -   dependency updates in the Dockerfile
        -   apptestctl v0.14.1
        -   kubectl v1.23.6
        -   docker 20.10.15
        -   kind 0.12.0 (the default image is now kubernetes 1.23)
        -   golang 1.18.2
        -   pipenv 2022.5.2

## [0.2.3-beta.1] - 2022-01-04

-   Added
    -   Test executors can now get extra info about the test run. Currently, used to provide info about
        upgrade test execution stage.

## [0.2.2] - 2021-11-17

-   Fixed
    -   try to better handle `index.yaml` Helm repo files, where incorrect subset of UTF-8 is used
    -   use better library for parsing and sorting semvers of apps in the catalog

## [0.2.1] - 2021-10-28

-   Changed

    -   App Platform is now initialized only once per cluster
    -   test scenarios use now Catalog CR instead of deprecated AppCatalog CR

-   Fixed
    -   correctly handle upgrade test scenarios where only 1 out of (stable, under-test) app versions was
        using a config file
    -   upgrade `step-exec-lib` to 0.1.5 to fix go test handling

## [0.2.0] - 2021-10-21

-   Added

    -   New test type - upgrade test
    -   New test executor - go test
    -   Upgrade tests can now save YAML metadata file for the Giant Swarm App Platform (off by default)

-   Changed

    -   Changed interface for the `AppRepository` class
    -   Update apptestctl to v0.12.0.
    -   Update step-exec-lib to v0.1.4
    -   Update python to 3.9
        -   Please note: this includes update of the python packed inside the docker image. If you use
            `dats.sh` to run your tests, your projects must require and run on python 3.9 as well.
            Check and update your `Pipfile`!
    -   Updated binaries used in the `dats.sh` docker image
        -   kind to 0.11.1
        -   docker to 20.10.9
        -   kubectl to 1.21.2

-   Fixed
    -   [pytest executor] If no tests match the scenario running, `ats` was returning non-successful
        exit code itself. This is now fixed and such case (no tests matching a scenario) is considered
        a success and 0 is returned as exit code.

## [0.1.4] - 2021-09-17

-   Changed
    -   Fix how app test values are supplied to pytest-helm-charts

## [0.1.3] - 2021-09-16

-   Changed
    -   Bump container versions
        -   python to 3.8.12
        -   conftest to 0.27.0
        -   alpine to 3.14.2

## [0.1.2] - 2021-08-18

-   Added

    -   new test type - upgrade test

-   Changed
    -   changed interface for the `AppRepository` class

## [0.1.1] - 2021-06-28

-   Added
    -   initial release

[Unreleased]: https://github.com/giantswarm/app-test-suite/compare/v0.10.4...HEAD
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
