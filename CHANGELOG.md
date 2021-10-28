# Changelog

Based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
following [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/giantswarm/app-test-suite/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/giantswarm/app-test-suite/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/giantswarm/app-test-suite/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/giantswarm/app-test-suite/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/giantswarm/app-test-suite/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/giantswarm/app-test-suite/releases/tag/v0.1.1
