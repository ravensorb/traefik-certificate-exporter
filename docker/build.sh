#!/usr/bin/env bash

#############################################################################################################
[ -z "$DEBUG" ]                  && DEBUG=1

[ -n "$ACTION" ]                 || ACTION=build

[ -z "$DOCKER_IMAGENAME" ]       && DOCKER_IMAGENAME=traefik-certificate-exporter
[ -z "$DOCKER_REGISTRY" ]        && DOCKER_REGISTRY=gcr.ravenwolf.org
[ -z "$DOCKER_LIBRARY" ]         && DOCKER_LIBRARY=ravensorb

[ -z "$DOCKER_IMAGETAG" ]        && DOCKER_IMAGETAG=latest
[ -z "$DOCKER_VERSIONTAG" ]      && DOCKER_VERSIONTAG="$(git describe --abbrev=0 --tags)"

[ -z "$DOCKER_FILE" ]            && DOCKER_FILE=Dockerfile
[ -z "$DOCKER_MULTIARCH"]        && DOCKER_MULTIARCH=0

[ -z "$SOURCE_TYPE" ]            && SOURCE_TYPE=git 
[ -z "$SOURCE_BRANCH" ]          && SOURCE_BRANCH=$(git symbolic-ref -q --short HEAD)  

[ -z "$GIT_SHA1" ]               && GIT_SHA1=$(git rev-parse -q HEAD)
[ -z "$GIT_SHA1_SHORT" ]         && GIT_SHA1_SHORT=$(git rev-parse --short HEAD)
[ -z "$GIT_VERSION" ]            && GIT_VERSION="$(git describe --long --tags)"

#############################################################################################################
# In case git isn't initialized
[ -z "$SOURCE_BRANCH" ]          && SOURCE_BRANCH="main"
[ -z "$DOCKER_VERSIONTAG" ]      && DOCKER_VERSIONTAG="0.0.1"
[ -z "$GIT_VERSION" ]            && GIT_VERSION="0.0.1"

#############################################################################################################
#############################################################################################################
function show_info() {
    echo "Docker Build Script v1.0 (sanderson@eye-catcher.com)"
    echo 
}

function show_help() {
    # Display Help
    echo 
    echo "Syntax: docker-build.sh [-h|a|t|p|m]"
    echo "options:"
    echo "  h   Display Help"
    echo "  a   Action (build, publish, build-publish)"

    echo "  f   Docker file name for build (default $DOCKER_FILE)"
    echo "  t   Specify a Docker Image Tag  (default: $DOCKER_IMAGETAG)"
    echo "  v   Specify a Docker Version Tag (default: $DOCKER_VERSIONTAG)"
    echo "  m   Enable docker multi-arch build"
}

function write_info() {
    echo "$@"
}

function write_error() {
    echo "[ERROR] $@" >&2
}

function write_debug() {
    if [ -n "$DEBUG" ]; then
        echo "[DEBUG] " $@
    fi
}

function parse_yaml {
   local prefix=$2
   local s='[[:space:]\-]*' w='[a-zA-Z0-9_\-]*' fs=$(echo @|tr @ '\034')
   sed -ne "s|^\($s\):|\1|" \
        -e "s|^\($s\)\($w\)$s[:=]$s[\"']\(.*\)[\"']$s\$|\1$fs\2$fs\3|p" \
        -e "s|^\($s\)\($w\)$s[:=]$s\(.*\)$s\$|\1$fs\2$fs\3|p"  $1 |
   awk -F$fs '{
      indent = length($1)/2;
      vname[indent] = $2;
      for (i in vname) {if (i > indent) {delete vname[i]}}
      if (length($3) > 0) {
         vn=""; for (i=0; i<indent; i++) {vn=(vn)(vname[i])("_")}
         printf("export %s%s%s=\"%s\"\n", "'$prefix'",vn, $2, $3);
      }
   }'
}

function load_jenkins_vars
{
    if [ -f "jenkins-vars.yml" ]; then
        write_info "Reading jenkins-vars.yml..."
        eval $(parse_yaml jenkins-vars.yml "jenkins_vars_")
        
        [[ -n "$jenkins_vars_release_tag" ]]                  && DOCKER_IMAGETAG=$jenkins_vars_release_tag
        [[ -n "$jenkins_vars_repo_vars__REGISTRY" ]]          && DOCKER_REGISTRY=$jenkins_vars_repo_vars__REGISTRY
        [[ -n "$jenkins_vars_repo_vars__CONTAINER_NAME" ]]    && DOCKER_IMAGENAME=$jenkins_vars_repo_vars__CONTAINER_NAME
        [[ -n "$jenkins_vars_repo_vars__MULTIARCH" ]]         && DOCKER_MULTIARCH=$jenkins_vars_repo_vars__MULTIARCH
        [[ -n "$jenkins_vars_repo_vars__LS_USER" ]]           && DOCKER_LIBRARY=$jenkins_vars_repo_vars__LS_USER
    fi
}

