#!/bin/bash -e

if [ $# -eq 1 ] && [ "$1" == "versions" ]; then
  echo "-> python env:"
  python --version
  pip --version
  pipenv --version
  echo
  echo "-> kubectl:"
  kubectl version --client
  echo
  echo "-> apptestctl:"
  apptestctl version
  echo "-> kind:"
  kind version
  echo
  echo "-> go:"
  go version
  exit 0
fi

if [ "${USE_UID:-0}" -ne 0 ] && [ "${USE_GID:-0}" -ne 0 ]; then
  groupadd -f -g "$USE_GID" ats
  groupadd -f -g "$DOCKER_GID" docker
  useradd -g "$USE_GID" -G docker -M -l -u "$USE_UID" ats -d "$ATS_DIR" -s /bin/bash || true
fi

if [ "${USE_UID:-0}" -ne 1000 ] || [ "${USE_GID:-0}" -ne 1000 ]; then
  chown -R "$USE_UID":"$USE_GID" "$ATS_DIR"
fi
sudo --preserve-env=PYTHONPATH,PATH,GOPATH -g "#$USE_GID" -u "#$USE_UID" -- python -m app_test_suite "$@"
