#!/usr/bin/env bash

ACTION=${1:publish}

if [ -d dist ]; then
    rm -r dist
fi

python3 -m build

if [ "$ACTION" == "publish" ]; then
    python3 -m twine upload --repository pypi dist/*

    echo "Sleaping 30 secods to allow pypi enough time to process upload of new version"
    sleep 30s

    cd docker
    docker-compose build
    docker-compose push
    cd ..
fi
