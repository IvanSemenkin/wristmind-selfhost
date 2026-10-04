#!/usr/bin/env sh
# WristMind self-hosting library: state detection, requirement checks and the
# install sequence. Sourced by the `wristmind` entry point; not run directly.
#
# POSIX sh. File lives in server/deploy/.

WM_DEFAULT_INSTALL_TIMEOUT=1200
WM_DEFAULT_HEALTH_TIMEOUT=180
WM_REQUIRED_RAM_MB=3800
WM_REQUIRED_DISK_MB=10240
# "Just look" install: a file-backed database inside the private volume.
WM_LOCAL_DATABASE_URL="sqlite+aiosqlite:////data/private/wristmind.db"

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

# wm_compose_stack <server_dir> <args...> — the same stack plus the HTTPS
# overlay when it exists. Used for anything certificate-related.
wm_compose_stack() {
    _wm_dir="${1:?server_dir}"
    shift
    if [ -f "$_wm_dir/compose.tls.yaml" ]; then
        wm_compose "$_wm_dir" -f compose.yaml -f compose.tls.yaml "$@"
    else
        wm_compose "$_wm_dir" "$@"
    fi
}

# wm_compose_stack_log <server_dir> <args...> — quiet unless it fails.
wm_compose_stack_log() {
    _wm_server="${1:?server_dir}"
    shift
    _wm_log="${TMPDIR:-/tmp}/wristmind-compose-tls.$$.log"
    if wm_compose_stack "$_wm_server" "$@" >"$_wm_log" 2>&1; then
        rm -f "$_wm_log"
        return 0
    fi
    tail -n 40 "$_wm_log" | sed 's/^/   /' >&2
    rm -f "$_wm_log"
    return 1
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

# wm_domain_dns_status <host> -> ok | mismatch | unresolved | unknown
# Compares the A records of a host with this machine's public-looking address.
wm_domain_dns_status() {
    _wm_domain="${1:?host}"
    _wm_target="$2"
    if ! wm_have_cmd getent && ! wm_have_cmd nslookup && ! wm_have_cmd dig; then
        printf 'unknown\n'
        return 0
    fi
    _wm_ips=""
    if wm_have_cmd getent; then
        _wm_ips="$(getent ahostsv4 "$_wm_domain" 2>/dev/null | awk '{print $1}' | sort -u)"
    elif wm_have_cmd dig; then
        _wm_ips="$(dig +short A "$_wm_domain" 2>/dev/null | sort -u)"
    else
        _wm_ips="$(nslookup -type=A "$_wm_domain" 2>/dev/null | awk '/^Address: / {print $2}' | sort -u)"
    fi
    if [ -z "$_wm_ips" ]; then
        printf 'unresolved\n'
        return 0
    fi
    for _wm_ip in $_wm_ips; do
        if [ -n "$_wm_target" ] && [ "$_wm_ip" = "$_wm_target" ]; then
            printf 'ok\n'
            return 0
        fi
    done
    printf 'mismatch\n'
}

# wm_public_ip — best-effort public address of this host, empty when unknown.
wm_public_ip() {
    for _wm_url in https://ifconfig.me https://icanhazip.com https://api.ipify.org; do
        if wm_have_cmd curl; then
            _wm_ip="$(curl -fsS --max-time 4 "$_wm_url" 2>/dev/null | tr -d '[:space:]')"
        elif wm_have_cmd wget; then
            _wm_ip="$(wget -q -T 4 -O - "$_wm_url" 2>/dev/null | tr -d '[:space:]')"
        else
            return 0
        fi
        case "$_wm_ip" in
            "" | *[!0-9.]* ) continue ;;
        esac
        printf '%s\n' "$_wm_ip"
        return 0
    done
}

