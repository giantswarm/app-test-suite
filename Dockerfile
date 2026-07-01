FROM gsoci.azurecr.io/giantswarm/alpine:3.24.1 AS binaries

ARG TARGETARCH=amd64

# renovate: datasource=github-releases depName=kubernetes/kubernetes
ARG KUBECTL_VER=v1.36.2
# renovate: datasource=github-releases depName=moby/moby
ARG DOCKER_VER=v28.5.2
# renovate: datasource=github-releases depName=kubernetes-sigs/kind
ARG KIND_VER=v0.32.0
# renovate: datasource=github-releases depName=helm/helm
ARG HELM_VER=v4.2.2

RUN apk add --no-cache ca-certificates curl \
    && mkdir -p /binaries \
    && DOCKER_ARCH=$([ "${TARGETARCH}" = "arm64" ] && echo "aarch64" || echo "x86_64") \
    && curl --silent --show-error --fail --location https://dl.k8s.io/release/${KUBECTL_VER}/bin/linux/${TARGETARCH}/kubectl --output /binaries/kubectl \
    && curl --silent --show-error --fail --location https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-${DOCKER_VER##v}.tgz | \
    tar --extract --gzip --directory /binaries --strip-components 1 docker/docker \
    && curl --silent --show-error --fail --location https://get.helm.sh/helm-${HELM_VER}-linux-${TARGETARCH}.tar.gz | \
    tar --extract --gzip --directory /binaries --strip-components 1 linux-${TARGETARCH}/helm \
    && curl --silent --show-error --fail --location https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VER}/kind-linux-${TARGETARCH} --output /binaries/kind

COPY container-entrypoint.sh /binaries

RUN chmod +x /binaries/*


FROM python:3.14.6-slim AS base

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    ATS_DIR="/ats"

WORKDIR $ATS_DIR


FROM base AS builder

ENV UV_LINK_MODE=copy

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

ARG TARGETARCH=amd64
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

RUN curl -SL https://dl.google.com/go/go${GO_VERSION}.linux-${TARGETARCH}.tar.gz | \
    tar -C /usr/local -xzf -

COPY --from=builder ${ATS_DIR}/.venv ${ATS_DIR}/.venv

COPY --from=binaries /binaries/* /usr/local/bin/
COPY container-crds/*.yaml /etc/ats/crds/

# we assume the user will be using UID==1000 and GID=1000; if that's not true, we'll run `chown`
# in the container's startup script
COPY --from=builder --chown=1000:1000 $ATS_DIR $ATS_DIR

WORKDIR $ATS_DIR/workdir

RUN mkdir -p ${ATS_DIR}/.cache/go-build

ENTRYPOINT ["container-entrypoint.sh"]

CMD ["-h"]