function load_env_vars
{
    set +e 
    set -o allexport

    write_info "Loading env vars..."

    envFiles=(".env" ".env.$DOCKER_IMAGENAME" ".pipeline.env" ".pipeline.env.$DOCKER_IMAGENAME" )

    for envFile in ${envFiles[@]}
    do
        if [ -f "$envFile" ]; then
            write_info "  from: $envFile..."
            source $envFile
        fi
    done

    write_info ""

    set +o allexport
    set -e 
}


#############################################################################################################
#############################################################################################################
show_info
load_jenkins_vars
load_env_vars

write_debug "Handling command line options..."

while getopts "ha:i:r:u:f:t:p:v:m" option; do
    case $option in 
        h) # Display help
            show_help
            exit;;
        a) # Set action
            ACTION=$OPTARG;;
        i) # Docker Image Name
            write_info "Setting custom image name: $OPTARG"
            DOCKER_IMAGENAME=$OPTARG;;
        r) # Docker Repo Name
            write_info "Setting custom repo name: $OPTARG"
            DOCKER_LIBRARY=$OPTARG;;
        u) # Docker Registry Base URL
            write_info "Setting custom registry name: $OPTARG"
            DOCKER_REGISTRY=$OPTARG;;
        f) # Docker File Name
            write_info "Setting custom docker file: $OPTARG"
            DOCKER_FILE=$OPTARG;;
        t) # Docker Image Tag
            write_info "Setting custom docker image tag: $OPTARG"
            DOCKER_IMAGETAG=$OPTARG;;
        v) # Docker Version Tag
            write_info "Setting docker version tag: $OPTARG"
            VERSION=$OPTARG;;

        m) # Docker Multi-arch build
            write_info "Setting docker multi arch build"
            DOCKER_MULTIARCH=1;;
        \?) # Invalid Option
            #write_info "Error: Invalid Option"
            show_help
            exit;;
    esac
done

#############################################################################################################
#############################################################################################################

write_info "Active settings:"
write_info "  Docker Action      : ${ACTION}"

write_info "  Docker Image Tag   : ${DOCKER_IMAGETAG}"
write_info "  Docker Version Tag : ${DOCKER_VERSIONTAG}"
write_info "  Docker Multiarch   : ${DOCKER_MULTIARCH}"
write_info "  Git Branch         : ${SOURCE_BRANCH}"
write_info "  Git Version        : ${GIT_VERSION}"
write_info "  Git SHA1           : ${GIT_SHA1_SHORT}"
write_info ""

#############################################################################################################

function docker_build()
{
    local docker_file=$1
    local docker_context=$2
    local image_name=$3
    local image_tag=$4
    local image_tag_version=$5
    local image_tag_sha1=$6
    local image_registry=$7

    shift 7
    local env_files=($@)
    local build_args=()
    
    [[ "$DOCKER_MULTIARCH" == "1" || "$DOCKER_MULTIARCH" == "true" ]] && build_mode="buildx build --load " || build_mode="build"
    #build_mode="build"

    local build_args_file=".build.args.tmp"

    [[ -f $build_args_file ]] && rm -f $build_args_file 2>/dev/null
    for i in "${env_files[@]}"
    do
        if [ -f "$i" ]; then
            sed -e '/^[[:space:]]*$/d' -e '/[#]/d' -e 's/\(^[^=]*\)=\(.*\)/--build-arg \1=\2/' -e 's/\"\"/\"/g' $i >> $build_args_file
            echo "" >> .build.args.tmp
            # build_args+=("-f $i")
        fi
    done

    if [[ -f $build_args_file ]]; then
        write_debug "Reading build args from $build_args_file..."
        readarray -t build_args_array < $build_args_file
        build_args=$(printf " %s" "${build_args_array[@]}")
        rm -f $build_args_file 2>/dev/null
        # write_debug "Build Args: ${build_args}"
    fi

    [ -n "$image_registry" ] && image_name_full=$image_registry/$image_name || image_name_full=$image_name

    write_info "Building Image: $image_name_full"

    tar -czh $docker_context |  docker \
        $build_mode \
        --network host \
        --no-cache \
        --force-rm \
        ${DEBUG:+--progress plain} \
        --build-arg SOURCE_COMMIT=$GIT_SHA1 \
        --build-arg SOURCE_TYPE=$SOURCE_TYPE ${build_args} \
        ${image_tag_version:+--build-arg VERSION=$image_tag_version} \
        ${docker_file:+--file $docker_file} \
        --tag $image_name_full \
        ${image_tag:+--tag $image_name_full:$image_tag} \
        ${image_tag_version:+--tag $image_name_full:$image_tag_version} \
        ${image_tag_sha1:+--tag $image_name_full:$image_tag_sha1} \
        -
}

