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

# if the user in the OS uses different uid/gid for pipenv cache, we have to remember that and chown
# shellcheck disable=SC2153
PIPENV_CACHE_UID=$(stat -c '%u' "${PIPENV_CACHE_DIR}")
PIPENV_CACHE_GID=$(stat -c '%g' "${PIPENV_CACHE_DIR}")
PIPENV_PERM_CHANGED=0
if [ "${USE_UID:-0}" -ne "${PIPENV_CACHE_UID}" ] || [ "${USE_GID:-0}" -ne "${PIPENV_CACHE_GID}" ]; then
  PIPENV_PERM_CHANGED=1
  chown -R "$USE_UID":"$USE_GID" "$PIPENV_CACHE_DIR"
fi

# if the user in the OS uses different uid/gid for venvs, we have to remember that and chown
# shellcheck disable=SC2153
VENVS_UID=$(stat -c '%u' "${VENVS_DIR}")
VENVS_GID=$(stat -c '%g' "${VENVS_DIR}")
VENVS_PERM_CHANGED=0
if [ "${USE_UID:-0}" -ne "${VENVS_UID}" ] || [ "${USE_GID:-0}" -ne "${VENVS_GID}" ]; then
  VENVS_PERM_CHANGED=1
  chown -R "$USE_UID":"$USE_GID" "$VENVS_DIR"
fi

# run ats
sudo --preserve-env=PYTHONPATH,PATH -g "#$USE_GID" -u "#$USE_UID" -- python -m app_test_suite "$@"

# revert original permissions on pipenv cache (if changed)
if [ "${PIPENV_PERM_CHANGED}" -eq 1 ]; then
  chown -R "$PIPENV_CACHE_UID":"$PIPENV_CACHE_GID" "$PIPENV_CACHE_DIR"
fi

# revert original permissions on venvs dir (if changed)
if [ "${VENVS_PERM_CHANGED}" -eq 1 ]; then
  chown -R "$VENVS_UID":"$VENVS_GID" "$VENVS_DIR"
fi
