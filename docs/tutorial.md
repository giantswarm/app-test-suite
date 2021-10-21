# How to use app-test-suite to test an app

## Preparing tools

**Please note**: this tutorial was written with python 3.8, but should work exactly the same with 3.9 and newer.

To be able to complete this tutorial, you need a few tools:

- `app-test-suite` itself; if you haven't done so already, we recommend getting the latest version of the `dats.sh`
  helper from [releases](https://github.com/giantswarm/app-test-suite/releases)
- a working python environment that you can use to install [pipenv](https://pypi.org/project/pipenv/)
  - if you already have python, it should be enough to run `pip install -U pipenv`
- to be able to use the shortest path, you also need a working python 3.8 environment
  - to avoid problems like missing the specific python version, we highly recommend
    [`pyenv`](https://github.com/pyenv/pyenv#installation) for managing python environments; once `pyenv` is
    installed, it's enough to run `pyenv install 3.8.6` to get the python environment you need

## Testing your app

### How does it work?

To get started, it's important to note that `ats` just executes tests, but doesn't implement any tests nor cares about
how you implement them. The contract is just that `ats` can invoke a specific `pytest` commands for you. If you
implement your tests using `pytest`, `ats` can start them automatically. More information is
available [here](pytest-test-pipeline.md). You can use `pytest` only, but the recommended way to implement tests for
running with `ats` is using `pytest` and our plugin called
[`pytest-helm-charts`](https://github.com/giantswarm/pytest-helm-charts).

### Why do I need a specific python version?

In general, you can use any python version you want, unless you're using the dockerized `dats.sh` wrapper, which is also
our recommended way of running `ats`. Inside the docker image `dats.sh` is using, there's only one python version
available. This python version is used by `ats` to invoke your tests implemented with `pytest`. As a result, if you
request any other python version than the one currently used by `dats.sh`, you'll get an error, as that version is not
available inside the docker image.

You can check the current python version (and versions of all the other software projects `ats` is using) by running:

```bash
$ dats.sh versions
-> python env:
Python 3.8.6
pip 20.3.1 from /ats/.venv/lib/python3.8/site-packages/pip (python 3.8)
pipenv, version 2020.11.15
...
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

Let's create a directory for storing tests. `ats` looks for them in the `tests/ats`
subdirectory of the helm chart, so let's start a fresh python virtual env there:

```bash
$ mkdir -p examples/tutorial/tests/ats
$ cd examples/tutorial/tests/ats
$ pipenv --python 3.8
Creating a virtualenv for this project...
Pipfile: /home/piontec/work/giantswarm/git/app-test-suite/examples/tutorial/tests/ats/Pipfile
Using /home/piontec/tools/pyenv/versions/3.8.8/bin/python3.8 (3.8.8) to create virtualenv...
⠴ Creating virtual environment...created virtual environment CPython3.8.8.final.0-64 in 262ms
  creator CPython3Posix(dest=/home/piontec/.virtualenvs/ats-DRi5BLbR, clear=False, no_vcs_ignore=False, global=False)
  seeder FromAppData(download=False, pip=bundle, setuptools=bundle, wheel=bundle, via=copy, app_data_dir=/home/piontec/.local/share/virtualenv)
    added seed packages: pip==21.1.2, setuptools==57.0.0, wheel==0.36.2
  activators BashActivator,CShellActivator,FishActivator,PowerShellActivator,PythonActivator,XonshActivator

✔ Successfully created virtual environment!
Virtualenv location: /home/piontec/.virtualenvs/ats-DRi5BLbR
Creating a Pipfile for this project...
```

Now, we need to add our dependencies. If we're going to use `pytest-helm-chart`, everything else will come as
dependencies:

```bash
$ pipenv install "pytest-helm-charts>=0.3.1"
Installing pytest-helm-charts>=0.3.1...
Adding pytest-helm-charts to Pipfile's [packages]...
✔ Installation Succeeded
Pipfile.lock not found, creating...
Locking [dev-packages] dependencies...
Locking [packages] dependencies...
Building requirements...
Resolving dependencies...
✔ Success!
Updated Pipfile.lock (a62443)!
Installing dependencies from Pipfile.lock (a62443)...
  🐍   ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉ 0/0 — 00:00:00
```

As a result, our `Pipfile` should look like this basic version:

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
pytest-helm-charts = ">=0.3.1"

[dev-packages]

[requires]
python_version = "3.8"
```

#### Implementing tests

Now we can start implementing actual tests. To get a full sample source code, just copy
the `test_example.py` [file](../examples/apps/hello-world-app/tests/ats/test_example.py) to our `tests/ats` directory,
so it looks like this:

```bash
$ ls
Pipfile  Pipfile.lock  test_example.py
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

In this test, we're only checking if we can get a working connection object to work with our cluster. This is done by
requesting the `kube_cluster: Cluster` object for our test (test method parameters
are [pytest fixtures](https://docs.pytest.org/en/stable/fixture.html) and are injected for you by the test framework
itself). Additionally, we're marking our test as a "smoke" test. This information is provided for `ats` itself: we want
to include opinionated test scenarios in `ats` and that way `ats` knows if it should run your test for specific scenario
or not.

You can read more about [how `ats` executes tests](./pytest-test-pipeline.md) and how to implement them
with [pytest-helm-charts](https://pytest-helm-charts.readthedocs.io/en/latest/)
and [pytest](https://docs.pytest.org/en/stable/index.html), including information about
[available fixtures](https://pytest-helm-charts.readthedocs.io/en/latest/api/pytest_helm_charts.fixtures/).

#### Running tests

We are now ready to build our test chart again, but this time running tests we've implemented. To do that, we need to
have a cluster where we can deploy our chart and then execute our tests against a running application. Do make this time
efficient, we'll use [kind](https://kind.sigs.k8s.io/docs/user/quick-start/). We're going to use embedded `ats` ability
to create `kind` clusters, but remember that you can use any existing cluster you like - you just need to pass
a `kube.config`
file to `ats`. Switch back to the root directory of this repository.
`ats` can run different types of tests on different clusters, so we have to pass cluster type option
twice, but our cluster will be reused for both kinds of tests:

```bash
# log below is truncated to interesting parts only
dats.sh -c examples/tutorial/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz --smoke-tests-cluster-type kind --functional-tests-cluster-type kind
2021-06-22 14:30:46,890 __main__ INFO: Starting test with the following options
2021-06-22 14:30:46,890 __main__ INFO:
Command Line Args:   -c examples/tutorial/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz --smoke-tests-cluster-type kind --functional-tests-cluster-type kind
Defaults:
  --steps:           ['all']
  --skip-steps:      []
  --app-tests-deploy-namespace:default
  --app-tests-pytest-tests-dir:tests/ats

2021-06-22 14:30:46,890 step_exec_lib.steps INFO: Running pre-run step for TestInfoProvider
2021-06-22 14:30:46,891 step_exec_lib.steps INFO: Running pre-run step for PytestSmokeTestRunner
...
2021-06-22 14:31:18,364 app_test_suite.steps.base_test_runner INFO: Running apptestctl tool to ensure app platform components on the target cluster
2021-06-22 14:31:18,364 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:31:18,365 step_exec_lib.utils.processes INFO: apptestctl bootstrap --kubeconfig-path=b523598b-f618-4527-b774-2f04cf36f388.kube.config --wait
...
2021-06-22 14:32:54,430 app_test_suite.steps.base_test_runner INFO: App platform components bootstrapped and ready to use.
2021-06-22 14:32:54,456 app_test_suite.steps.repositories INFO: Uploading file 'examples/tutorial/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz' to chart-museum.
2021-06-22 14:32:54,468 app_test_suite.steps.base_test_runner INFO: Creating App CR for app 'hello-world-app' to be deployed in namespace 'default' in version '0.2.3-90e2f60e6810ddf35968221c193340984236fe2a'.
2021-06-22 14:32:55,490 app_test_suite.steps.pytest.pytest INFO: Running pipenv tool in 'examples/tutorial/tests/ats' directory to install virtual env for running tests.
2021-06-22 14:32:55,490 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:32:55,490 step_exec_lib.utils.processes INFO: pipenv install --deploy
Creating a virtualenv for this project...
Pipfile: /ats/workdir/examples/tutorial/tests/ats/Pipfile
Using /ats/.venv/bin/python3.8 (3.8.6) to create virtualenv...
⠴ Creating virtual environment...created virtual environment CPython3.8.6.final.0-64 in 1470ms
  creator CPython3Posix(dest=/ats/.local/share/virtualenvs/ats-SrLP7Uv-, clear=False, no_vcs_ignore=False, global=False)
  seeder FromAppData(download=False, pip=bundle, setuptools=bundle, wheel=bundle, via=copy, app_data_dir=/ats/.local/share/virtualenv)
    added seed packages: pip==21.1.2, setuptools==57.0.0, wheel==0.36.2
  activators BashActivator,CShellActivator,FishActivator,PowerShellActivator,PythonActivator,XonshActivator

✔ Successfully created virtual environment!
Virtualenv location: /ats/.local/share/virtualenvs/ats-SrLP7Uv-
Installing dependencies from Pipfile.lock (a62443)...
  🐍   ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉ 16/16 — 00:00:11
2021-06-22 14:33:14,280 step_exec_lib.utils.processes INFO: Command executed, exit code: 0.
2021-06-22 14:33:14,280 app_test_suite.steps.pytest.pytest INFO: Running pytest tool in 'examples/tutorial/tests/ats' directory.
2021-06-22 14:33:14,280 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:33:14,280 step_exec_lib.utils.processes INFO: pipenv run pytest -m smoke --cluster-type kind --kube-config /ats/workdir/b523598b-f618-4527-b774-2f04cf36f388.kube.config --chart-path examples/tutorial/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz --chart-version 0.2.3-90e2f60e6810ddf35968221c193340984236fe2a --chart-extra-info external_cluster_version=v1.19.1 --log-cli-level info --junitxml=test_results_smoke.xml
=========================================================== test session starts ============================================================
platform linux -- Python 3.8.6, pytest-6.2.4, py-1.10.0, pluggy-0.13.1
rootdir: /ats/workdir
plugins: helm-charts-0.3.1
collected 2 items / 1 deselected / 1 selected

test_example.py::test_we_have_environment
-------------------------------------------------------------- live log setup --------------------------------------------------------------
INFO     pytest_helm_charts.fixtures:fixtures.py:85 Cluster configured
PASSED                                                                                                                               [100%]
------------------------------------------------------------ live log teardown -------------------------------------------------------------
INFO     pytest_helm_charts.fixtures:fixtures.py:91 Cluster released


============================================================= warnings summary =============================================================
test_example.py:8
  /ats/workdir/examples/tutorial/tests/ats/test_example.py:8: PytestUnknownMarkWarning: Unknown pytest.mark.smoke - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/mark.html
    @pytest.mark.smoke

test_example.py:14
  /ats/workdir/examples/tutorial/tests/ats/test_example.py:14: PytestUnknownMarkWarning: Unknown pytest.mark.functional - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/mark.html
    @pytest.mark.functional

-- Docs: https://docs.pytest.org/en/stable/warnings.html
--------------------------- generated xml file: /ats/workdir/examples/tutorial/tests/ats/test_results_smoke.xml ----------------------------
=============================================== 1 passed, 1 deselected, 2 warnings in 0.07s ================================================
2021-06-22 14:33:16,887 step_exec_lib.utils.processes INFO: Command executed, exit code: 0.
2021-06-22 14:33:16,888 app_test_suite.steps.base_test_runner INFO: Deleting App CR
2021-06-22 14:33:17,916 app_test_suite.steps.base_test_runner INFO: Application deleted
2021-06-22 14:33:17,916 step_exec_lib.steps INFO: Running build step for PytestFunctionalTestRunner
2021-06-22 14:33:17,936 app_test_suite.steps.base_test_runner INFO: Running apptestctl tool to ensure app platform components on the target cluster
2021-06-22 14:33:17,936 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:33:17,937 step_exec_lib.utils.processes INFO: apptestctl bootstrap --kubeconfig-path=b523598b-f618-4527-b774-2f04cf36f388.kube.config --wait
...
2021-06-22 14:33:21,102 app_test_suite.steps.base_test_runner INFO: App platform components bootstrapped and ready to use.
2021-06-22 14:33:21,117 app_test_suite.steps.repositories INFO: Uploading file 'examples/tutorial/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz' to chart-museum.
2021-06-22 14:33:21,134 app_test_suite.steps.base_test_runner INFO: Creating App CR for app 'hello-world-app' to be deployed in namespace 'default' in version '0.2.3-90e2f60e6810ddf35968221c193340984236fe2a'.
2021-06-22 14:33:22,155 app_test_suite.steps.pytest.pytest INFO: Running pipenv tool in 'examples/tutorial/tests/ats' directory to install virtual env for running tests.
2021-06-22 14:33:22,155 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:33:22,155 step_exec_lib.utils.processes INFO: pipenv install --deploy
Installing dependencies from Pipfile.lock (a62443)...
  🐍   ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉ 0/0 — 00:00:00
2021-06-22 14:33:25,325 step_exec_lib.utils.processes INFO: Command executed, exit code: 0.
2021-06-22 14:33:25,326 app_test_suite.steps.pytest.pytest INFO: Running pytest tool in 'examples/tutorial/tests/ats' directory.
2021-06-22 14:33:25,326 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:33:25,326 step_exec_lib.utils.processes INFO: pipenv run pytest -m functional --cluster-type kind --kube-config /ats/workdir/b523598b-f618-4527-b774-2f04cf36f388.kube.config --chart-path examples/tutorial/hello-world-app-0.2.3-90e2f60e6810ddf35968221c193340984236fe2a.tgz --chart-version 0.2.3-90e2f60e6810ddf35968221c193340984236fe2a --chart-extra-info external_cluster_version=v1.19.1 --log-cli-level info --junitxml=test_results_functional.xml
=========================================================== test session starts ============================================================
platform linux -- Python 3.8.6, pytest-6.2.4, py-1.10.0, pluggy-0.13.1
rootdir: /ats/workdir
plugins: helm-charts-0.3.1
collected 2 items / 1 deselected / 1 selected

test_example.py::test_hello_working
-------------------------------------------------------------- live log setup --------------------------------------------------------------
INFO     pytest_helm_charts.fixtures:fixtures.py:85 Cluster configured
PASSED                                                                                                                               [100%]
------------------------------------------------------------ live log teardown -------------------------------------------------------------
INFO     pytest_helm_charts.fixtures:fixtures.py:91 Cluster released


============================================================= warnings summary =============================================================
test_example.py:8
  /ats/workdir/examples/tutorial/tests/ats/test_example.py:8: PytestUnknownMarkWarning: Unknown pytest.mark.smoke - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/mark.html
    @pytest.mark.smoke

test_example.py:14
  /ats/workdir/examples/tutorial/tests/ats/test_example.py:14: PytestUnknownMarkWarning: Unknown pytest.mark.functional - is this a typo?  You can register custom marks to avoid this warning - for details, see https://docs.pytest.org/en/stable/mark.html
    @pytest.mark.functional

-- Docs: https://docs.pytest.org/en/stable/warnings.html
------------------------- generated xml file: /ats/workdir/examples/tutorial/tests/ats/test_results_functional.xml -------------------------
=============================================== 1 passed, 1 deselected, 2 warnings in 0.09s ================================================
2021-06-22 14:33:27,813 step_exec_lib.utils.processes INFO: Command executed, exit code: 0.
2021-06-22 14:33:27,813 app_test_suite.steps.base_test_runner INFO: Deleting App CR
2021-06-22 14:33:28,839 app_test_suite.steps.base_test_runner INFO: Application deleted
2021-06-22 14:33:28,839 app_test_suite.cluster_providers.kind_cluster_provider INFO: Deleting KinD cluster with ID 'b523598b-f618-4527-b774-2f04cf36f388'...
2021-06-22 14:33:28,839 step_exec_lib.utils.processes INFO: Running command:
2021-06-22 14:33:28,839 step_exec_lib.utils.processes INFO: kind delete cluster --name b523598b-f618-4527-b774-2f04cf36f388
2021-06-22 14:33:30,112 step_exec_lib.utils.processes INFO: Command executed, exit code: 0.
2021-06-22 14:33:30,113 app_test_suite.cluster_providers.kind_cluster_provider INFO: KinD cluster deleted successfully
```

That's it. When our tests have passed, you know that the Chart was really deployed to the cluster and responded
to your requests!
