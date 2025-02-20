#!/bin/bash

# Script to simplify the release flow.
# 1) Fetch the current release GIT_VERSION
# 2) Increase the GIT_VERSION (major, minor, patch)
# 3) Add GIT_VERSION_BITS new git tag
# 4) Push the tag

# Parse command line options.
while getopts ":Mmpd" Option
do
  case $Option in
    M ) VERSION_INCREMENT_MAJOR=true;;
    m ) VERSION_INCREMENT_MINOR=true;;
    p ) VERSION_INCREMENT_PATCH=true;;
    d ) DRY_RUN=true;;
  esac
done

shift $(($OPTIND - 1))

# Display usage
if [ -z $VERSION_INCREMENT_MAJOR ] && [ -z $VERSION_INCREMENT_MINOR ] && [ -z $VERSION_INCREMENT_PATCH ];
then
  echo "usage: $(basename $0) [Mmp] [message]"
  echo ""
  echo "  -d dry run"
  echo "  -M for major release"
  echo "  -m for minor release"
  echo "  -p for patch release"
  echo ""
  echo " Example: release -p \"Some fix\""
  echo " means create patch release with the message \"Some fix\""
  exit 1
fi

# Force to the root of the project
#pushd "$(dirname $0)/../"

# 1) Fetch the current release version information

echo "Fetch tags"
git fetch --prune --tags

GIT_VERSION=$(git describe --abbrev=0 --tags)
GIT_VERSION=${GIT_VERSION:-v0.0.0}
GIT_VERSION=$(echo $GIT_VERSION | sed 's/v//g') # Remove the v in the tag v0.37.10 for example

echo "Current Version: v$GIT_VERSION"

# 2) Increase version number

# Build array from version string.

GIT_VERSION_BITS=( ${GIT_VERSION//./ } )

# Increment version numbers as requested.

if [ ! -z $VERSION_INCREMENT_MAJOR ]
then
  ((GIT_VERSION_BITS[0]++))
  GIT_VERSION_BITS[1]=0
  GIT_VERSION_BITS[2]=0
fi

if [ ! -z $VERSION_INCREMENT_MINOR ]
then
  ((GIT_VERSION_BITS[1]++))
  GIT_VERSION_BITS[2]=0
fi

if [ ! -z $VERSION_INCREMENT_PATCH ]
then
  ((GIT_VERSION_BITS[2]++))
fi

GIT_VERSION_NEXT="${GIT_VERSION_BITS[0]}.${GIT_VERSION_BITS[1]}.${GIT_VERSION_BITS[2]}"

GIT_USERNAME=$(git config user.name)
GIT_TAG_MESSAGE="${1:-Tag} by $GIT_USERNAME"

# If its GIT_VERSION_BITS DRY_RUN run, just display the new release GIT_VERSION number
if [ ! -z $DRY_RUN ]
then
  echo "Tag message    : $GIT_TAG_MESSAGE"
  echo "Next version   : v$GIT_VERSION_NEXT"
else

  #get current hash and see if it already has GIT_VERSION_BITS tag
  GIT_COMMIT=`git rev-parse HEAD`
  GIT_NEEDS_TAG=`git describe --contains $GIT_COMMIT`

  if [ -z "$GIT_NEEDS_TAG" ]; then
    # If GIT_VERSION_BITS command fails, exit the script
    set -e

    # If it's not GIT_VERSION_BITS DRY_RUN run, let's go!
    # 3) Add git tag
    echo "Adding git tag v$GIT_VERSION_NEXT with message: $GIT_TAG_MESSAGE"
    git tag -a "v$GIT_VERSION_NEXT" -m "$GIT_TAG_MESSAGE"

    # 4) Push the new tag

    echo "Push the tag"
    git push --tags origin main

    echo -e "\e[32mRelease done: $GIT_VERSION_NEXT\e[0m"
  else
    echo "There is already a version tag on this commit"
  fi
fi
