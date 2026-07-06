# Pytest test pipeline

This testing pipeline is implemented using the well established [`pytest`](https://docs.pytest.org/en/stable/)
testing framework. It can be used for testing any apps, no matter if the application was originally written in python or
not. To make testing easier, we are also providing
[`pytest-helm-charts`](https://github.com/giantswarm/pytest-helm-charts) plugin, which makes writing tests for
kubernetes deployed apps easier. See [examples/apps/hello-world-app/tests/ats](examples/apps/hello-world-app/tests/ats)
for a complete usage example.

To make your tests automatically invocable from `ats`, you must adhere to the following rules:

- put all test code in the `tests/ats/` directory relative to where you run `ats` from (the working
  directory). This is decoupled from the `--chart-file` archive location, so the chart `.tgz` can live
  anywhere. Override the location with `--app-tests-pytest-tests-dir` (relative to the working directory,
  or an absolute path).
- manage dependencies with [`uv`](https://docs.astral.sh/uv/): the directory must contain a `pyproject.toml`
  and a committed `uv.lock`. `ats` runs `uv sync` before each test run and invokes tests with `uv run pytest`.

## Setting up a test directory

Install `uv` if you haven't already:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Create the project inside your chart's `tests/ats/` directory:

```bash
cd tests/ats
uv init --no-workspace --no-readme
uv add "pytest-helm-charts>=0.5"
```

This creates `pyproject.toml` and `uv.lock`. Commit both. The minimal `pyproject.toml` looks like:

```toml
[project]
name = "my-chart-tests"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pytest-helm-charts>=0.5",
]
```

To add more dependencies later: `uv add <package>`. To update the lock file: `uv lock --upgrade`.

### Running tests locally

`ats` (the docker image) handles `uv sync` for you inside the container. To run tests locally without the container,
activate the virtualenv that `uv sync` creates:

```bash
cd tests/ats
uv sync
uv run pytest -m smoke
```

Or just use any Python environment you manage yourself — `uv` is only required inside the `ats` container.

### Migrating from Pipfile

If your test directory has a `Pipfile` / `Pipfile.lock`:

```bash
cd tests/ats
uv init --no-workspace --no-readme
# re-add your dependencies from Pipfile [packages]
uv add "pytest-helm-charts>=0.5"
rm Pipfile Pipfile.lock
```

Commit `pyproject.toml` and `uv.lock`, remove `Pipfile` and `Pipfile.lock`.

The `pytest` pipeline invokes following series of steps:

1. TestInfoProvider: gathers some additional info required for running the tests.
2. PytestSmokeTestRunner: invokes `pytest` with `smoke` tag to run smoke tests only.
3. PytestFunctionalTestRunner: invokes `pytest` with `functional` tag to run functional tests only.
4. PytestUpgradeTestRunner: deploys your app as specified with `--upgrade-tests-app-catalog-url`
    and `--upgrade-tests-app-version` or directly local chart file `--upgrade-tests-app-file`. Then
    tests are executed on the stable app version using the `upgrade` type, a pre-upgrade hook is executed,
    your app is upgraded to the version under the test, post-upgrade hook is executed and then again test are invoked
    using `upgrade` test type.

## Configuring test scenarios

Each test type ("smoke", "functional") can have its own type and configuration of a Kubernetes cluster it runs on. That
way you can create test scenarios like: "please run my 'smoke' tests on a `kind` cluster; if they succeed, run '
functional' tests on an external cluster I give you `kube.config` for".

The type of cluster used for each type of tests is selected using the `--[TEST_TYPE]-tests-cluster-type`
config option. Additionally, if the cluster provider of given type supports some config files that allow you to tune how
the cluster is created, you can pass a path to that config file using the
`--[TEST_TYPE]-tests-cluster-config-file`.

Currently, the supported cluster types are:

1. `external` - it means the cluster is created out of the scope of control of `ats`. The user must pass a path to
   the `kube.config` file and cluster type and Kubernetes version as command line arguments.
1. `kind` - `ats` automatically create a [`kind`](https://kind.sigs.k8s.io/docs/user/quick-start/)
   cluster for that type of tests. You can additionally pass
   [kind config file](https://kind.sigs.k8s.io/docs/user/quick-start/#configuring-your-kind-cluster)
   to configure the cluster that will be created by `ats`.

### Test scenario example

**Info:** Please remember you can save any command line option you use constantly in the `.ats/main.yaml`
file and skip it from command line.

1. I want to run 'smoke' tests on a kind cluster and 'functional' tests on an external K8s 1.19.0 cluster created on
   EKS:

   ```bash
   # command-line version
   ats -c my-chart --smoke-tests-cluster-type kind \
     --functional-tests-cluster-type external \
     --external-cluster-kubeconfig-path kube.config \
     --external-cluster-type EKS \
     --external-cluster-version "1.19.0"
   ```

2. I want to run both `smoke` and `functional` tests on the same `kind` cluster. I want the `kind` cluster to be created
   according to my config file:

   ```yaml
   # config file version - content of `.ats/main.yaml`
   functional-tests-cluster-type: kind
   smoke-tests-cluster-type: kind
   smoke-tests-cluster-config-file: my-chart/kind_config.yaml
   functional-tests-cluster-config-file: my-chart/kind_config.yaml
   ```
