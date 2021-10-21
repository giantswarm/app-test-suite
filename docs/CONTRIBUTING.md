# App test suite contribution guidelines

`app-test-suite` is built using Python >= 3.9 and pipenv.

## Development setup

### Without docker

This setup is recommended for GUI and running interactively with debuggers. Check below for a version that runs inside a
docker container.

A good method of handling Python installations is to use [pyenv](https://github.com/pyenv/pyenv).

```bash
# Install pipenv
pip install pipenv
# to create venv
pipenv install --dev
# to configure quality check triggers
pipenv run pre-commit install
```

You also need a bunch of binary tools, which normally are present in the docker image, but for developing locally, you
need to install them on your own. You can list all the required tools and versions currently used by running:

```bash
dats.sh versions
```

### With docker

It is possible to skip installing Python locally and utilize docker by mounting the repository into a running container.

```bash
# do this once (and every time you change something in Dockerfile)
docker build -t app-test-suite:dev .
# in the root of this repository
docker run --rm -it -v $(pwd)/app_test_suite:/ats/app_test_suite -v $(pwd):/ats/workdir --entrypoint /bin/bash app-test-suite:dev
```

Once inside the container, just execute `python -m app_test_suite`.

## Extending `ats`

### How it's implemented

The execution logic is based entirely on the [step-exec-lib](https://github.com/giantswarm/step-exec-lib). Please check its
docs for more information about the base classes used here.

#### Cluster provider

`ats` allows you to run different types of tests on clusters you have configured for them. To allow the user to choose
on which type of cluster the specific test type will run, there has to be a
[`ClusterProvider`](../app_test_suite/cluster_providers/cluster_provider.py) for that specific cluster. Please make sure
you register any new `ClusterProviders` in the package's
[`__init__.py`](../app_test_suite/cluster_providers/__init__.py), as they are auto-discovered from there. When you're
done with it, you don't have to write any additional code to make the new cluster type available.

As an example, please have a look at
[`ExternalClusterProvider`](../app_test_suite/cluster_providers/external_cluster_provider.py).

## Tests

We encourage adding tests. Execute them with `make docker-test`

## Releases

At this point, this repository does not make use of the release automation implemented in GitHub actions.

To create a release, switch to the `master` branch, make sure everything you want to have in your release is committed
and documented in the CHANGELOG.md file and your git stage is clean. Now execute:

```bash
    make release TAG=vX.Y.Z
```

This will prepare the files in the repository, commit them and create a new git tag. Review the created commits. When
satisfied, publish the new release with:

```bash
    git push origin vX.Y.Z
```
