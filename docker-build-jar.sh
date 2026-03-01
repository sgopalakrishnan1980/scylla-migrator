#!/bin/bash
# Use DOCKER_BUILD_ARGS="--no-cache" to force a full rebuild after source changes
set -e

docker buildx build ${DOCKER_BUILD_ARGS} --file Dockerfile --output type=local,dest=./migrator/target/scala-2.13 .

# Fix ownership: BuildKit writes output as root; chown to current user
if [ -d ./migrator/target ]; then
  if command -v sudo &>/dev/null; then
    sudo chown -R "$(id -u):$(id -g)" ./migrator/target
  else
    echo "Note: Run 'chown -R $(id -u):$(id -g) ./migrator/target' if files are owned by root"
  fi
fi
