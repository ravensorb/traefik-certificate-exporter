#!/bin/bash

# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for
# details.
set -eo pipefail

# Setup the key environment variables
[ -z "${LLL_EX_PATH_COMMON_SCRIPTS}" ] && export LLL_EX_PATH_COMMON_SCRIPTS=/opt/l3io/common/scripts
[ -z "${LLL_EX_UPGRADE_SYSTEM_PACKAGES}" ] && export LLL_EX_UPGRADE_SYSTEM_PACKAGES=false

# Load in the utils
source $LLL_EX_PATH_COMMON_SCRIPTS/00-utils

###############################################################
# Install system packages
##############################################################

function install_system_packages {
    # Exit if no installable packages are provided
    if [ -z ${LLL_EX_INSTALL_PACKAGES+x} ]; then
        write_debug "**** No system packages to install ****"
        return
    fi

    # Refresh the package manager cache for this platform
    #refresh_app_package_manager

    #Split list of packages on delimiter '|'
    IFS='|'
    LLL_EX_INSTALL_PACKAGES=(${LLL_EX_INSTALL_PACKAGES})
    for PKG in "${LLL_EX_INSTALL_PACKAGES[@]}"; do
        # Skip common apps (will be handled later)
        [[ ${PKG,,} =~ "crudini" || ${PKG,,} =~ "envsubst" || ${PKG,,} =~ "yq" ]] && continue

        write_info "Installing Package: ${PKG}"

        install_app_package $PKG $PKG
    done
}

###############################################################
# Install python 2.x packages
##############################################################

function install_python2_packages {
    # Exit if no installable packages are provided
    if [ -z ${LLL_EX_INSTALL_PIP2_PACKAGES+x} ]; then
        write_debug "**** No python 2.x packages to install ****"
        return
    fi

    if ! [ -x "$(command -v pip)" ]; then
        write_info "Installing pip" # should we just require this to be handeld by the system-packages install script
        install_app_package "pip2" "python-pip" "py2-pip"

        # Install/upgrade pip and related packages 
        install_pip_package "pip setuptools wheel" 2
    fi

    #Split list of packages on delimiter '|'
    IFS='|'
    LLL_EX_INSTALL_PIP2_PACKAGES=(${LLL_EX_INSTALL_PIP2_PACKAGES})
    for PKG in "${LLL_EX_INSTALL_PIP2_PACKAGES[@]}"; do
        write_info "Installing Python 2.x Package: ${PKG}"

        install_pip_package $PKG 2
    done

    # Install the basic requirements
    if ! check_exists_state_file "installed-requirements-pip2.txt"; then
        install_pip_requirements "${LLL_EX_PATH_CONFIG}/requirements-pip2.txt" 2

        create_state_file "installed-requirements-python2.txt"
    else
        write_info "Pip Requirements already installed"
    fi
}

###############################################################
# Install python 3.x packages
##############################################################

function install_python3_packages {
    # Exit if no installable packages are provided
    if [ -z ${LLL_EX_INSTALL_PIP3_PACKAGES+x} ]; then
        write_debug "**** No python 3.x packages to install ****"
        return
    fi

    if ! [ -x "$(command -v pip)" ]; then
        write_info "Installing pip" # should we just require this to be handeld by the system-packages install script
        install_app_package "pip3" "python3-pip" "py3-pip"

        # Install/upgrade pip and related packages 
        install_pip_package "pip setuptools wheel" 3
    fi

    #Split list of packages on delimiter '|'
    IFS='|'
    LLL_EX_INSTALL_PIP3_PACKAGES=(${LLL_EX_INSTALL_PIP3_PACKAGES})
    for PKG in "${LLL_EX_INSTALL_PIP3_PACKAGES[@]}"; do
        write_info "Installing Python 3.x Package: ${PKG}"

        install_pip_package $PKG 3
    done

    # Install the basic requirements
    if ! check_exists_state_file "installed-requirements-pip3.txt"; then
        install_pip_requirements "${LLL_EX_PATH_CONFIG}/requirements.txt" 3
    
        install_pip_requirements "${LLL_EX_PATH_CONFIG}/requirements-pip3.txt" 3

        create_state_file "installed-requirements-python3.txt"
    else
        write_info "Pip Requirements already installed"
    fi
}

[[ "${LLL_EX_UPGRADE_SYSTEM_PACKAGES,,}" = "true" || "${LLL_EX_UPGRADE_SYSTEM_PACKAGES}" == "1" ]] && upgrade_app_packages

install_system_packages
install_python2_packages
install_python3_packages