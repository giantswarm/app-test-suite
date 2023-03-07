#!/bin/bash -e

pipenv run pre-commit run -a
pipenv run pytest "$@"
