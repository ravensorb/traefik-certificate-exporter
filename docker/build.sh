#!/usr/bin/env bash

ACTION=${1:-}

if [ -d data ]; then
    sudo rm -r data
fi

[ -n "$SOURCE_BRANCH" ]  || SOURCE_BRANCH=$(git symbolic-ref -q --short HEAD)  
[ -n "$GIT_SHA1" ]       || GIT_SHA1=$(git rev-parse -q HEAD)
[ -n "$VERSION" ]        || VERSION=$(git describe --long)

[ -n "$SOURCE_TYPE" ]        || SOURCE_TYPE=git 
[ -n "$DOCKERFILE" ]         || DOCKERFILE=Dockerfile
[ -n "$DOCKERFILE_PATH" ]    || DOCKERFILE_PATH=.
[ -n "$IMAGE_NAME" ]         || IMAGE_NAME=traefik-certificate-exporter

if [ "$SOURCE_BRANCH" != "release" ]; then
    DOCKERFILE=Dockerfile.text
fi

docker build \
    -f $DOCKERFILE \
    --build-arg BUILD_DATE=`date -u +"%Y-%m-%dT%H:%M:%SZ"` \
    --build-arg "SOURCE_COMMIT=$GIT_SHA1" \
    --build-arg "SOURCE_TYPE=$SOURCE_TYPE" \
    ${VERSION:+--build-arg "VERSION=$VERSION"} \
    -t $IMAGE_NAME:${VERSION} \
    -t $IMAGE_NAME:latest . 

if [ "$ACTION" == "publish" ]; then
    docker push
fi
