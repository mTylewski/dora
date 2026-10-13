#!/bin/sh
# Pull-based update (CLAUDE.md, section 8): the firm's server fetches the release,
# verifies its signature with the vendor's public key and only then restarts.
# The vendor never logs in to the server.
#
# /etc/claims/release contains one line: the image reference to deploy, pinned by digest,
# e.g. ghcr.io/OWNER/claims-app@sha256:...  The firm's admin changes it after reading
# the release notes; with auto_update=true Ansible points it at the channel tag instead.
set -eu

ROOT="${CLAIMS_ROOT:-/srv/claims}"
RELEASE_FILE="/etc/claims/release"
PUBKEY="/etc/claims/cosign.pub"
ENV_FILE="$ROOT/config/.env"
COMPOSE="docker compose -f /etc/claims/docker-compose.yml --env-file $ENV_FILE"

ref="$(tr -d '[:space:]' < "$RELEASE_FILE")"
[ -n "$ref" ] || { echo "empty $RELEASE_FILE" >&2; exit 1; }

docker pull "$ref"
# Resolve a tag to its digest so exactly the verified image is deployed.
digest_ref="$(docker image inspect --format '{{index .RepoDigests 0}}' "$ref")"

cosign verify --key "$PUBKEY" "$digest_ref" >/dev/null
echo "signature OK: $digest_ref"

current="$(grep '^CLAIMS_IMAGE=' "$ENV_FILE" | cut -d= -f2-)"
if [ "$current" != "$digest_ref" ]; then
	sed -i "s|^CLAIMS_IMAGE=.*|CLAIMS_IMAGE=$digest_ref|" "$ENV_FILE"
fi
# Idempotent: starts missing containers, recreates only those whose image changed.
$COMPOSE up -d --remove-orphans
echo "running $digest_ref (previous: $current)"