# wm_install <repo_root> [flags]
#   --public-url=URL   public address of this install
#   --domain=HOST      implies https://HOST
#   --local            "just look" mode: SQLite, mock providers, no db container
#   --with-search      enable the private SearXNG profile
# Idempotent: an existing .env is preserved and compose only reconciles state.
wm_install() {
    _wm_root="${1:?repo_root}"
    shift
    _wm_public=""
    _wm_domain=""
    _wm_public_explicit=0
    _wm_local=0
    _wm_with_search=0
    for _wm_arg in "$@"; do
        case "$_wm_arg" in
            --public-url=*) _wm_public="${_wm_arg#--public-url=}"; _wm_public_explicit=1 ;;
            --domain=*) _wm_domain="${_wm_arg#--domain=}"; _wm_public_explicit=1 ;;
            --local) _wm_local=1 ;;
            --with-search) _wm_with_search=1 ;;
            *) wm_wait "неизвестный параметр проигнорирован: $_wm_arg" ;;
        esac
    done

    _wm_server="$(wm_server_dir "$_wm_root")"
    _wm_port="$(wm_http_port "$_wm_server")"

    # A domain implies HTTPS; a bare address stays plain HTTP. A local install
    # is always reached at loopback.
    if [ "$_wm_local" -eq 1 ]; then
        _wm_public="http://127.0.0.1:$_wm_port"
    elif [ -n "$_wm_domain" ]; then
        _wm_public="https://${_wm_domain#*://}"
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

    # Honest DNS report before anything claims to serve HTTPS. A wrong A record
    # is a warning, not a hard stop: the server still installs, the watch just
    # cannot connect yet.
    _wm_dns_ready=""
    case "$_wm_public" in
        https://*)
            _wm_domain_only="${_wm_public#https://}"
            _wm_domain_only="${_wm_domain_only%%/*}"
            _wm_domain_only="${_wm_domain_only%%:*}"
            _wm_public_ip="$(wm_public_ip)"
            _wm_dns="$(wm_domain_dns_status "$_wm_domain_only" "$_wm_public_ip")"
            case "$_wm_dns" in
                ok)
                    wm_ok "DNS: $_wm_domain_only указывает на $_wm_public_ip"
                    _wm_dns_ready=1
                    ;;
                mismatch)
                    wm_wait "DNS: $_wm_domain_only не указывает на $_wm_public_ip"
                    ;;
                unresolved)
                    wm_wait "DNS: $_wm_domain_only пока не разрешается"
                    ;;
                *)
                    wm_wait "DNS не проверен: нет getent/dig/nslookup"
                    ;;
            esac
            ;;
    esac

    wm_step "2/5 Секреты и .env"
    if wm_env_exists "$_wm_server" && ! wm_env_is_template "$_wm_server"; then
        wm_ok ".env уже существует, секреты не меняются"
        wm_env_backup "$_wm_server" >/dev/null 2>&1 || true
    else
        # Only an explicit address is written; otherwise the template's
        # neutral localhost default stays in place.
        if [ "$_wm_public_explicit" -eq 1 ]; then
            wm_env_create "$_wm_server" "$_wm_public" || return 1
        else
            wm_env_create "$_wm_server" || return 1
        fi
        wm_ok ".env создан, секреты сгенерированы"
    fi
    if wm_env_is_template "$_wm_server"; then
        wm_err ".env остался шаблоном: заполните значения вручную."
        return 1
    fi

    # Persist the chosen public address and CORS origins even for an existing
    # Persist an explicit address even for an existing .env, so enrollment
    # links and browser access use the same one. A bare domain is stored as
    # http:// until a certificate actually exists: claiming https:// before
    # that would be a lie.
    if [ "$_wm_public_explicit" -eq 1 ]; then
        _wm_store="$_wm_public"
        if [ -n "$_wm_domain" ] && [ "$(wm_env_get "$_wm_server" WRISTMIND_TLS_ENABLED)" != "true" ]; then
            _wm_store="http://$_wm_domain"
        fi
        [ -n "$_wm_domain" ] && wm_env_set "$_wm_server" WRISTMIND_DOMAIN "$_wm_domain"
        wm_env_set "$_wm_server" WRISTMIND_PUBLIC_BASE_URL "$_wm_store"
        wm_env_set "$_wm_server" WRISTMIND_CORS_ORIGINS "$(wm_env_merge_cors "$_wm_server" "$_wm_store")"
        wm_ok "адрес сохранён: $_wm_store"
    fi

    if [ "$_wm_local" -eq 1 ]; then
        wm_env_set "$_wm_server" WRISTMIND_DATABASE_URL "$WM_LOCAL_DATABASE_URL"
        wm_env_set "$_wm_server" WRISTMIND_MOCK_PROVIDERS true
        wm_ok "локальный режим: SQLite и моки провайдеров"
    fi
    if [ "$_wm_with_search" -eq 1 ]; then
        wm_env_ensure "$_wm_server" SEARXNG_SECRET "$(wm_random_hex 32)"
        wm_env_set "$_wm_server" WRISTMIND_SEARXNG_URL "http://searxng:8080"
        wm_ok "веб-поиск включён (профиль search)"
    fi

    _wm_profiles="--profile plain"
    [ "$_wm_with_search" -eq 1 ] && _wm_profiles="$_wm_profiles --profile search"

    if [ "$_wm_local" -eq 0 ]; then
        wm_step "3/5 База данных"
        if ! wm_compose_log "$_wm_server" up -d db; then
            wm_err "не удалось поднять контейнер db."
            return 1
        fi
        wm_ok "контейнер db запущен"
    else
        wm_step "3/5 База данных"
        wm_ok "внешняя база не нужна: используется SQLite в приватном томе"
    fi

    wm_step "4/5 API, обработчик и веб-шлюз"
    # shellcheck disable=SC2086
    if ! wm_compose_log "$_wm_server" $_wm_profiles up -d api worker nginx; then
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

