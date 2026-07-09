# app-test-suite

[![build](https://circleci.com/gh/giantswarm/app-test-suite.svg?style=svg)](https://circleci.com/gh/giantswarm/app-test-suite)
[![codecov](https://codecov.io/gh/giantswarm/app-test-suite/branch/master/graph/badge.svg)](https://codecov.io/gh/giantswarm/app-test-suite)
[![Apache License](https://img.shields.io/badge/license-apache-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

A tool to test apps (Helm Charts) for
[Giant Swarm App Platform](https://docs.giantswarm.io/app-platform/).

This tool is a development and CI/CD tool that allows you to test your chart after building:
    - run your tests of different kind using [`pytest`](https://docs.pytest.org/en/stable/) and
      [`pytest-helm-charts`](https://github.com/giantswarm/pytest-helm-charts)
    - define different test scenarios for your release

To build the Chart, please consider the companion [app-build-suite](https://github.com/giantswarm/app-build-suite) project.

---

## Index

- [How to use app-test-suite](#how-to-use-app-test-suite)
  - [Installation](#installation)
  - [Tutorial](#tutorial)
  - [Quick start](#quick-start)
  - [How does it work](#how-does-it-work)
    - [Bootstrapping](#bootstrapping)
    - [Test execution](#test-execution)
  - [Full usage help](#full-usage-help)
- [Tuning app-test-suite execution and running parts of the build process](#tuning-app-test-suite-execution-and-running-parts-of-the-build-process)
  - [Configuring app-test-suite](#configuring-app-test-suite)
- [Execution steps details and configuration](#execution-steps-details-and-configuration)
  - [Test executors](#test-executors)
  - [Test pipelines](#test-pipelines)
- [How to contribute](#how-to-contribute)

## How to use app-test-suite

### Installation

#### With uv

You can install `app-test-suite` as a command line tool invoked with the `ats` command. In this mode you're
responsible for installing all the binary dependencies that `ats` needs to work.

This mode doesn't need docker to run `ats` itself, so it's a good match for all the systems built with isolation
and sandboxing in mind, like CI/CD or AI agents running in isolated jails/sandboxes.

The main tool you need is [uv](https://github.com/astral-sh/uv). Please refer to the
[uv installation documentation](https://docs.astral.sh/uv/getting-started/installation/) for instructions on how
to install it.

Depending on the test scenarios you use, you also need some of the following binaries
installed and available on your `PATH`:

- [helm](https://helm.sh/docs/intro/install/) (always required)
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (always required)
- [go](https://go.dev/doc/install) (only when using the `gotest` test executor)

`ats` does not create or destroy clusters: you always provide it a `kubeconfig` for an existing cluster to
run the tests on (see [`--cluster-kubeconfig`](#quick-start)).

Then, to install `ats`, just run:

```bash
uv tool install app-test-suite
```

Check the installation:

```bash
ats --version
```

To upgrade:

```bash
uv tool upgrade app-test-suite
```

#### With docker

`ats` is also distributed as a docker image, so you can run it directly with `docker run`. This bundles all the
binary dependencies for you. The container needs network access to your test cluster's API server (here provided
with `--network host`) and reads the `kubeconfig` you mount into the working directory. The interactive run
command is:

```bash
docker run --rm -it \
  -e USE_UID="$(id -u)" \
  -e USE_GID="$(id -g)" \
  -v "$(pwd):/ats/workdir" \
  --network host \
  gsoci.azurecr.io/giantswarm/app-test-suite:<version>
```

To keep the examples below readable, define a shell alias once:

```bash
alias ats='docker run --rm -it -e USE_UID="$(id -u)" -e USE_GID="$(id -g)" -v "$(pwd):/ats/workdir" --network host gsoci.azurecr.io/giantswarm/app-test-suite:<version>'
```

Alternatively, you can just checkout this repository and build the docker image yourself by running:

```bash
make docker-build
```

### Tutorial

If you prefer to learn by example, building a simple project step-by-step, please start
with [tutorial](docs/tutorial.md).

### Quick start

`app-test-suite` provides App Platform bootstrapping and test scenarios for your Managed Apps charts.
Currently, it offers 3 test scenarios, which are executed one after the other unless [configured](#configuring-app-test-suite)
otherwise. Each test scenario ensures that the App Platform components are deployed to the cluster, then invokes
test logic, which for different scenarios works like below:

1. The `smoke` tests scenario: just run the test executor with `smoke` as a test type filter. Use this scenario
    and test type to run any tests that will allow you to fail fast and save time and resources on running more complex
    tests.
2. The `functional` tests scenario: just run the test executor with `functional` as a test type filter. As this is
    executed after the `smoke` scenario succeeds, you know that the basic stuff is ready and you can ensure your app
    under test is functioning properly.
3. The `upgrade` tests scenario requires additional configuration. It takes one version of your app and tests if
    it is safe to upgrade it to the version under test. As such it needs either `--upgrade-tests-app-catalog-url`
    and `--upgrade-tests-app-version` config options pair or a local chart file `--upgrade-tests-app-file`.
    The scenario executes the following steps:
   1. From-version app is deployed as configured using the `--upgrade-tests-app-*` options.
   2. Test executor is executed to run all the tests with `upgrade` annotation.
   3. Optional `pre-upgrade` hook configured with `--upgrade-tests-upgrade-hook` is executed as a system binary.
   4. App under test is upgraded to the `--chart-file` indicated chart version.
   5. Optional `post-upgrade` hook configured with `--upgrade-tests-upgrade-hook` is executed as a system binary.
   6. Test executor is executed again to run all the tests with `upgrade` annotation.

Running the docker image (via the `ats` alias) is the most straight forward way to run `app-test-suite`.
As an example, we have included a chart
in this repository in
[`examples/apps/hello-world-app`](examples/apps/hello-world-app). Its configuration file for
`ats` is in the [.ats/main.yaml](examples/apps/hello-world-app/.ats/main.yaml) file.
`ats` discovers tests and its `.ats/main.yaml` config relative to the directory you run it from (the working
directory), independently of where the `-c` chart archive lives. To test the chart using `ats` and the
provided config file, run it from the chart's directory:

```bash
cd examples/apps/hello-world-app
ats -c hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz
```

To run it, you need to have an existing Kubernetes cluster. The bundled `.ats/main.yaml` points `ats` at a
`kube.config` file in the working directory. If you have `kind`, you can create the cluster
and its config file like this:

```bash
kind create cluster
kind get kubeconfig > ./kube.config
```

### How does it work

Each run consist of two stages: bootstrapping and test execution.

#### Bootstrapping

`app-test-suite` automates preparation of the cluster used for testing in the following way:

- `ats` connects to the test cluster you provided with `--cluster-kubeconfig` and applies the bundled CRDs with
  `kubectl apply --server-side -f /etc/ats/crds` (the CRDs vendored in `container-crds/`; no operators are installed)
- `ats` deploys your chart under test directly with Helm (`helm upgrade --install`); your application defined in the
  chart is deployed to the test cluster (you can disable this with the `app-tests-skip-app-deploy` option; this might
  be needed if you need more control over your test, like setting up additional CRDs or installing additional apps).
  The deployed release name and namespace are exposed to your tests via the `ATS_RELEASE_NAME` and
  `ATS_RELEASE_NAMESPACE` environment variables.

After that, `ats` hands control over to your tests.

#### Test execution

After bootstrapping, `ats` starts executing test scenarios. Currently, we have 3 scenarios executed in this order:
`smoke`, `functional` and `upgrade`. To better depict what `ats` does and how it executes a test scenario, let's have a
look at what happens when you execute:

```bash
# run from the chart's directory (examples/apps/hello-world-app), where tests/ats lives
ats -c hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz \
  --skip-steps upgrade \
  --cluster-kubeconfig ./kube.config \
  --cluster-type kind \
  --cluster-version "1.19.0"
```

the following commands are executed underneath:

```bash
# here start smoke tests
kubectl --kubeconfig=kube.config apply --server-side -f /etc/ats/crds
uv sync
(
    # See: https://github.com/giantswarm/pytest-helm-charts/blob/master/CHANGELOG.md#071---20220803
    KUBECONFIG="/ats/workdir/kube.config"

    ATS_CLUSTER_TYPE="kind"
    ATS_CLUSTER_VERSION="1.19.0"

    ATS_TEST_TYPE="smoke"

    ATS_CHART_PATH="hello-world-app-0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db.tgz"
    ATS_CHART_VERSION="0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db"

    ATS_RELEASE_NAME="hello-world-app"
    ATS_RELEASE_NAMESPACE="default"

    uv run pytest --log-cli-level info --junitxml=test_results_smoke.xml
)

# and here start functional tests
kubectl --kubeconfig=kube.config apply --server-side -f /etc/ats/crds
uv sync

    # See: https://github.com/giantswarm/pytest-helm-charts/blob/master/CHANGELOG.md#071---20220803
    KUBECONFIG="/ats/workdir/kube.config"

    ATS_CLUSTER_TYPE="kind"
    ATS_CLUSTER_VERSION="1.19.0"

    ATS_TEST_TYPE="functional"

    ATS_CHART_PATH="hello-world-app-0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db.tgz"
    ATS_CHART_VERSION="0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db"

    ATS_RELEASE_NAME="hello-world-app"
    ATS_RELEASE_NAMESPACE="default"

    uv run pytest --log-cli-level info --junitxml=test_results_functional.xml
)
```

### Full usage help

To get an overview of available options, please run:

```bash
ats -h
```

To learn what they mean and how to use them, please follow to
[execution steps and their config options](#execution-steps-details-and-configuration).

## Tuning app-test-suite execution and running parts of the build process

This tool works by executing a series of so called `Build Steps`.
The important property in `app-test-suite` is that you can only execute a subset of all the build steps. This idea
should be useful for integrating `ats` with other workflows, like CI/CD systems or for running parts of the build
process on your local machine during development. You can either run only a selected set of steps using `--steps` option
or you can run all if them excluding some using `--skip-steps`. Check `ats -h` output for step names available
to `--steps` and `--skip-steps`
flags.

To skip or include multiple step names, separate them with space, like in this example:

```bash
ats -c examples/apps/hello-world-app/mychart-0.1.0.tgz --skip-steps test_unit test_performance
```

### Configuring app-test-suite

Every configuration option in `ats` can be configured in 3 ways. Starting from the highest to the lowest priority, these
are:

- command line arguments,
- environment variables,
- config file (`ats` tries first to load the config file from the chart's directory `.ats/main.yaml` file; if it doesn't
  exist, then it tries to load the default config file from the current working directory's
  `.ats/main.yaml`).

When you run `ats -h` it shows you command line options and the relevant environment variables names. Options for a
config file are the same as for command line, just with truncated leading `--`. You can check
[this example](examples/apps/hello-world-app/.ats/main.yaml).

The configuration is made this way, so you can put your defaults into the config file, yet override them with env
variables or command line when needed. This way you can easily override configs for stuff like CI/CD builds.

## Execution steps details and configuration

`ats` is prepared to work with multiple different test engines. Please check below for available
ones and steps they provide.

### Test executors

`app-test-suite` supports multiple test execution engines that can be used to run the same set of test scenarios.
Currently, the following are supported:

- `pytest` - run tests written in `python`; see [docs/pytest-test-pipeline.md](docs/pytest-test-pipeline.md).
- `gotest` - run tests with `go test`; see [docs/gotest-test-pipeline.md](docs/gotest-test-pipeline.md).

Both executors look for the test suite in the same directory, configured with a single `--tests-dir` option
(default `tests/ats`, resolved relative to the working directory). The executor is auto-detected from that
directory: a `go.mod` selects `gotest` and a `pyproject.toml` selects `pytest`. Set `--test-executor`
explicitly to override the detection (for example when the directory is empty or contains both markers).
The example app carries both suites in separate directories — `tests/ats` (pytest) and `tests/ats-gotest`
(gotest) — so you can switch between them with `--tests-dir`.

### Test pipelines

There are a few assumptions related to how testing invoked by `ats` works.

First, we assume that each test framework that you can use for developing tests for your app can label the tests and run
only the set of tests labelled. `ats` expects all tests to have at least one of the following labels: `smoke`
, `functional`. It uses the labels to run only certain tests, so `ats`
runs all `smoke` tests first, then all `functional` tests. As concrete example, this mechanism is implemented
as [marks in pytest](https://docs.pytest.org/en/stable/mark.html) or
[tags in go test](https://golang.org/pkg/go/build/#hdr-Build_Constraints).

The idea is that `ats` invokes first the testing framework with `smoke` filter, so that only smoke tests are invoked.
Smoke tests are expected to be very basic and short-lived, so they provide an immediate feedback if something is wrong
and there's no point in running more advanced (and time and resource consuming tests). Only if `smoke` tests are
OK, `functional` tests are invoked to check if the application works as expected. In the future, we want to
introduce `performance` tests for checking for expected performance results in a well-defined environment
and `compatibility` tests for checking strict compatibility of your app with a specific platform release.

All scenarios run against the single cluster you provide with `--cluster-kubeconfig`. Combined with the "fail
fast" ordering above (`smoke` before `functional` before `upgrade`), this lets you point `ats` at a cheap,
quick-to-provision cluster (for example a local `kind` cluster) during development and at a more
representative cluster in CI — the choice of cluster is entirely up to you, outside of `ats`.

## How to contribute

Check out the [contribution guidelines](docs/CONTRIBUTING.md).
