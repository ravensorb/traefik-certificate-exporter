# shellcheck shell=bash
#
# The container's privilege decision (ADR-0030, amended 2026-10-10 for BL-E013-041).
#
# Sourced by init-traefik-certificate-exporter-config/run, never executed, and never an s6
# service. It lives in its own file so the decision itself can be executed by the test suite
# (tests/test_s6_privilege_drop.py) with a stub `s6-setuidgid` on PATH, instead of being
# asserted only by grepping the init script.
#
# The rule: the service drops to the PUID/PGID account ONLY when that account is proven able
# to do the job -- every ACME store file the application will read is readable by it, and the
# output path is writable by it. Anything unproven keeps root and says why in ONE WARNING.
# Traefik writes acme.json mode 0600 owned by the user it runs as and refuses to start if it
# is any more open, so "relax the permissions" is never a remedy this file may offer.
#
# Every probe runs AS the service account through `s6-setuidgid`: a `[ -r ]` evaluated as
# root would succeed for every file and prove nothing.
#
# Nothing here sets shell options (`set -e`/`-u`, `shopt`) -- the caller's shell is left as it
# was found.

# The remedy shared by every "the account cannot do the job" reason (decision rows 3-6).
_tce_unprivileged_remedy() {
    printf '%s' "To run unprivileged: run Traefik as a non-root user, set PUID/PGID to" \
        " that user's uid/gid, and keep settings.outputpath writable by it;" \
        " settings.restartcontainers still forces root. See docs/operational.md."
}

# Decision row 1's WARNING: <user> <why the settings count as unresolved>.
_tce_unresolved_warning() {
    echo "WARNING: running as root because the container could not resolve settings" \
         "($2), so it cannot prove the ACME store is readable by $1." \
         "Check /config/config.yaml and the TRAEFIK_CERTIFICATE_EXPORTER_* environment;" \
         "settings.datapath and settings.outputpath must be absolute paths." >&2
}

# True when <user> can write <path>, or owns it on a writable filesystem (an owner can chmod
# it back to writable). The plain `[ -w ]` here runs as the caller (root) on purpose: it is
# false only on a read-only mount, where ownership gives the account no lever.
_tce_user_controls() {
    s6-setuidgid "$1" test -w "$2" > /dev/null 2>&1 && return 0
    [ -w "$2" ] && s6-setuidgid "$1" test -O "$2" > /dev/null 2>&1
}

