#!/usr/bin/env bash

ACTION=${1:publish}

python3 -m build

if [ "$ACTION" == "publish" ]; then
    python3 -m twine upload --repository pypi dist/*

    cd docker
    docker build -f Dockerfile.test .
    cd ..
fi
