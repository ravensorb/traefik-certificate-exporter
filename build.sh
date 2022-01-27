#!/usr/bin/env bash

ACTION=${1:-build}

PYPI_INDEX=pypi
[[ "$ACTION" != *"test"* ]] || PYPI_INDEX=testpypi

echo "Python Action: ${ACTION}"
echo "PyPi Index: ${PYPI_INDEX}"

if [[ "$ACTION" == *"build"* ]]; then
    if [ -d dist ]; then
        echo "Removing old builds"
        rm -r dist
    fi

    echo "Building Package"
    python3 -m build
fi

if [[ "$ACTION" == *"publish"* ]]; then
    echo "Publishing python package"
    python3 -m twine upload --repository $PYPI_INDEX dist/*

    if [[ "$ACTION" == *"docker"* ]]; then
        echo "Sleaping 30 secods to allow $PYPI_INDEX enough time to process upload of new version"
        sleep 30s
    fi
fi

if [[ "$ACTION" == *"docker"* ]]; then
    echo "Build and Publishing Docker Container"
    cd docker
    ./build.sh $ACTION-build
    cd ..
fi
