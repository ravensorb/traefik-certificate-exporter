#!/usr/bin/env bash

ACTION=${1:-}

if [ -d dist ]; then
    rm -r dist
fi

python3 -m build

if [ "$ACTION" == "publish" ]; then
    python3 -m twine upload --repository testpypi dist/*

    echo "Sleaping 30 secods to allow testpypi enough time to process upload of new version"
    sleep 30s

    cd docker
    ./build.sh $ACTION
fi
