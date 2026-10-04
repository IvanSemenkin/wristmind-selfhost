#!/usr/bin/env sh
# WristMind self-hosting library: state detection, requirement checks and the
# install sequence. Sourced by the `wristmind` entry point; not run directly.
#
# POSIX sh. File lives in server/deploy/.

WM_DEFAULT_INSTALL_TIMEOUT=1200
WM_DEFAULT_HEALTH_TIMEOUT=180
WM_REQUIRED_RAM_MB=3800
WM_REQUIRED_DISK_MB=10240

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
wm_err() { printf '%s\n' "ошибка: $*" >&2; }

wm_step() { printf '%s\n' "$*"; }
wm_ok() { printf '   ✅ %s\n' "$*"; }
wm_wait() { printf '   ⏳ %s\n' "$*"; }

wm_have_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
wm_server_dir() { printf '%s\n' "${1:?repo_root}/server"; }

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
wm_have_docker() { command -v docker >/dev/null 2>&1; }

wm_have_compose() {
    wm_have_docker || return 1
    docker compose version >/dev/null 2>&1
}

wm_compose_version() { docker compose version 2>/dev/null | head -n 1; }

wm_docker_version() { docker version --format '{{.Server.Version}}' 2>/dev/null; }

wm_docker_usable() {
    wm_have_docker || return 1
    docker info >/dev/null 2>&1
}

# wm_compose <server_dir> <args...> — runs compose from the server directory,
# letting it read server/.env itself.
wm_compose() {
    _wm_dir="${1:?server_dir}"
    shift
    ( cd "$_wm_dir" && docker compose "$@" )
}

# Runs a command with a hard time limit when `timeout` is available.
# Never used to wrap shell functions: `timeout` requires a real command.
wm_run_long() {
    if wm_have_cmd timeout; then
        timeout "${WRISTMIND_INSTALL_TIMEOUT:-$WM_DEFAULT_INSTALL_TIMEOUT}" "$@"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Requirement checks
# ---------------------------------------------------------------------------
# wm_requirements <repo_root> [--runtime]
# One line per check; returns non-zero when a hard requirement fails.
wm_requirements() {
    _wm_root="${1:?repo_root}"
    _wm_runtime="${2-}"
    _wm_server="$(wm_server_dir "$_wm_root")"
    _wm_failed=0

    if ! wm_have_docker; then
        wm_err "Docker не найден. Установите Docker Engine."
        _wm_failed=1
    elif ! wm_docker_usable; then
        wm_err "Docker установлен, но демон недоступен: запустите его или проверьте права."
        _wm_failed=1
    else
        wm_ok "Docker $(wm_docker_version)"
    fi

    if ! wm_have_compose; then
        wm_err "Docker Compose (плагин v2) не найден."
        _wm_failed=1
    else
        wm_ok "$(wm_compose_version)"
    fi

    if [ -r /proc/meminfo ]; then
        _wm_mem_mb=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 ))
        if [ "$_wm_mem_mb" -lt "$WM_REQUIRED_RAM_MB" ]; then
            wm_err "RAM ${_wm_mem_mb} МБ — меньше требуемых ${WM_REQUIRED_RAM_MB} МБ."
            _wm_failed=1
        else
            wm_ok "RAM ${_wm_mem_mb} МБ"
        fi
    else
        wm_wait "RAM не проверена: нет /proc/meminfo"
    fi

    if wm_have_cmd df; then
        _wm_disk_mb="$(df -Pk "$_wm_root" 2>/dev/null | awk 'NR==2 {print int($4 / 1024)}')"
        if [ -n "$_wm_disk_mb" ] && [ "$_wm_disk_mb" -lt "$WM_REQUIRED_DISK_MB" ]; then
            wm_err "Свободно ${_wm_disk_mb} МБ — меньше требуемых ${WM_REQUIRED_DISK_MB} МБ."
            _wm_failed=1
        elif [ -n "$_wm_disk_mb" ]; then
            wm_ok "Свободное место ${_wm_disk_mb} МБ"
        fi
    fi

    _wm_port="$(wm_http_port "$_wm_server")"
    if wm_port_in_use "$_wm_port"; then
        if [ -n "$_wm_runtime" ]; then
            wm_ok "Порт $_wm_port занят — это может быть уже работающая установка"
        else
            wm_err "Порт $_wm_port уже занят. Освободите его или задайте WRISTMIND_HTTP_PORT."
            _wm_failed=1
        fi
    else
        wm_ok "Порт $_wm_port свободен"
    fi

    [ "$_wm_failed" -eq 0 ]
}

