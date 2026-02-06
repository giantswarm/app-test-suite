FROM gsoci.azurecr.io/giantswarm/alpine:3.23.3 AS binaries

# renovate: datasource=github-releases depName=kubernetes/kubernetes
ARG KUBECTL_VER=v1.35.0
# renovate: datasource=github-releases depName=moby/moby
ARG DOCKER_VER=v28.5.2
# renovate: datasource=github-releases depName=kubernetes-sigs/kind
ARG KIND_VER=v0.31.0
# renovate: datasource=github-releases depName=giantswarm/apptestctl
ARG APPTESTCTL_VER=v0.25.0

RUN apk add --no-cache ca-certificates curl \
    && mkdir -p /binaries \
    && curl --silent --show-error --fail --location https://dl.k8s.io/release/${KUBECTL_VER}/bin/linux/amd64/kubectl --output /binaries/kubectl \
    && curl --silent --show-error --fail --location https://github.com/giantswarm/apptestctl/releases/download/${APPTESTCTL_VER}/apptestctl-${APPTESTCTL_VER}-linux-amd64.tar.gz | \
    tar --extract --gzip --directory /binaries --strip-components 1 apptestctl-${APPTESTCTL_VER}-linux-amd64/apptestctl \
    && curl --silent --show-error --fail --location https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VER##v}.tgz | \
    tar --extract --gzip --directory /binaries --strip-components 1 docker/docker \
    && curl --silent --show-error --fail --location https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VER}/kind-linux-amd64 --output /binaries/kind

COPY container-entrypoint.sh /binaries

RUN chmod +x /binaries/*


FROM python:3.12.7-slim AS base

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    ATS_DIR="/ats"

WORKDIR $ATS_DIR


FROM base AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Disable Python downloads, because we want to use the system interpreter
# across both images. If using a managed Python version, it needs to be
# copied from the build image into the final image; see `standalone.Dockerfile`
# for an example.
ENV UV_PYTHON_DOWNLOADS=0

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY README.md ${ATS_DIR}/
COPY app_test_suite/ ${ATS_DIR}/app_test_suite/

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked


FROM base

ARG GO_VERSION="1.23.1"

ENV USE_UID=0 \
    USE_GID=0 \
    PATH="${ATS_DIR}/.venv/bin:/usr/local/go/bin:$PATH" \
    PYTHONPATH=$ATS_DIR \
    GOPATH=$ATS_DIR

# install dependencies
RUN apt-get update && \
    apt-get install --no-install-recommends -y curl git sudo && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -SL https://dl.google.com/go/go${GO_VERSION}.linux-amd64.tar.gz | \
    tar -C /usr/local -xzf -

COPY --from=binaries /binaries/* /usr/local/bin/

# we assume the user will be using UID==1000 and GID=1000; if that's not true, we'll run `chown`
# in the container's startup script
COPY --from=builder --chown=1000:1000 $ATS_DIR $ATS_DIR

WORKDIR $ATS_DIR/workdir

RUN mkdir -p ${ATS_DIR}/.cache/go-build

ENTRYPOINT ["container-entrypoint.sh"]

CMD ["-h"]
