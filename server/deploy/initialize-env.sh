#!/usr/bin/env sh
# Generate server/.env with fresh secrets.
#
# Kept for direct use on an existing install; `./wristmind install` calls the
# same implementation. An existing real .env is never rewritten.
#
#   sh server/deploy/initialize-env.sh [public_base_url]

set -eu

wm_script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
wm_server_dir="$(dirname -- "$wm_script_dir")"

# shellcheck source=env.sh
. "$wm_script_dir/env.sh"

wm_env_create "$wm_server_dir" "${1-}"