# tce_privilege_decision <resolved-settings-file> <service-user>
#
# stdout: exactly one line, `true` (keep root) or `false` (drop to <service-user>).
# stderr: on `true`, one `WARNING: running as root ...` line, plus at most one line saying the
#         ACME store is writable by <service-user>; on `false`, nothing, or one `INFO:` line
#         saying so.
# Always returns 0. The caller treats anything but `true`/`false` on stdout as `true`.
#
# Resolved-settings file layout (written by the init script's embedded resolver):
#   1 restartcontainers (true|false)  2 outputPath  3 dataPath  4 fileSpec
#   5.. one absolute path per file matching fileSpec under dataPath (Python glob.glob)
tce_privilege_decision() {
    local resolved="$1" user="$2"
    local -a lines=()
    local line restart outputPath dataPath fileSpec path
    local -a matches=() unreadable=() controlled=()
    local warning="" note="" quoted

    # One loop both counts and collects; `|| [ -n "$line" ]` keeps a last line that has no
    # trailing newline.
    if [ -n "${resolved}" ] && [ -f "${resolved}" ] && [ -r "${resolved}" ]; then
        while IFS= read -r line || [ -n "${line}" ]; do
            lines+=("${line}")
        done < "${resolved}"
    fi

    restart="${lines[0]-}"
    outputPath="${lines[1]-}"
    dataPath="${lines[2]-}"
    fileSpec="${lines[3]-}"
    if [ "${#lines[@]}" -gt 4 ]; then
        matches=("${lines[@]:4}")
    fi

    # Row 1: nothing proven -- the settings could not be resolved at all.
    if [ "${#lines[@]}" -lt 4 ] || { [ "${restart}" != "true" ] && [ "${restart}" != "false" ]; }; then
        _tce_unresolved_warning "${user}" "the resolved settings are missing or malformed"
        echo true
        return 0
    fi

    # Row 2: the Docker-socket restart path needs root regardless of the store.
    if [ "${restart}" = "true" ]; then
        echo "WARNING: running as root because settings.restartcontainers is enabled," \
             "which requires Docker socket access. Disable settings.restartcontainers to" \
             "run as the unprivileged PUID/PGID account (${user}), or put an endpoint-restricted" \
             "docker-socket proxy in front of the socket (see docs/operational.md)." >&2
        echo true
        return 0
    fi

    # Row 1, continued: a relative path cannot be probed reliably here -- the service runs
    # from s6's service directory, not from this script's cwd -- so it counts as unresolved.
    local unresolved=""
    if [ -n "${dataPath}" ] && [ "${dataPath#/}" = "${dataPath}" ]; then
        unresolved="settings.datapath '${dataPath}' is not an absolute path"
    elif [ -n "${outputPath}" ] && [ "${outputPath#/}" = "${outputPath}" ]; then
        unresolved="settings.outputpath '${outputPath}' is not an absolute path"
    else
        for path in "${matches[@]}"; do
            if [ "${path#/}" = "${path}" ]; then
                unresolved="a matched ACME store path is not absolute"
                break
            fi
        done
    fi
    if [ -n "${unresolved}" ]; then
        _tce_unresolved_warning "${user}" "${unresolved}"
        echo true
        return 0
    fi

    # The writable-store note (orthogonal to the rows): an account that can rewrite the store
    # can also make the NEXT start keep root, so unprivileged mode needs /data mounted :ro.
    if [ -n "${dataPath}" ] && [ -d "${dataPath}" ] && _tce_user_controls "${user}" "${dataPath}"; then
        controlled+=("'${dataPath}'")
    fi
    for path in "${matches[@]}"; do
        if _tce_user_controls "${user}" "${path}"; then
            controlled+=("'${path}'")
        fi
    done
    if [ "${#controlled[@]}" -gt 0 ]; then
        note="The ACME store is writable by ${user} (${controlled[*]}): unprivileged mode"
        note="${note} requires mounting /data read-only (:ro), or a compromised ${user} can"
        note="${note} force root on the next start."
    fi

    # Row 3: the application globs and watches dataPath, so it must be listable (r and x).
    if [ -z "${dataPath}" ] || [ ! -d "${dataPath}" ] \
        || ! s6-setuidgid "${user}" test -r "${dataPath}" > /dev/null 2>&1 \
        || ! s6-setuidgid "${user}" test -x "${dataPath}" > /dev/null 2>&1; then
        warning="WARNING: running as root because ${user} cannot list settings.datapath"
        warning="${warning} '${dataPath}' (it does not exist, is not a directory, or is not"
        warning="${warning} readable and searchable by that account), so the ACME store"
        warning="${warning} cannot be proven readable. $(_tce_unprivileged_remedy)"
    # Row 4: nothing to prove readable yet.
    elif [ "${#matches[@]}" -eq 0 ]; then
        warning="WARNING: running as root because no file matches '${fileSpec}' under"
        warning="${warning} '${dataPath}' yet, so the ACME store cannot be proven readable"
        warning="${warning} by ${user}. Restart the container once Traefik has written it."
        warning="${warning} $(_tce_unprivileged_remedy)"
    else
        # Row 5: one probe per matched file (paths come from lines, never word-split).
        for path in "${matches[@]}"; do
            if ! s6-setuidgid "${user}" test -r "${path}" > /dev/null 2>&1; then
                unreadable+=("'${path}'")
            fi
        done
        if [ "${#unreadable[@]}" -gt 0 ]; then
            quoted="${unreadable[*]}"
            warning="WARNING: running as root because these ACME store files are not readable"
            warning="${warning} by ${user}: ${quoted}. Traefik enforces mode 0600 owned by the"
            warning="${warning} user it runs as, so the store cannot be opened up for another"
            warning="${warning} account. $(_tce_unprivileged_remedy)"
        fi
    fi

    if [ -n "${warning}" ]; then
        echo "${warning}" >&2
        [ -z "${note}" ] || echo "${note}" >&2
        echo true
        return 0
    fi

    # Row 7 (row 6 is the caller's, after it takes ownership of the output path).
    [ -z "${note}" ] || echo "INFO: ${note}" >&2
    echo false
    return 0
}

# tce_output_writable <output-path> <service-user>
#
# Decision row 6, run by init AFTER it has taken ownership of the output path: returns 0 when
# <service-user> can write <output-path>; otherwise prints the root WARNING to stderr and
# returns 1, and the caller keeps root.
tce_output_writable() {
    local outputPath="$1" user="$2"

    if [ -n "${outputPath}" ] && s6-setuidgid "${user}" test -w "${outputPath}" > /dev/null 2>&1; then
        return 0
    fi

    echo "WARNING: running as root because ${user} cannot write settings.outputpath" \
         "'${outputPath}' even after the container took ownership of it (read-only mount," \
         "root-squashed network share, or a missing directory)." \
         "$(_tce_unprivileged_remedy)" >&2
    return 1
}