# wm_port_in_use <port> — true when something is listening on the port.
wm_port_in_use() {
    _wm_port="${1:?port}"
    if wm_have_cmd ss; then
        ss -ltn 2>/dev/null | awk -v p=":${_wm_port}" '$4 ~ p"$" {found=1} END {exit !found}'
        return $?
    fi
    if wm_have_cmd netstat; then
        netstat -ltn 2>/dev/null | awk -v p=":${_wm_port}" '$4 ~ p"$" {found=1} END {exit !found}'
        return $?
    fi
    return 1
}

# ---------------------------------------------------------------------------
# State detection
# ---------------------------------------------------------------------------
# wm_state <repo_root> -> installed | configured | empty
wm_state() {
    _wm_root="${1:?repo_root}"
    _wm_server="$(wm_server_dir "$_wm_root")"

    if wm_compose_running "$_wm_server"; then
        printf 'installed\n'
    elif wm_env_exists "$_wm_server" && ! wm_env_is_template "$_wm_server"; then
        printf 'configured\n'
    else
        printf 'empty\n'
    fi
}

# True when at least one container of this compose project exists.
wm_compose_running() {
    _wm_server="${1:?server_dir}"
    wm_have_compose || return 1
    _wm_ids="$( wm_compose "$_wm_server" ps -aq 2>/dev/null )" || return 1
    [ -n "$_wm_ids" ]
}

# wm_version_label <repo_root> — best-effort version of this checkout.
wm_version_label() {
    _wm_root="${1:?repo_root}"
    if [ -d "$_wm_root/.git" ] && wm_have_cmd git; then
        _wm_rev="$(git -C "$_wm_root" rev-parse --short HEAD 2>/dev/null)"
        _wm_branch="$(git -C "$_wm_root" branch --show-current 2>/dev/null)"
        if [ -n "$_wm_rev" ]; then
            printf '%s@%s\n' "${_wm_branch:-detached}" "$_wm_rev"
            return 0
        fi
    fi
    printf 'unknown\n'
}

# ---------------------------------------------------------------------------
# Runtime probes
# ---------------------------------------------------------------------------
# wm_host_ip — best-effort host address for the printed panel URL.
wm_host_ip() {
    if wm_have_cmd ip; then
        _wm_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
        if [ -n "$_wm_ip" ]; then
            printf '%s\n' "$_wm_ip"
            return 0
        fi
    fi
    printf '127.0.0.1\n'
}

wm_http_port() {
    _wm_server="${1:?server_dir}"
    _wm_p="$(wm_env_get "$_wm_server" WRISTMIND_HTTP_PORT)"
    printf '%s\n' "${_wm_p:-${WRISTMIND_HTTP_PORT:-8080}}"
}

wm_http_ok() {
    _wm_u="${1:?url}"
    if wm_have_cmd curl; then
        curl -fsS -o /dev/null --max-time 5 "$_wm_u" >/dev/null 2>&1
    elif wm_have_cmd wget; then
        wget -q -T 5 -O /dev/null "$_wm_u" >/dev/null 2>&1
    else
        return 1
    fi
}

