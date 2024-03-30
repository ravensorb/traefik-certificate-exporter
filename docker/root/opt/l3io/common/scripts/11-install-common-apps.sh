#!/bin/bash

# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for
# details.
set -eo pipefail

# Setup the key environment variables
[ -z "${LLL_EX_PATH_COMMON_SCRIPTS}" ] && export LLL_EX_PATH_COMMON_SCRIPTS=/opt/l3io/common/scripts

# Load in the utils
source $LLL_EX_PATH_COMMON_SCRIPTS/00-utils

####################################################################
# Allow newer LLL_EX_INSTALL_PACKAGES to include additional common
# packages that are not supported via the common package managers
####################################################################

#Split list of packages on delimiter '|'
IFS='|'
LLL_EX_INSTALL_PACKAGES=(${LLL_EX_INSTALL_PACKAGES})
for PKG in "${LLL_EX_INSTALL_PACKAGES[@]}"; do
    # [[ "${PKG,,}" == "crudini" ]] && LLL_EX_ENABLE_CRUDINI=1
    [[ "${PKG,,}" == "envsubst" ]] && LLL_EX_ENABLE_ENVSUBST=1
    [[ "${PKG,,}" == "yq" ]] && LLL_EX_ENABLE_YQ=1
done

####################################################################
# Install crudini
####################################################################

# if ! is_app_installed "crudini" "$LLL_EX_ENABLE_CRUDINI" "/usr/bin/crudini" "installed-crudini.txt"; then
#     write_info "Installing the latest version of crudini"

#     #install_app_package "curl" "curl" "curl"

#     download_github_latest_version "pixelb/crudini" "/usr/bin/crudini"

#     create_state_file "installed-crudini.txt"
# fi

####################################################################
# Install envsubst
####################################################################

if ! is_app_installed "envsubst" "$LLL_EX_ENABLE_ENVSUBST" "/usr/bin/envsubst" "installed-envsubst.txt"; then
    write_info "Installing the latest version of envsubst"

    #install_app_package "curl" "curl" "curl"

    # https://github.com/a8m/envsubst
    download_github_latest_version "a8m/envsubst" "/usr/bin/envsubst" `uname -s` `uname -m`

    create_state_file "installed-envsubst.txt"
fi

####################################################################
# Install yq
####################################################################

if ! is_app_installed "YQ" "$LLL_EX_ENABLE_YQ" "/usr/bin/yq" "installed-yq.txt"; then
    write_info "Installing the latest version of yq"

    #install_app_package "curl" "curl" "curl"

    # https://github.com/mikefarah/yq
    download_github_latest_version "mikefarah/yq" "/usr/bin/yq"

    create_state_file "installed-yq.txt"
fi
