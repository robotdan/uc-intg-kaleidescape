#!/bin/bash
set -euo pipefail

# Only run on macOS
if [[ "$(uname)" != "Darwin" ]]; then
  echo "This script is intended to run on macOS."
  exit 0
fi

# Check if Docker is available
if ! docker system info > /dev/null 2>&1; then
  echo "Docker is not running."

  # Check if current user has an active GUI session
  ACTIVE_USER=$(stat -f "%Su" /dev/console)
  if [[ "$ACTIVE_USER" != "$USER" ]]; then
    echo "No active GUI session for user '$USER'."
    echo "To use Docker via SSH, make sure:"
    echo "  1. Automatic login is enabled for your user."
    echo "  2. Docker Desktop is set to launch on login."
    echo "  3. You are logged into the GUI after reboot."
  fi

  echo "Your user has an active console session, but Docker may not have launched."
  echo "Start Docker Desktop manually or reboot with login auto-start enabled."
  exit 1
fi

INTG_DIR="intg-kaleidescape"
PYINSTALLER_IMAGE="docker.io/unfoldedcircle/r2-pyinstaller:3.11.12"
DRIVER_ID=$(jq -r .driver_id driver.json)
VERSION=${1:-dev}

echo "Building uc-intg-${DRIVER_ID} version ${VERSION}..."

rm -rf dist build artifacts

docker run --rm --name builder \
  --user="$(id -u):$(id -g)" \
  -v "$(pwd):/workspace" \
  "${PYINSTALLER_IMAGE}" \
  bash -c \
  "cd /workspace && \
    python -m pip install -r requirements.txt && \
    pyinstaller --clean --onedir --name driver \
      --add-data driver.json:. \
      --collect-all pykaleidescape \
      --collect-all ucapi \
      --paths . \
      ${INTG_DIR}/driver.py"

mkdir -p artifacts/bin
mv dist/driver/* artifacts/bin/
cp driver.json artifacts/
cp Kaleidescape-Logo-Jewel.png artifacts/

ARTIFACT_NAME="uc-intg-${DRIVER_ID}-${VERSION}-aarch64.tar.gz"
tar czf "${ARTIFACT_NAME}" -C artifacts .

SIZE_MB=$(du -m "${ARTIFACT_NAME}" | cut -f1)
echo ""
echo "Build complete: ${ARTIFACT_NAME} (${SIZE_MB} MB)"
