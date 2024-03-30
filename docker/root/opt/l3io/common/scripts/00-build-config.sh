#!/bin/bash

# Bash "strict mode", to help catch problems and bugs in the shell
# script. Every bash script you write should include this. See
# http://redsymbol.net/articles/unofficial-bash-strict-mode/ for
# details.
set -eo pipefail

# Setup the key environment variables
[ -z "${LLL_EX_PATH_SCRIPTS}" ] && export LLL_EX_PATH_SCRIPTS=/opt/l3io/build/scripts
[ -z "${LLL_EX_PATH_CONFIG}" ] && export LLL_EX_PATH_CONFIG=/opt/l3io/build/config
[ -z "${LLL_EX_PATH_COMMON_SCRIPTS}" ] && export LLL_EX_PATH_COMMON_SCRIPTS=/opt/l3io/common/scripts

set -u

# Load in the utils
source $LLL_EX_PATH_COMMON_SCRIPTS/00-utils

# Store the current path
pushd . &> /dev/null

# write_debug "**** Executing Common Scripts: ${LLL_EX_PATH_COMMON_SCRIPTS}"
execute_scripts_in_folder ${LLL_EX_PATH_COMMON_SCRIPTS} "-install-"
execute_scripts_in_folder ${LLL_EX_PATH_COMMON_SCRIPTS} "-config-"
write_info "**** Executing Apps Scripts: ${LLL_EX_PATH_SCRIPTS}"
execute_scripts_in_folder ${LLL_EX_PATH_SCRIPTS} 

if [[ -d ${LLL_EX_PATH_COMMON_SCRIPTS} && -f $LLL_EX_PATH_COMMON_SCRIPTS/00-init-config.sh ]]; then
    if [ -d /etc/cont-init.d ]; then
        write_info "s-6 overlay detected (v2 - legacy)"
        if ! [ -f /etc/cont-init.d/90-init-config.sh ]; then
            write_info "Copying init script in place..."
            cp -v ${LLL_EX_PATH_COMMON_SCRIPTS}/00-init-config.sh /etc/cont-init.d/90-init-config.sh
            chmod +x /etc/cont-init.d/90-init-config.sh
            chown ${PUID:-abc}:${PGID:-abc} /etc/cont-init.d/90-init-config.sh
        fi
    elif [ -d /etc/s6-overlay/s6-rc.d ]; then
        write_info "s-6 overlay detected (v3)"
        if ! [ -f /etc/s6-overlay/s6-rc.d/init-ravensorb/run ]; then
            mkdir -p /etc/s6-overlay/s6-rc.d/init-ravensorb/dependencies.d
            write_info "Copying init script in place..."

            cp -v ${LLL_EX_PATH_COMMON_SCRIPTS}/00-init-config.sh /etc/s6-overlay/s6-rc.d/init-ravensorb/run 
            chmod +x /etc/s6-overlay/s6-rc.d/init-ravensorb/run          

            echo oneshot > /etc/s6-overlay/s6-rc.d/init-ravensorb/type
            echo /etc/s6-overlay/s6-rc.d/init-ravensorb/run > /etc/s6-overlay/s6-rc.d/init-ravensorb/up
            touch /etc/s6-overlay/s6-rc.d/init-ravensorb/dependencies.d/legacy-services  
            touch /etc/s6-overlay/s6-rc.d/user2/contents.d/init-ravensorb
        fi
    else
        write_info "***************************************************************"
        write_info "***************************************************************"
        write_info "*********** UNABLE TO SETUP INIT-CONFIG.SH SCRIPT *************"
        write_info "***************************************************************"
        write_info "MAY NEED TO EXTEND ENTRY POINT, RUN, or CMD in docker-compose"
        write_info "***************************************************************"
        write_info "***************************************************************"
        # write_info "****** COPYING 00-init-config.sh TO INIT FOLDER *******"
        # cp -v ${LLL_EX_PATH_SCRIPTS}/00-init-config.sh ${LLL_EX_PATH_BASE}/init/scripts/00-init-config.sh || true
        # chmod +x ${LLL_EX_PATH_SCRIPTS}/00-init-config.sh || true        
    fi
fi

# Execute cleanup
write_info "**** Cleaning up after install"
clean_app_package_manager
clean_tmp_cache

# Reset the working path
popd &> /dev/null

write_info "Done Setup...."

