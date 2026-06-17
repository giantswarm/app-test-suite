#!/bin/sh

DATS_TAG=${DATS_TAG:-"0.14.0"}

# Please Note
# This script speeds up test execution by caching uv's package downloads.
# To make this work on CI systems, ensure $UV_CACHE_DIR below is persisted between runs.

# don't override variables below
ATS_DIR="/ats"
UV_CACHE_DIR=".cache/uv"

docker run -it --rm \
    -e USE_UID="$(id -u "${USER}")" \
    -e USE_GID="$(id -g "${USER}")" \
    -e DOCKER_GID="$(getent group docker | cut -d: -f3)" \
    -e UV_CACHE_DIR="${ATS_DIR}/${UV_CACHE_DIR}" \
    -v "$(pwd):${ATS_DIR}/workdir/" \
    -v "${HOME}/${UV_CACHE_DIR}:${ATS_DIR}/${UV_CACHE_DIR}" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    --network host \
    "gsoci.azurecr.io/giantswarm/app-test-suite:${DATS_TAG}" "$@"
