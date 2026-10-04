#!/usr/bin/env sh
# Shared secret and .env management for the WristMind installer.
#
# This file is sourced, not executed. It knows how to:
#   - detect whether an install already has an .env
#   - create server/.env from server/.env.production.example with fresh secrets
#   - read and safely update single values in an existing .env
#
# POSIX sh. The only dependency is openssl.

WM_PLACEHOLDER="generate-a-long-random-value"
# Safe fallback when a fixed separator cannot be extracted from the template.
WM_CORS_DEFAULT='["http://localhost:3000","http://127.0.0.1:3000"]'

# wm_env_file <server_dir>
wm_env_file() {
    printf '%s\n' "${1:?server_dir}/.env"
}

wm_env_exists() {
    [ -f "$(wm_env_file "${1:?server_dir}")" ]
}

# True when .env still contains the template placeholder, i.e. is unusable.
wm_env_is_template() {
    _wm_f="$(wm_env_file "${1:?server_dir}")"
    [ -f "$_wm_f" ] || return 1
    grep -q "^POSTGRES_PASSWORD=${WM_PLACEHOLDER}$" "$_wm_f"
}

# wm_env_get <server_dir> <KEY>
wm_env_get() {
    _wm_f="$(wm_env_file "${1:?server_dir}")"
    _wm_key="${2:?key}"
    [ -f "$_wm_f" ] || return 0
    sed -n "s/^${_wm_key}=//p" "$_wm_f" | head -n 1
}

# wm_env_set <server_dir> <KEY> <value> — append when absent, replace when present.
# The separator is read from the template so it can contain `#` or `$`.
wm_env_set() {
    _wm_f="$(wm_env_file "${1:?server_dir}")"
    _wm_key="${2:?key}"
    _wm_val="${3-}"
    if grep -q "^${_wm_key}=" "$_wm_f"; then
        _wm_tmp="${_wm_f}.tmp.$$"
        # Literal replacement: generated secrets and URLs contain no sed `&`.
        sed "s|^${_wm_key}=.*|${_wm_key}=${_wm_val}|" "$_wm_f" >"$_wm_tmp"
        chmod 600 "$_wm_tmp"
        mv "$_wm_tmp" "$_wm_f"
    else
        printf '%s=%s\n' "$_wm_key" "$_wm_val" >>"$_wm_f"
    fi
}

wm_random_hex() {
    _wm_bytes="${1:-24}"
    if ! command -v openssl >/dev/null 2>&1; then
        echo "ERROR: openssl is required to generate secrets." >&2
        return 1
    fi
    openssl rand -hex "$_wm_bytes"
}

# wm_env_ensure <server_dir> <KEY> <value>
# Like wm_env_set, but never overwrites an existing non-empty value. Used for
# secrets that must exist in .env without surprising an existing install.
wm_env_ensure() {
    _wm_server="${1:?server_dir}"
    _wm_key="${2:?key}"
    _wm_val="${3-}"
    _wm_existing="$(wm_env_get "$_wm_server" "$_wm_key")"
    if [ -n "$_wm_existing" ]; then
        return 0
    fi
    wm_env_set "$_wm_server" "$_wm_key" "$_wm_val"
}

# wm_template_value <template> <KEY>
wm_template_value() {
    sed -n "s/^${2:?key}=//p" "${1:?template}" | head -n 1
}

# wm_env_merge_cors <server_dir> <url>
# Keeps existing origins and adds the given URL (its origin form) once.
# String-level merge on purpose: it must not destroy the existing JSON.
wm_env_merge_cors() {
    _wm_server="${1:?server_dir}"
    _wm_url="${2:?url}"
    _wm_origin="${_wm_url%/}"
    _wm_current="$(wm_env_get "$_wm_server" WRISTMIND_CORS_ORIGINS)"
    [ -n "$_wm_current" ] || _wm_current="$WM_CORS_DEFAULT"
    case "$_wm_current" in
        *"$_wm_origin"*)
            printf '%s\n' "$_wm_current"
            return 0
            ;;
    esac
    case "$_wm_current" in
        "["*"]")
            _wm_prefix="${_wm_current%]}"
            printf '%s,"%s"]\n' "$_wm_prefix" "$_wm_origin"
            ;;
        *)
            printf '["%s"]\n' "$_wm_origin"
            ;;
    esac
}

# wm_env_create <server_dir> [public_base_url]
# Creates .env from the template, filling every placeholder with a fresh secret
# and keeping every non-secret default. Never overwrites a real existing .env.
wm_env_create() {
    _wm_server="${1:?server_dir}"
    _wm_public="${2-}"
    _wm_f="$(wm_env_file "$_wm_server")"
    _wm_tpl="$_wm_server/.env.production.example"

    if wm_env_exists "$_wm_server" && ! wm_env_is_template "$_wm_server"; then
        echo ".env already exists; leaving it unchanged" >&2
        return 0
    fi

    if [ ! -f "$_wm_tpl" ]; then
        echo "ERROR: template not found: $_wm_tpl" >&2
        return 1
    fi

    _wm_pg="$(wm_random_hex 24)" || return 1
    _wm_bootstrap="$(wm_random_hex 32)" || return 1
    _wm_pepper="$(wm_random_hex 32)" || return 1
    _wm_fallback="$(wm_random_hex 32)" || return 1

    _wm_umask="$(umask)"
    umask 077
    cp "$_wm_tpl" "$_wm_f"
    wm_env_set "$_wm_server" POSTGRES_PASSWORD "$_wm_pg"
    wm_env_set "$_wm_server" WRISTMIND_BOOTSTRAP_SECRET "$_wm_bootstrap"
    wm_env_set "$_wm_server" WRISTMIND_TOKEN_PEPPER "$_wm_pepper"
    wm_env_set "$_wm_server" WRISTMIND_FALLBACK_TICKET_SECRET "$_wm_fallback"

    if [ -n "$_wm_public" ]; then
        wm_env_set "$_wm_server" WRISTMIND_PUBLIC_BASE_URL "$_wm_public"
        # Adds the chosen origin to the template's local-development origins
        # instead of replacing them.
        wm_env_set "$_wm_server" WRISTMIND_CORS_ORIGINS "$(wm_env_merge_cors "$_wm_server" "$_wm_public")"
    fi

    chmod 600 "$_wm_f"
    umask "$_wm_umask"
    echo "Created $_wm_f"
    return 0
}

# wm_env_backup <server_dir> — timestamped copy next to .env, ignored by Git.
wm_env_backup() {
    _wm_f="$(wm_env_file "${1:?server_dir}")"
    [ -f "$_wm_f" ] || return 0
    _wm_b="${_wm_f}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
    _wm_umask="$(umask)"
    umask 077
    cp "$_wm_f" "$_wm_b"
    chmod 600 "$_wm_b"
    umask "$_wm_umask"
    printf '%s\n' "$_wm_b"
}
