#!/usr/bin/env bash

ACTION=${1}

PYPI_INDEX=pypi
[[ "$ACTION" != *"test"* ]] || PYPI_INDEX=testpypi

if [ -d dist ]; then
    rm -r dist
fi

python3 -m build

if [ "$ACTION" == *"publish"* ]; then
    python3 -m twine upload --repository $PYPI_INDEX dist/*

    echo "Sleaping 30 secods to allow $PYPI_INDEX enough time to process upload of new version"
    sleep 30s

    cd docker
    ./build.sh $ACTION
    cd ..
fi
