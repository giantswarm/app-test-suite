# Image URL to use all building/pushing image targets
IMG ?= gsoci.azurecr.io/giantswarm/app-test-suite

export VER ?= $(shell git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0")
export COMMIT ?= $(shell git rev-parse HEAD 2>/dev/null || echo "0000000000000000000000000000000000000000")
export SHORT_COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo "0000000")
export DATE ?= $(shell date '+%FT%T%:z')

IMG_VER ?= ${VER}-${COMMIT}

.PHONY: all release release_ver_to_code docker-build docker-build-image docker-build-ver docker-push docker-build-test test docker-test docker-test-ci update-crds

# Version of giantswarm/apptestctl whose pkg/crds/ is vendored into container-crds/.
# Keep this in sync with container-crds/README.md.
APPTESTCTL_CRDS_VER ?= v0.25.1

check_defined = \
    $(strip $(foreach 1,$1, \
        $(call __check_defined,$1,$(strip $(value 2)))))
__check_defined = \
    $(if $(value $1),, \
      $(error Undefined $1$(if $2, ($2))))

all: docker-build

release: release_ver_to_code docker-test docker-build-image
	git add --force app_test_suite/version.py
	git add pyproject.toml uv.lock
	git commit -m "Release ${TAG}" --no-verify
	git tag ${TAG}
	docker build . -t ${IMG}:latest -t ${IMG}:${TAG}
	export NEXT=$(shell uv version --dry-run --short --bump patch) && echo "build_ver = \"v$${NEXT}-dev\"" > app_test_suite/version.py
	git add --force app_test_suite/version.py
	git commit -m "Post-release version set for ${TAG}" --no-verify

release_ver_to_code:
	$(call check_defined, TAG)
	sed -i 's/version = ".*"/version = "'${TAG}'"/' pyproject.toml
	uv lock
	echo "build_ver = \"${TAG}\"" > app_test_suite/version.py
	$(eval IMG_VER := ${TAG})

# Build the docker image from locally built binary
docker-build: docker-build-ver docker-build-image

docker-build-image:
	docker build . -t ${IMG}:latest -t ${IMG}:${IMG_VER}

docker-build-ver:
	echo "build_ver = \"${VER}-${COMMIT}\"" > app_test_suite/version.py

# Push the docker image
docker-push: docker-build
	docker push ${IMG}:${IMG_VER}

docker-build-test: docker-build
	docker build -f testrunner.Dockerfile . -t ${IMG}-test:latest

test-command = --cov app_test_suite --log-cli-level info tests/
test-command-ci = --cov-report=xml $(test-command)
test-docker-args = run -it --rm -v ${PWD}/.coverage/:/ats/.coverage/
test-docker-run = docker $(test-docker-args) ${IMG}-test:latest

test:
	uv run python -m pytest $(test-command)

docker-test: docker-build-test
	$(test-docker-run) $(test-command)

docker-test-ci: docker-build-test
	$(test-docker-run) $(test-command-ci)

# Re-vendor the CRD bundle from apptestctl pkg/crds/ at $(APPTESTCTL_CRDS_VER).
update-crds: ## Refresh container-crds/ from giantswarm/apptestctl pkg/crds (set APPTESTCTL_CRDS_VER)
	rm -rf /tmp/apptestctl-crds
	git clone --quiet --depth 1 --branch $(APPTESTCTL_CRDS_VER) https://github.com/giantswarm/apptestctl /tmp/apptestctl-crds
	find container-crds -name '*.yaml' -delete
	cp /tmp/apptestctl-crds/pkg/crds/*.yaml container-crds/
	rm -rf /tmp/apptestctl-crds
	@echo "Vendored CRDs from apptestctl $(APPTESTCTL_CRDS_VER). Update APPTESTCTL_CRDS_VER in container-crds/README.md."
