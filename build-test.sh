#!/usr/bin/env bash

ACTION=${1:-}

rm -r dist

python3 -m build

if [ "$ACTION" == "publish" ]; then
    python3 -m twine upload --repository testpypi dist/*

    cd docker
    docker build -f Dockerfile.test . --build-arg TEST_VERSION=1 --no-cache
    cd ..
fi
