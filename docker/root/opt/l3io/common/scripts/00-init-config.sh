#!/usr/bin/with-contenv bash

# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for
# details.
set -eo pipefail

# Setup the key environment variables
[ -z "${LLL_EX_PATH_DEFAULTS}" ] && export LLL_EX_PATH_DEFAULTS=/defaults
[ -z "${LLL_EX_PATH_SCRIPTS}" ] && export LLL_EX_PATH_SCRIPTS=/opt/l3io/init/scripts
[ -z "${LLL_EX_PATH_CONFIG}" ] && export LLL_EX_PATH_CONFIG=/opt/l3io/init/config
[ -z "${LLL_EX_PATH_COMMON_SCRIPTS}" ] && export LLL_EX_PATH_COMMON_SCRIPTS=/opt/l3io/common/scripts

set -u

# Load in the utils
source $LLL_EX_PATH_COMMON_SCRIPTS/00-utils

import_env_files_in_folder ${LLL_EX_PATH_DEFAULTS}

# Store the current path
pushd . &> /dev/null

execute_scripts_in_folder ${LLL_EX_PATH_COMMON_SCRIPTS} "-install-"
execute_scripts_in_folder ${LLL_EX_PATH_COMMON_SCRIPTS} "-config-"
execute_scripts_in_folder ${LLL_EX_PATH_SCRIPTS} 

# Execute cleanup
write_info "**** Cleaning up after install"
clean_app_package_manager
clean_tmp_cache

# Reset the working path
popd &> /dev/null

write_info "Done Setup...."

