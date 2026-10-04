#!/usr/bin/env sh
set -eu

wm_project_dir="${WRISTMIND_PROJECT_DIR:-/home/ivan/wristmind-project}"
wm_parent_dir="$(dirname "$wm_project_dir")"
wm_project_name="$(basename "$wm_project_dir")"
wm_before_revision="$(docker run --rm \
    -v "$wm_parent_dir:/work" \
    -w /work \
    alpine/git -c "safe.directory=/work/$wm_project_name" \
    -C "$wm_project_name" rev-parse HEAD)"

docker run --rm \
    -e "GIT_SSH_COMMAND=ssh -i /keys/wristmind-deploy -o IdentitiesOnly=yes -o UserKnownHostsFile=/keys/wristmind-github-known-hosts -o StrictHostKeyChecking=yes" \
    -v "$wm_parent_dir:/work" \
    -v /home/ivan/.ssh:/keys:ro \
    -w /work \
    alpine/git -c "safe.directory=/work/$wm_project_name" \
    -C "$wm_project_name" pull --ff-only origin main

docker run --rm --entrypoint chown \
    -v "$wm_parent_dir:/work" \
    alpine/git -R 1000:1000 "/work/$wm_project_name"

cd "$wm_project_dir/server"
wm_after_revision="$(docker run --rm \
    -v "$wm_parent_dir:/work" \
    -w /work \
    alpine/git -c "safe.directory=/work/$wm_project_name" \
    -C "$wm_project_name" rev-parse HEAD)"
if docker run --rm \
    -v "$wm_parent_dir:/work" \
    -w /work \
    alpine/git -c "safe.directory=/work/$wm_project_name" \
    -C "$wm_project_name" diff --quiet "$wm_before_revision" "$wm_after_revision" -- \
    server/Dockerfile server/pyproject.toml server/src server/compose.yaml; then
    docker compose up -d
else
    docker compose up -d --build
fi
docker compose exec -T nginx nginx -s reload
docker compose ps
