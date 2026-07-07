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
- [Testing GitOps bundle charts](#testing-gitops-bundle-charts)
  - [Selecting the engine](#selecting-the-engine)
  - [The engine value overlay](#the-engine-value-overlay)
  - [Bundle readiness](#bundle-readiness)
  - [What the tests see](#what-the-tests-see)
  - [Pinning the engine install manifest](#pinning-the-engine-install-manifest)
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

Depending on the test scenarios and cluster provider you use, you also need some of the following binaries
installed and available on your `PATH`:

- [helm](https://helm.sh/docs/intro/install/) (always required)
- [kubectl](https://kubernetes.io/docs/tasks/tools/) (always required)
- [kind](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) and a working
  [docker](https://docs.docker.com/get-docker/) daemon (only when using the built-in `kind` cluster provider)
- [go](https://go.dev/doc/install) (only when using the `gotest` test executor)

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
binary dependencies for you, but requires access to the docker socket. The interactive run command is:

```bash
docker run --rm -it \
  -e USE_UID="$(id -u)" \
  -e USE_GID="$(id -g)" \
  -e DOCKER_GID="$(getent group docker | cut -d: -f3)" \
  -v "$(pwd):/ats/workdir" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --network host \
  gsoci.azurecr.io/giantswarm/app-test-suite:<version>
```

To keep the examples below readable, define a shell alias once:

```bash
alias ats='docker run --rm -it -e USE_UID="$(id -u)" -e USE_GID="$(id -g)" -e DOCKER_GID="$(getent group docker | cut -d: -f3)" -v "$(pwd):/ats/workdir" -v /var/run/docker.sock:/var/run/docker.sock --network host gsoci.azurecr.io/giantswarm/app-test-suite:<version>'
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

`app-test-suite` automates preparation of a cluster used for testing in the following way:

- if you configured your run with `*-tests-cluster-type kind`, a cluster is created with `kind` tool
- `ats` connects to the target test cluster and applies the bundled CRDs with
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

## Testing GitOps bundle charts

A *bundle chart* is a Helm chart whose rendered output is GitOps custom resources (Flux
`HelmRelease`/`Kustomization`/`OCIRepository`, or Argo `Application`) instead of workloads. A GitOps
engine running in the cluster reconciles those resources and pulls in the actual apps.
[`agentic-platform`](https://github.com/giantswarm/agentic-platform) is the reference case: one chart
value switches its rendered output between Flux and Argo resources.

A plain `helm upgrade --install --wait` can't test such a chart honestly: there is no engine in the test
cluster to reconcile the emitted resources, and `--wait` only confirms that the resource objects exist,
not that the bundle they describe actually deployed. Tests would pass against a cluster where not a
single workload came up.

`ats` handles this by running each test scenario as a matrix of engine legs. For every selected engine it:

1. installs the engine on the test cluster (once per cluster; Flux and Argo can coexist),
2. deploys the chart into a per-engine namespace (`<deploy-namespace>-<engine>`), stacking the engine
   value overlay on your app config,
3. waits until the bundle is *ready* (see [Bundle readiness](#bundle-readiness)),
4. runs the test suite against the converged deployment,
5. tears the release down and waits for the emitted resources to drain before the next iteration.

This applies to all three scenarios. In the upgrade scenario both the stable release and the upgrade to
the version under test deploy under the live engine, so the stable-to-candidate resource-set transition
(renames, removals, orphaned resources) is exercised the way production hits it.

Both the Flux and Argo CD engines are supported.

### Selecting the engine

Engine selection is per test type, alongside the existing `--<test>-tests-cluster-*` options:

```bash
--<test>-tests-gitops-engines <value>   # smoke | functional | upgrade
```

- `auto` (default): render the chart with your app config and detect the engine from the emitted
  resource kinds. Flux kinds produce a Flux iteration, `Application` produces an Argo iteration, neither falls
  through to a plain Helm deploy.
- `helm`: force today's plain Helm deploy; skip detection and all engine machinery.
- `flux`, `argo`: explicit comma-separated list, one iteration per engine. Overrides detection.

Because `auto` is the default, every run renders the chart once to detect engines, and charts that
already emit GitOps resources start getting real readiness checks instead of a false-green
`helm --wait`. If that is not what you want for a given chart, set the option to `helm`.

### The engine value overlay

The value that selects the engine is chart-specific, so `ats` never guesses it. Instead you supply a
small values overlay per engine that is stacked on your normal app config (Helm merges them, last wins).
For `agentic-platform` the overlays look like this:

```yaml
# ci/gitops-values-flux.yaml
gitops:
  engine: flux
```

```yaml
# ci/gitops-values-argo.yaml
gitops:
  engine: argo
  argo:
    project: default
    server: https://kubernetes.default.svc
```

`ats` picks up `ci/gitops-values-<engine>.yaml` (relative to the working directory) automatically when it
exists, so a conforming repo needs no extra configuration. To point elsewhere, use:

```bash
--<test>-tests-gitops-values-<engine> path/to/overlay.yaml
```

A chart that renders the same resources regardless of engine (the [`flux-bundle-app`
example](examples/apps/flux-bundle-app) does this) needs no overlay at all.

`auto` detection renders with your app config only, not the engine overlay. A chart that emits its
GitOps resources only when the overlay sets the engine (rather than by default) is invisible to
`auto` and should be tested with an explicit `flux`/`argo` selection instead.

### Bundle readiness

A bundle can create more resources that create yet more resources (nested bundles), so "ready" is a
fixpoint, not a single check. `ats` polls until:

- every GitOps resource in the cluster reports ready (Flux: `HelmRelease`/`Kustomization`/`OCIRepository`
  `Ready`; Argo: every `Application` `Healthy` and `Synced`), **and**
- the set of resources is stable between two consecutive polls, meaning the deploy cascade stopped
  expanding.

The wait (and the teardown drain) are bounded by:

```bash
--<test>-tests-gitops-bundle-ready-timeout <duration>   # default 10m, e.g. 30s / 5m / 1h
```

On timeout, `ats` dumps the conditions of every resource that is not ready, so a chart-pull error or a
bad value reads as such instead of a mystery timeout.

Bundle children pull from wherever the chart points them. `ats` pulls anonymously; a chart whose children
live in a private registry needs its pull credentials injected via the `--app-tests-pre-hook`.

### What the tests see

On an engine iteration, the test suite runs against the per-engine namespace and receives the usual
`ATS_RELEASE_NAME` / `ATS_RELEASE_NAMESPACE` variables plus `ATS_EXTRA_GITOPS_ENGINE` (`flux` or `argo`),
so a test can assert engine-specific behaviour or wait on the reconciled workloads. See
[`examples/apps/flux-bundle-app/tests/ats`](examples/apps/flux-bundle-app/tests/ats) and
[`examples/apps/argo-bundle-app/tests/ats`](examples/apps/argo-bundle-app/tests/ats) for worked examples.

### Pinning the engine install manifest

The engine is installed from a manifest vendored in the `ats` container image: a trimmed Flux install with
the source, kustomize and helm controllers, or Argo CD Core (the application-controller, repo-server and
redis, without the API server, UI, dex or notifications). On an Argo iteration `ats` also switches on
applications-in-any-namespace so the bundle reconciles from its per-engine namespace, applies a permissive
`default` `AppProject`, and registers the Giant Swarm catalog as an OCI Helm repository. To use a different
build, or when running `ats` outside the container, point it at a path or URL:

```bash
--gitops-flux-install-manifest <path|url>
--gitops-argo-install-manifest <path|url>
```

The vendored manifests are refreshed by `hack/sync-gitops-manifests.sh`, which pins the Flux and Argo CD
versions.

## How to contribute

Check out the [contribution guidelines](docs/CONTRIBUTING.md).