# ---------------------------------------------------------------------------
# TLS
# ---------------------------------------------------------------------------
# wm_tls_render <server_dir> <domain>
# Renders the HTTPS nginx configuration from its template. The result is
# deployment-specific and therefore not tracked by Git.
wm_tls_render() {
    _wm_server="${1:?server_dir}"
    _wm_domain="${2:?domain}"
    _wm_tpl="$_wm_server/deploy/nginx.tls.conf"
    _wm_out="$_wm_server/tls/nginx.conf"
    [ -f "$_wm_tpl" ] || { wm_err "нет шаблона $_wm_tpl"; return 1; }
    mkdir -p "$_wm_server/tls"
    sed "s|__WM_DOMAIN__|${_wm_domain}|g" "$_wm_tpl" >"$_wm_out"
    printf '%s\n' "$_wm_out"
}

# wm_https_ok <domain> — probes the HTTPS endpoint without relying on public
# DNS from inside this machine.
wm_https_ok() {
    _wm_domain="${1:?domain}"
    if wm_have_cmd curl; then
        curl -fsS -o /dev/null --max-time 8 \
            --resolve "${_wm_domain}:443:127.0.0.1" \
            "https://${_wm_domain}/health" >/dev/null 2>&1
        return $?
    fi
    # No curl: at least confirm that TLS on 443 is up.
    return 1
}