# wm_wait_for_health <base_url> [timeout_seconds]
wm_wait_for_health() {
    _wm_url="${1:?url}"
    _wm_deadline=$(( $(date +%s) + ${2:-$WM_DEFAULT_HEALTH_TIMEOUT} ))
    while [ "$(date +%s)" -lt "$_wm_deadline" ]; do
        if wm_http_ok "$_wm_url/health"; then
            return 0
        fi
        sleep 3
    done
    return 1
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
# wm_compose_log <server_dir> <compose args...> — quiet unless it fails.
wm_compose_log() {
    _wm_server="${1:?server_dir}"
    shift
    _wm_log="${TMPDIR:-/tmp}/wristmind-compose.$$.log"
    if wm_compose "$_wm_server" "$@" >"$_wm_log" 2>&1; then
        rm -f "$_wm_log"
        return 0
    fi
    tail -n 40 "$_wm_log" | sed 's/^/   /' >&2
    rm -f "$_wm_log"
    return 1
}

# wm_install <repo_root> [--public-url=URL] [--domain=HOST]
# Idempotent: an existing .env is preserved and compose only reconciles state.
wm_install() {
    _wm_root="${1:?repo_root}"
    shift
    _wm_public=""
    _wm_domain=""
    for _wm_arg in "$@"; do
        case "$_wm_arg" in
            --public-url=*) _wm_public="${_wm_arg#--public-url=}" ;;
            --domain=*) _wm_domain="${_wm_arg#--domain=}" ;;
        esac
    done

    _wm_server="$(wm_server_dir "$_wm_root")"
    _wm_port="$(wm_http_port "$_wm_server")"

    # A domain implies HTTPS; a bare address stays plain HTTP.
    if [ -n "$_wm_domain" ]; then
        _wm_public="https://${_wm_domain#https://}"
        _wm_public="${_wm_public#http://}"
    elif [ -z "$_wm_public" ]; then
        _wm_ip="$(wm_host_ip)"
        if [ "$_wm_port" = "80" ]; then
            _wm_public="http://$_wm_ip"
        else
            _wm_public="http://$_wm_ip:$_wm_port"
        fi
    fi

    wm_step "1/5 Подготовка окружения"
    if ! wm_have_compose; then
        wm_err "Docker Compose недоступен, установка остановлена."
        return 1
    fi
    wm_ok "Docker Compose доступен"

    wm_step "2/5 Секреты и .env"
    if wm_env_exists "$_wm_server" && ! wm_env_is_template "$_wm_server"; then
        wm_ok ".env уже существует, секреты не меняются"
        wm_env_backup "$_wm_server" >/dev/null 2>&1 || true
    else
        wm_env_create "$_wm_server" "$_wm_public" || return 1
        wm_ok ".env создан, секреты сгенерированы"
    fi
    if wm_env_is_template "$_wm_server"; then
        wm_err ".env остался шаблоном: заполните значения вручную."
        return 1
    fi

    wm_step "3/5 База данных"
    if ! wm_compose_log "$_wm_server" up -d db; then
        wm_err "не удалось поднять контейнер db."
        return 1
    fi
    wm_ok "контейнер db запущен"

    wm_step "4/5 API, обработчик и веб-шлюз"
    if ! wm_compose_log "$_wm_server" up -d api worker nginx; then
        wm_err "не удалось поднять api/worker/nginx. Последние строки:"
        wm_compose "$_wm_server" logs --tail=40 api worker nginx 2>&1 | sed 's/^/   /'
        return 1
    fi
    wm_ok "api, worker и nginx запущены"

    wm_step "5/5 Проверка"
    _wm_base="http://127.0.0.1:$_wm_port"
    if wm_wait_for_health "$_wm_base" "${WRISTMIND_HEALTH_TIMEOUT:-$WM_DEFAULT_HEALTH_TIMEOUT}"; then
        wm_ok "API отвечает: $_wm_base/health"
    else
        wm_err "API не ответил за отведённое время. Логи:"
        wm_compose "$_wm_server" logs --tail=40 api worker 2>&1 | sed 's/^/   /'
        return 1
    fi

    printf '\n'
    wm_access_block "$_wm_root" "$_wm_base"
}

# wm_access_block <repo_root> <local_base_url> — where the user goes next.
wm_access_block() {
    _wm_root="${1:?repo_root}"
    _wm_base="${2:?base}"
    _wm_server="$(wm_server_dir "$_wm_root")"
    _wm_public="$(wm_env_get "$_wm_server" WRISTMIND_PUBLIC_BASE_URL)"
    _wm_bootstrap="$(wm_env_get "$_wm_server" WRISTMIND_BOOTSTRAP_SECRET)"

    printf 'WristMind установлен.\n\n'
    printf '  Панель:      %s/main\n' "$_wm_base"
    printf '  API:         %s/v1\n' "$_wm_base"
    # Host address for reaching the panel from another machine on the LAN.
    _wm_host="$(wm_host_ip)"
    _wm_hostport="${_wm_base#*://}"
    _wm_hostport="${_wm_hostport%%/*}"
    _wm_portpart="${_wm_hostport##*:}"
    if [ "$_wm_host" != "127.0.0.1" ] && [ "$_wm_portpart" != "$_wm_hostport" ]; then
        printf '  По сети:     http://%s:%s/main\n' "$_wm_host" "$_wm_portpart"
    fi
    # Printed only when the public address is a real different (e.g. HTTPS) URL.
    if [ -n "$_wm_public" ]; then
        _wm_public_host="${_wm_public#*://}"
        _wm_public_host="${_wm_public_host%%/*}"
        _wm_public_host="${_wm_public_host%%:*}"
        if [ "$_wm_public_host" != "$_wm_host" ]; then
            printf '  Публичный:   %s\n' "$_wm_public"
        fi
    fi
    printf '\n'
    # The vision says the bootstrap secret should never reach the user. Until
    # the /setup wizard exists there is no other way to enroll the first panel,
    # so this is printed deliberately and will be removed with that wizard.
    printf '  Первое подключение панели: bootstrap-секрет из %s/.env\n' "$_wm_server"
    if [ -n "$_wm_bootstrap" ]; then
        printf '    %s\n' "$_wm_bootstrap"
    fi
    printf '\n'
    printf '  Мастер /setup ещё не реализован — это следующий шаг, не текущая функция.\n'
    printf '  Часы Wear OS требуют HTTPS и домен. Пока их нет, подключается только панель.\n'
}
