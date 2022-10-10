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

`ats` is distributed as a docker image, so the easiest way to install and use it is to get our `dats.sh`
script from [releases](https://github.com/giantswarm/app-test-suite/releases). `dats.sh` is a wrapper script that
launches for you `ats` inside a docker container and provides all the necessary docker options required to make it work.

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

Executing `dats.sh` is the most straight forward way to run `app-test-suite`. As an example, we have included a chart
in this repository in
[`examples/apps/hello-world-app`](examples/apps/hello-world-app). Its configuration file for
`ats` is in the [.ats/main.yaml](examples/apps/hello-world-app/.ats/main.yaml) file.
To test the chart using `dats.sh`
and the provided config file, run:

```bash
dats.sh -c examples/apps/hello-world-app/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz
```

To run it, you need to have an existing Kubernetes cluster. `kube.config` file needed to authorize with it
needs to be saved in the root directory of this repository. If you have `kind`, you can create the cluster
and its config file like this:

```bash
kind create cluster
kind get kubeconfig > ./kube.config
```

### How does it work

Each run consist of two stages: bootstrapping and test execution.

#### Bootstrapping

`app-test-suite` automates preparation of a cluster used for testing in the following way:

- if you configured your run with `*-tests-cluster-type kind`, a cluster is created with `kind` tool
- `ats` connects to the target test cluster and runs [`apptestctl`](https://github.com/giantswarm/apptestctl) -
  an additional tool that deploys components of App Platform
  (`app-operator`, `chart-operator` and CRDs they use)
- `ats` deploys `chart-museum`: a simple helm chart registry that will be used to store your chart under test
- creates `Catalog` CR for the chart repository provided by `chart-museum`
- creates `App` CR for your chart: as a result, your application defined in the chart is already deployed to the test
  cluster (you can disable creating this app with `app-tests-skip-app-deploy` option; this might be needed if you
  need more control over your test, like: setup additional CRDs or install additional apps).

After that, `ats` hands control over to your tests.

#### Test execution

After bootstrapping, `ats` starts executing test scenarios. Currently, we have 3 scenarios executed in this order:
`smoke`, `functional` and `upgrade`. To better depict what `ats` does and how it executes a test scenario, let's have a
look at what happens when you execute:

```bash
dats.sh -c examples/apps/hello-world-app/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz \
  --functional-tests-cluster-type external \
  --smoke-tests-cluster-type external \
  --skip-steps upgrade \
  --external-cluster-kubeconfig-path ./kube.config \
  --external-cluster-type kind \
  --external-cluster-version "1.19.0"
```

the following commands are executed underneath:

```bash
# here start smoke tests
apptestctl bootstrap --kubeconfig-path=kube.config --wait
pipenv install --deploy
(
    # See: https://github.com/giantswarm/pytest-helm-charts/blob/master/CHANGELOG.md#071---20220803
    KUBECONFIG="/ats/workdir/kube.config"

    ATS_CLUSTER_TYPE="kind"
    ATS_CLUSTER_VERSION="1.19.0"

    ATS_TEST_TYPE="smoke"

    ATS_CHART_PATH="hello-world-app-0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db.tgz"
    ATS_CHART_VERSION="0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db"

    pipenv run pytest --log-cli-level info --junitxml=test_results_smoke.xml
)

# and here start functional tests
apptestctl bootstrap --kubeconfig-path=kube.config --wait
pipenv install --deploy

    # See: https://github.com/giantswarm/pytest-helm-charts/blob/master/CHANGELOG.md#071---20220803
    KUBECONFIG="/ats/workdir/kube.config"

    ATS_CLUSTER_TYPE="kind"
    ATS_CLUSTER_VERSION="1.19.0"

    ATS_TEST_TYPE="functional"

    ATS_CHART_PATH="hello-world-app-0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db.tgz"
    ATS_CHART_VERSION="0.1.8-1112d08fc7d610a61ace4233a4e8aecda54118db"

    pipenv run pytest --log-cli-level info --junitxml=test_results_functional.xml
)
```

### Full usage help

To get an overview of available options, please run:

```bash
dats.sh -h
```

To learn what they mean and how to use them, please follow to
[execution steps and their config options](#execution-steps-details-and-configuration).

## Tuning app-test-suite execution and running parts of the build process

This tool works by executing a series of so called `Build Steps`.
The important property in `app-test-suite` is that you can only execute a subset of all the build steps. This idea
should be useful for integrating `ats` with other workflows, like CI/CD systems or for running parts of the build
process on your local machine during development. You can either run only a selected set of steps using `--steps` option
or you can run all if them excluding some using `--skip-steps`. Check `dats.sh -h` output for step names available
to `--steps` and `--skip-steps`
flags.

To skip or include multiple step names, separate them with space, like in this example:

```bash
dats.sh -c examples/apps/hello-world-app/mychart-0.1.0.tgz --skip-steps test_unit test_performance
```

### Configuring app-test-suite

Every configuration option in `ats` can be configured in 3 ways. Starting from the highest to the lowest priority, these
are:

- command line arguments,
- environment variables,
- config file (`ats` tries first to load the config file from the chart's directory `.ats/main.yaml` file; if it doesn't
  exist, then it tries to load the default config file from the current working directory's
  `.ats/main.yaml`).

When you run `dats.sh -h` it shows you command line options and the relevant environment variables names. Options for a
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

- `pytest` - the first test executor, allows you to run any tests written in `python` and `pytest`.

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

Another important concept is that each type of tests can be run on a different type of Kubernetes cluster. That way, we
want to make a test flow that uses "fail fast" principle: if your tests are going to fail, make them fail as soon as
possible, without creating "heavy" clusters or running "heavy" tests. As an example, our default config should be
something like this:

1. Run `smoke` tests on `kind` cluster. Fail if any test fails.
2. Run `functional` tests on `kind` cluster. We might reuse the `kind` cluster from the step above. But we might also
   need a more powerful setup to be able to test all the `functional` scenarios, so we might request a real AWS cluster
   for that kind of tests. It's for the test developer to choose.

## How to contribute

Check out the [contribution guidelines](docs/CONTRIBUTING.md).
