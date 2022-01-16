#!/usr/bin/env bash

ACTION=${1:-test}

if [ -d data ]; then
    sudo rm -r data
fi

[[ "$ACTION" != *"test"* ]] || TEST_VERSION=1

[ -n "$DOCKER_REPO" ]    || DOCKER_REPO="ravensorb/"
[ -n "$SOURCE_BRANCH" ]  || SOURCE_BRANCH=$(git symbolic-ref -q --short HEAD)  
[ -n "$GIT_SHA1" ]       || GIT_SHA1=$(git rev-parse -q HEAD)
[ -n "$VERSION" ]        || VERSION=$(git describe --long)

[ -n "$SOURCE_TYPE" ]        || SOURCE_TYPE=git 
[ -n "$DOCKERFILE" ]         || DOCKERFILE=Dockerfile
[ -n "$DOCKERFILE_PATH" ]    || DOCKERFILE_PATH=.
[ -n "$IMAGE_NAME" ]         || IMAGE_NAME=${DOCKER_REPO}traefik-certificate-exporter

docker build \
    -f $DOCKERFILE \
    --rm \
    --build-arg BUILD_DATE=`date -u +"%Y-%m-%dT%H:%M:%SZ"` \
    --build-arg "SOURCE_COMMIT=$GIT_SHA1" \
    --build-arg "SOURCE_TYPE=$SOURCE_TYPE" \
    ${TEST_VERSION:+--build-arg "TEST_VERSION=1"} \
    ${VERSION:+--build-arg "VERSION=$VERSION"} \
    -t $IMAGE_NAME:${VERSION} \
    -t $IMAGE_NAME:latest . 

if [[ "$ACTION" == *"test"* ]]; then
    docker run \
            --rm \
            -v ${PWD}/data/data:/data:ro \
            -v ${PWD}/data/certs:/certs:rw \
            -v ${PWD}/data/config:/config:rw \
            -v /var/run/docker.sock:/var/run/docker.sock:ro \
            $IMAGE_NAME:latest 
fi

if [[ "$ACTION" == *"publish"* ]]; then
    docker push $IMAGE_NAME:latest
    docker push $IMAGE_NAME:${VERSION}
fi