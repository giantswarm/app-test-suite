# How to use app-test-suite to test an app

## Preparing tools

**Please note**: this tutorial uses [uv](https://docs.astral.sh/uv/) for managing test dependencies.
The ATS docker image ships `uv`, so no separate installation is needed when running inside the container.

To be able to complete this tutorial, you need a few tools:

- `app-test-suite` itself; it is distributed as a docker image you run directly (optionally via the `ats`
  alias described in the [README](../README.md#installation))
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for managing test dependencies locally
  - install with: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Testing your app

### How does it work?

To get started, it's important to note that `ats` just executes tests, but doesn't implement any tests nor
cares about how you implement them. The contract is just that `ats` can invoke a specific `pytest` commands
for you. If you implement your tests using `pytest`, `ats` can start them automatically. More information is
available [in the pytest pipeline docs](pytest-test-pipeline.md). You can use `pytest` only, but the
recommended way to implement tests for running with `ats` is using `pytest` and our plugin called
[`pytest-helm-charts`](https://github.com/giantswarm/pytest-helm-charts).

### Why do I need a specific python version?

In general, you can use any python version you want, unless you're using the ATS docker image,
which is also our recommended way of running `ats`. Inside the ATS docker image, there's only
one python version available. This python version is used by `ats` to invoke your tests implemented with
`pytest`. As a result, if you request any other python version than the one currently used by the ATS docker image,
you'll get an error, as that version is not available inside the docker image.

You can check the current python version (and versions of all the other software projects `ats` is using) by
running:

```bash
$ ats versions
-> python env:
Python 3.12.x
uv ...
-> binary versions:
helm: ...
kubectl: ...
kind: ...
```

### Writing the tests

We will now write some tests to test the
[example hello world chart](../examples/apps/hello-world-app/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz).

#### Preparing environment

To get started, let's make a copy of the ready example already present in the `examples` directory.

```bash
mkdir examples/tutorial
cp -a examples/apps/hello-world-app/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz examples/tutorial
```

Let's create a directory for storing tests. `ats` looks for them in the `tests/ats` subdirectory relative to
the directory you run `ats` from (the working directory), so let's initialise a uv project there:

```bash
mkdir -p examples/tutorial/tests/ats
cd examples/tutorial/tests/ats
uv init --no-workspace --no-readme
uv add "pytest-helm-charts>=0.5"
```

As a result, the `pyproject.toml` should look like this:

```toml
[project]
name = "my-chart-tests"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pytest-helm-charts>=0.5",
]
```

Commit both `pyproject.toml` and `uv.lock` — `ats` calls `uv sync` (equivalent to `pip install`) before running
tests and expects the lock file to be present.

#### Implementing tests

Now we can start implementing actual tests. To get a full sample source code, just copy the `test_example.py`
[file](../examples/apps/hello-world-app/tests/ats/test_example.py) to our `tests/ats` directory, so it looks
like this:

```bash
$ ls
pyproject.toml  uv.lock  test_example.py
```

The simplest test case code in the `test_example.py` file looks like this:

```python
import pytest
import pykube
from pytest_helm_charts.fixtures import Cluster


@pytest.mark.smoke
def test_we_have_environment(kube_cluster: Cluster) -> None:
    assert kube_cluster.kube_client is not None
    assert len(pykube.Node.objects(kube_cluster.kube_client)) >= 1
```

In this test, we're only checking if we can get a working connection object to work with our cluster. This is
done by requesting the `kube_cluster: Cluster` object for our test (test method parameters are
[pytest fixtures](https://docs.pytest.org/en/stable/fixture.html) and are injected for you by the test
framework itself). Additionally, we're marking our test as a "smoke" test. This information is provided for
`ats` itself: we want to include opinionated test scenarios in `ats` and that way `ats` knows if it should run
your test for specific scenario or not.

You can read more about [how `ats` executes tests](./pytest-test-pipeline.md) and how to implement them with
[pytest-helm-charts](https://pytest-helm-charts.readthedocs.io/en/latest/) and
[pytest](https://docs.pytest.org/en/stable/index.html), including information about
[available fixtures](https://pytest-helm-charts.readthedocs.io/en/latest/api/pytest_helm_charts.fixtures/).

#### Running tests

We are now ready to build our test chart again, but this time running tests we've implemented. To do that, we
need to have a cluster where we can deploy our chart and then execute our tests against a running application.
Do make this time efficient, we'll use [kind](https://kind.sigs.k8s.io/docs/user/quick-start/). We're going to
use embedded `ats` ability to create `kind` clusters, but remember that you can use any existing cluster you
like - you just need to pass a `kube.config` file to `ats`. Run `ats` from the `examples/tutorial` directory,
so it discovers the tests in `tests/ats` relative to it (the chart archive passed with `-c` can live
anywhere). `ats` can run different types of tests on different clusters, so we have to pass cluster type
option twice, but our cluster will be reused for both kinds of tests:

```bash
# log truncated to key steps
cd examples/tutorial
ats -c hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz \
    --smoke-tests-cluster-type kind --functional-tests-cluster-type kind
...
INFO: Running pre-run step for TestInfoProvider
INFO: Running pre-run step for SmokeTestScenario
...
INFO: Applying cluster CRDs from /etc/ats/crds
INFO: Running command: kubectl --kubeconfig=<uuid>.kube.config apply --server-side -f /etc/ats/crds
INFO: Cluster CRDs bootstrapped and ready.
INFO: Ensuring namespace 'policy-exceptions'.
INFO: Installing chart as Helm release 'hello-world-app' into namespace 'default'.
INFO: Running command: helm upgrade --install hello-world-app \
    hello-world-app-0.2.3-....tgz \
    --namespace default --create-namespace --reset-values --wait --timeout 30m
...
INFO: Running 'uv sync' in 'tests/ats' to install test virtual env.
INFO: Running pytest tool in 'tests/ats' directory.
INFO: Running command: uv run pytest -m smoke --log-cli-level info --junitxml=test_results_smoke.xml

test_example.py::test_we_have_environment PASSED                                [100%]

================= 1 passed, 1 deselected in 0.07s =================

INFO: Uninstalling Helm release 'hello-world-app' from namespace 'default'.
INFO: Running build step for FunctionalTestScenario
...
INFO: Installing chart as Helm release 'hello-world-app' into namespace 'default'.
...
INFO: Running command: uv run pytest -m functional --log-cli-level info --junitxml=test_results_functional.xml

test_example.py::test_hello_working PASSED                                      [100%]

================= 1 passed, 1 deselected in 0.09s =================

INFO: Uninstalling Helm release 'hello-world-app' from namespace 'default'.
INFO: Deleting KinD cluster...
```

That's it. When our tests have passed, you know that the Chart was really deployed to the cluster and
responded to your requests!
