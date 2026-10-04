#!/usr/bin/env sh
set -eu

if [ -e .env ] && ! grep -q "generate-a-long-random-value" .env; then
    echo ".env already exists; leaving it unchanged"
    exit 0
fi

umask 077
cp .env.production.example .env
wm_pg_secret="$(openssl rand -hex 24)"
wm_bootstrap_secret="$(openssl rand -hex 32)"
wm_pepper_secret="$(openssl rand -hex 32)"
wm_fallback_secret="$(openssl rand -hex 32)"

sed -i \
    -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${wm_pg_secret}/" \
    -e "s/^WRISTMIND_BOOTSTRAP_SECRET=.*/WRISTMIND_BOOTSTRAP_SECRET=${wm_bootstrap_secret}/" \
    -e "s/^WRISTMIND_TOKEN_PEPPER=.*/WRISTMIND_TOKEN_PEPPER=${wm_pepper_secret}/" \
    -e "s/^WRISTMIND_FALLBACK_TICKET_SECRET=.*/WRISTMIND_FALLBACK_TICKET_SECRET=${wm_fallback_secret}/" \
    .env
chmod 600 .env
echo "Created .env with generated secrets"