function docker_publish()
{
    local image_name=$1
    local image_tag=$2
    local image_tag_version=$3
    local image_tag_commit_sha=$4
    local image_registry=$5

    write_info "Publishing Image: $image_name"

    [ -n "$image_registry" ] && image_name_full=$image_registry/$image_name || image_name_full=$image_name

    tagCount=0
    [ -n "$image_tag" ] && { ((tagCount+=1)); write_info "Pushing image tag"; docker push $image_name_full:$image_tag; }
    [ -n "$image_tag_version" ] && { ((tagCount+=1)); write_info "Pushing version tag"; docker push $image_name_full:$image_tag_version; }
    [ -n "$image_tag_commit_sha" ] && { ((tagCount+=1)); write_info "Pushing commit sha tag"; docker push $image_name_full:$image_tag_commit_sha; }
    [[ $tagCount > 0 ]] && { write_info "Pushing all tags"; docker push $image_name_full --all-tags; }

    if [[ -f "README.MD" || -f "README.md" ]]; then
        pushrm_provider="--provider dockerhub"

        [[ $image_registry == *"harbor"* ]] && pushrm_provider="--provider harbor2"
        [[ $image_registry == *"quay"* ]] && pushrm_provider="--provider quay"

        write_info "Publishing Image Readme"
        docker pushrm $image_name_full:$image_tag $pushrm_provider
    fi
}

#############################################################################################################

if [[ -f "mount-common.sh" ]]; then
    ./mount-common.sh
fi 

if [[ "$ACTION" == "dump-env" ]]; then
    env | sort
    exit 0
fi

if [[ "$ACTION" == *"build"* ]]; then
    docker_build \
        "${DOCKERFILE}" \
        "." \
        "${DOCKER_IMAGENAME}" \
        "${DOCKER_IMAGETAG}" \
        "$DOCKER_VERSIONTAG" \
        "$GIT_SHA1_SHORT" \
        "${DOCKER_REGISTRY}/${DOCKER_LIBRARY}" \
        ".env" \
        ".env.${DOCKER_IMAGENAME}" \
        ".pipeline.env.${DOCKER_IMAGENAME}" 
fi

if [[ "$ACTION" == *"publish"* ]]; then

    docker_publish \
        "${DOCKER_IMAGENAME}" \
        "${DOCKER_IMAGETAG}" \
        "${DOCKER_VERSIONTAG}" \
        "${GIT_SHA1_SHORT}" \
        "${DOCKER_REGISTRY}/${DOCKER_LIBRARY}"
fi

if [[ "$ACTION" == *"remove"* ]]; then
    write_info "Removing Container"
    docker rm -f ${DOCKER_IMAGENAME}-debug
fi

if [[ "$ACTION" == *"run"* ]]; then
    write_info "Running Container"

    dockerArgsEnvFiles=()
    [[ -f ".env" ]] && dockerArgsEnvFiles+=("-e .env")
    [[ -f ".env.${DOCKER_IMAGENAME}" ]] && dockerArgsEnvFiles+=("-e .env.${DOCKER_IMAGENAME}")

    docker run \
            -d \
            --rm ${dockerArgsEnvFiles[@]} \
            -v ${PWD}/data/data:/data:ro \
            -v ${PWD}/data/certs:/certs:rw \
            -v ${PWD}/data/config:/config:rw \
            -v /var/run/docker.sock:/var/run/docker.sock:ro \
            --name ${DOCKER_IMAGENAME}-debug \
            ${DOCKER_REGISTRY}/${DOCKER_LIBRARY}/${DOCKER_IMAGENAME}:${DOCKER_IMAGETAG} 
fi 

if [[ "$ACTION" == *"logs"* ]]; then
    write_info "Displaying logs for the container"
    docker logs -f ${DOCKER_IMAGENAME}-debug
fi 

if [[ "$ACTION" == *"shell"* ]]; then
    docker exec -it ${DOCKER_IMAGENAME}-debug /bin/bash
fi

#############################################################################################################
