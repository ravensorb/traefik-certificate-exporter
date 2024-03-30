#!/usr/bin/env bash

#############################################################################################################
[ -z "$DEBUG" ]                  && DEBUG=

[ -n "$ACTION" ]                 || ACTION=build

[ -z "$PACKAGE_VERSIONTAG" ]     && PACKAGE_VERSIONTAG=$(git describe --abbrev=0 --tags)
[ -z "$PACKAGE_REPO" ]           && PACKAGE_REPO="pypi"

[ -z "$SOURCE_TYPE" ]            && SOURCE_TYPE=git 
[ -z "$SOURCE_BRANCH" ]          && SOURCE_BRANCH=$(git symbolic-ref -q --short HEAD)  

[ -z "$GIT_SHA1" ]               && GIT_SHA1=$(git rev-parse -q HEAD)
[ -z "$GIT_SHA1_SHORT" ]         && GIT_SHA1_SHORT=$(git rev-parse --short HEAD)
[ -z "$GIT_VERSION" ]            && GIT_VERSION="$(git describe --long --tags)"

#############################################################################################################
# In case git isn't initialized
[ -z "$SOURCE_BRANCH" ]          && SOURCE_BRANCH="main"
[ -z "$PACKAGE_VERSIONTAG" ]     && PACKAGE_VERSIONTAG="0.0.1"
[ -z "$GIT_VERSION" ]            && GIT_VERSION="0.0.1"

#############################################################################################################
#############################################################################################################
function show_info() {
    echo "Package Build Script v1.0 (sanderson@eye-catcher.com)"
    echo 
}

function show_help() {
    # Display Help
    echo 
    echo "Syntax: build.sh [-h|a|r|v]"
    echo "options:"
    echo "  h   Display Help"
    echo "  a   Action (build, publish, docker)"

    echo "  r   Package repository name (pypi, test-pypi, ravenwolf)"
    echo "  v   Specify a Docker Version Tag (default: $PACKAGE_VERSIONTAG)"
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

function load_jenkins_vars()
{
    if [ -f "jenkins-vars.yml" ]; then
        write_info "Reading jenkins-vars.yml..."
        eval $(parse_yaml jenkins-vars.yml "jenkins_vars_")
        
        [[ -n "$jenkins_vars_release_tag" ]]                  && PACKAGE_VERSIONTAG=$jenkins_vars_release_tag
        [[ -n "$jenkins_vars_repo_vars__REPO" ]]              && PACKAGE_REPO=$jenkins_vars_repo_vars__REGISTRY
    fi
}

function load_env_vars()
{
    if [ -f ".env" ]; then
        write_error "Not implemented..."
    fi
}

#############################################################################################################
#############################################################################################################
show_info
load_jenkins_vars

while getopts "ha:r:v:" option; do
    case $option in 
        h) # Display help
            show_help
            exit;;
        a) # Set action
            ACTION=$OPTARG;;
        r) # Repo Name
            write_info "Setting custom repo name: $OPTARG"
            PACKAGE_REPO=$OPTARG;;
        v) # Version Tag
            write_info "Setting version tag: $OPTARG"
            PACKAGE_VERSIONTAG=$OPTARG;;
        \?) # Invalid Option
            #write_info "Error: Invalid Option"
            show_help
            exit;;
    esac
done

#############################################################################################################

write_info "Build Action: ${ACTION}"
write_info "Package Repo: ${PACKAGE_REPO}"
write_info "Version Tag: ${PACKAGE_VERSIONTAG}"

#############################################################################################################

if [[ "$ACTION" == *"build"* ]]; then
    if [ -d dist ]; then
        echo "Removing old builds"
        rm -r dist
    fi

    echo "Building Package"
    poetry build
fi

if [[ "$ACTION" == *"publish"* ]]; then
    echo "Publishing package"
    poetry publish -r $PACKAGE_REPO

    if [[ "$ACTION" == *"docker"* ]]; then
        echo "Sleaping 30 secods to allow $PACKAGE_REPO enough time to process upload of new version"
        sleep 30s
    fi
fi

if [[ "$ACTION" == *"docker"* ]]; then
    echo "Build and Publishing Docker Container"
    cd docker
    ./build.sh -a $ACTION-build
    cd ..
fi
