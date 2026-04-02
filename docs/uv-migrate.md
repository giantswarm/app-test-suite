# Uv migration from pipenv and pyenv

If you're not familiar with the `uv` tool, read the [intro](https://docs.astral.sh/uv/) and the
[installation](https://docs.astral.sh/uv/getting-started/installation/) page.

## Migration guide

The migration doesn't involve any changes in your tests' code. The only thing that changes is the tool you use
to ensure the dependencies (python version, libraries) are installed for your tests. As such, the migration is
pretty easy do to manually.

### Example

As an example, here's the process of migrating the hello-world-app from `pipenv` to `uv`.

1. Check the current project requirements in `pipenv`'s `Pipfile`

```sh
➜  cat Pipfile
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true

[requires]
python_version = "3"

[packages]
pytest-helm-charts = "~=1.3.2"
```

1. Init `uv`

We currently use python 3.12 in the docker image, so let's make sure we're compatible with that version:

```sh
➜  uv init -p 3.12
Initialized project `ats`
```

1. Add the same requirements for `uv` as stated for `pipenv`

```sh
➜  uv add "pytest-helm-charts~=1.3.2"
Using CPython 3.14.2
Creating virtual environment at: .venv
Resolved 17 packages in 392ms
Prepared 10 packages in 282ms
Installed 15 packages in 34ms
 + certifi==2026.2.25
 + charset-normalizer==3.4.6
 + deprecated==1.3.1
 + idna==3.11
 + iniconfig==2.3.0
 + packaging==26.0
 + pluggy==1.6.0
 + pygments==2.20.0
 + pykube-ng==23.6.0
 + pytest==8.4.2
 + pytest-helm-charts==1.3.4
 + pyyaml==6.0.3
 + requests==2.33.1
 + urllib3==2.6.3
 + wrapt==2.1.2
```

1. Check the generated config.

```sh
➜  cat pyproject.toml
[project]
name = "ats"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "pytest-helm-charts~=1.3.2",
]
```

1. Clean up files

If you didn't use these files, `uv` generated them for the new project. Clean them up if you don't need them:

```sh
rm README.md main.py
```

1. Clean up pipenv config

```sh
rm Pipfile Pipfile.lock
```

1. Test the migration
