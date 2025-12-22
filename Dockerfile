FROM gsoci.azurecr.io/giantswarm/alpine:3.23.2 AS binaries

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

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    ATS_DIR="/ats" \
    PIPENV_VER="2024.1.0"

RUN pip install --no-cache-dir pipenv==${PIPENV_VER}

WORKDIR $ATS_DIR


FROM base as builder

# pip prerequesties
RUN apt-get update && \
    apt-get install --no-install-recommends -y gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY Pipfile Pipfile.lock ./

RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy --clear


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

COPY --from=builder ${ATS_DIR}/.venv ${ATS_DIR}/.venv

COPY --from=binaries /binaries/* /usr/local/bin/

COPY app_test_suite/ ${ATS_DIR}/app_test_suite/

WORKDIR $ATS_DIR/workdir

RUN mkdir -p ${ATS_DIR}/.cache/go-build

# we assume the user will be using UID==1000 and GID=1000; if that's not true, we'll run `chown`
# in the container's startup script
RUN chown -R 1000:1000 $ATS_DIR

ENTRYPOINT ["container-entrypoint.sh"]

CMD ["-h"]
