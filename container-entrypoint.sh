#!/bin/bash -e

if [ $# -eq 1 ] && [ "$1" == "versions" ]; then
  echo "-> python env:"
  python --version
  uv --version
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

# add user and group 'ats' with the same UID and GID as the user running the image in the host OS
if [ "${USE_UID:-0}" -ne 0 ] && [ "${USE_GID:-0}" -ne 0 ]; then
  groupadd -f -g "$USE_GID" ats
  groupadd -f -g "$DOCKER_GID" docker
  useradd -g "$USE_GID" -G docker -M -l -u "$USE_UID" ats -d "$ATS_DIR" -s /bin/bash || true
fi

# if the user in the host OS uses different UID/GID than default, we have to 'chown'
if [ "${USE_UID:-0}" -ne 1000 ] || [ "${USE_GID:-0}" -ne 1000 ]; then
  chown -R "$USE_UID":"$USE_GID" "$ATS_DIR"
fi

sudo --preserve-env=PYTHONPATH,PATH,GOPATH -g "#$USE_GID" -u "#$USE_UID" -- python -m app_test_suite "$@"