# wm_tls <repo_root> [--domain=HOST] [--email=ADDR] [--staging]
# Requests an ACME certificate and turns on HTTPS. Honest about every refusal.
wm_tls() {
    _wm_root="${1:?repo_root}"
    shift
    _wm_domain_arg=""
    _wm_email_arg=""
    _wm_staging="false"
    for _wm_arg in "$@"; do
        case "$_wm_arg" in
            --domain=*) _wm_domain_arg="${_wm_arg#--domain=}" ;;
            --email=*) _wm_email_arg="${_wm_arg#--email=}" ;;
            --staging) _wm_staging="true" ;;
        esac
    done

    _wm_server="$(wm_server_dir "$_wm_root")"
    wm_have_compose || { wm_err "Docker Compose недоступен."; return 1; }

    _wm_domain="$(wm_env_get "$_wm_server" WRISTMIND_DOMAIN)"
    [ -n "$_wm_domain_arg" ] && _wm_domain="$_wm_domain_arg"
    [ -n "$_wm_domain" ] || {
        wm_err "домен не задан. Выполните: ./wristmind tls --domain=example.com --email=you@example.com"
        return 1
    }
    _wm_email="$(wm_env_get "$_wm_server" WRISTMIND_TLS_EMAIL)"
    [ -n "$_wm_email_arg" ] && _wm_email="$_wm_email_arg"
    [ -n "$_wm_email" ] || {
        wm_err "нужен адрес для ACME. Добавьте --email=you@example.com"
        return 1
    }

    # Nothing is written before every check passes: a refused request must
    # leave the install exactly as it was.
    wm_step "1/4 Проверка домена"
    _wm_public_ip="$(wm_public_ip)"
    _wm_dns="$(wm_domain_dns_status "$_wm_domain" "$_wm_public_ip")"
    case "$_wm_dns" in
        ok) wm_ok "DNS: $_wm_domain указывает на $_wm_public_ip" ;;
        mismatch)
            wm_err "DNS: $_wm_domain не указывает на $_wm_public_ip. Сертификат не будет выпущен."
            return 1
            ;;
        unresolved)
            wm_err "DNS: $_wm_domain не разрешается. Сначала настройте A-запись."
            return 1
            ;;
        *) wm_wait "DNS не проверен: нет getent/dig/nslookup. Продолжаю." ;;
    esac

    wm_step "2/4 Конфигурация HTTPS"
    _wm_rendered="$(wm_tls_render "$_wm_server" "$_wm_domain")" || return 1
    wm_ok "конфигурация: $_wm_rendered"

    # Port 80 must serve the ACME challenge. Bring up the HTTPS front end
    # first: it is the one that listens on 80/443.
    wm_step "3/4 Порт 80 и выпуск сертификата"
    if ! wm_compose_stack_log "$_wm_server" --profile tls up -d nginx-tls; then
        wm_err "не удалось поднять nginx-tls до выпуска сертификата."
        return 1
    fi
    if ! wm_compose_stack "$_wm_server" --profile tls run --rm certbot; then
        wm_err "certbot не выпустил сертификат. HTTPS не включён; HTTP-режим не изменён."
        return 1
    fi
    wm_ok "сертификат получен для $_wm_domain"

    wm_step "4/4 Включение HTTPS"
    # nginx-tls started before the certificate existed; reload it so it reads
    # the files, then stop the plain HTTP front end if it was running.
    wm_compose_stack "$_wm_server" --profile tls exec -T nginx-tls nginx -s reload >/dev/null 2>&1 || true
    wm_compose_stack_log "$_wm_server" stop nginx >/dev/null 2>&1 || true
    wm_env_set "$_wm_server" WRISTMIND_DOMAIN "$_wm_domain"
    wm_env_set "$_wm_server" WRISTMIND_TLS_EMAIL "$_wm_email"
    wm_env_set "$_wm_server" WRISTMIND_TLS_STAGING "$_wm_staging"
    wm_env_set "$_wm_server" WRISTMIND_TLS_ENABLED "true"
    wm_env_set "$_wm_server" WRISTMIND_PUBLIC_BASE_URL "https://$_wm_domain"
    wm_env_set "$_wm_server" WRISTMIND_CORS_ORIGINS "$(wm_env_merge_cors "$_wm_server" "https://$_wm_domain")"
    wm_ok "HTTPS включён, plain HTTP остановлен"

    if wm_https_ok "$_wm_domain"; then
        wm_ok "HTTPS отвечает на https://$_wm_domain"
    else
        wm_wait "HTTPS пока не ответил; проверьте: curl -I https://$_wm_domain"
    fi

    printf '\n'
    printf 'HTTPS включён: https://%s\n' "$_wm_domain"
    printf 'Сертификат продлевается так:\n'
    printf '  docker compose -f compose.yaml -f compose.tls.yaml --profile tls run --rm certbot renew\n'
    printf 'Автоматическое продление пока не входит в установщик.\n'
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
    # Not shown for a loopback-only local install, where it would be wrong.
    case "$_wm_public" in
        *127.0.0.1* | *localhost*) _wm_show_lan=0 ;;
        *) _wm_show_lan=1 ;;
    esac
    _wm_host="$(wm_host_ip)"
    _wm_hostport="${_wm_base#*://}"
    _wm_hostport="${_wm_hostport%%/*}"
    _wm_portpart="${_wm_hostport##*:}"
    if [ "$_wm_show_lan" -eq 1 ] && [ "$_wm_host" != "127.0.0.1" ] \
        && [ "$_wm_portpart" != "$_wm_hostport" ]; then
        printf '  По сети:     http://%s:%s/main\n' "$_wm_host" "$_wm_portpart"
    fi
    # A public HTTPS address is what watches and remote clients use.
    case "$_wm_public" in
        https://*) printf '  Публичный:   %s\n' "$_wm_public" ;;
    esac
    case "$_wm_public" in
        *127.0.0.1* | *localhost*)
            printf '\n  Локальный просмотр: данные в приватном томе, ключи не нужны.\n'
            ;;
    esac
    if [ "$(wm_env_get "$_wm_server" WRISTMIND_TLS_ENABLED)" = "true" ] && [ -n "$_wm_domain" ]; then
        printf '  Часы подключаются по адресу https://%s\n' "$_wm_domain"
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
