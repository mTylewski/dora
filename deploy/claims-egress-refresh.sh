#!/bin/sh
# Resolve the allow-listed host names and refresh the nftables egress sets.
# Entries expire after 30 minutes unless refreshed, so removed hosts stop being reachable.
# Run every 5 minutes (systemd timer installed by Ansible).
set -eu

HOSTS_FILE="${1:-/etc/claims/allowed_hosts}"
TIMEOUT="30m"

grep -v '^\s*#' "$HOSTS_FILE" | grep -v '^\s*$' | while read -r host; do
	for ip in $(getent ahostsv4 "$host" | awk '{print $1}' | sort -u); do
		nft add element inet claims egress_v4 "{ $ip timeout $TIMEOUT }"
	done
	for ip in $(getent ahostsv6 "$host" | awk '$1 ~ /:/ {print $1}' | sort -u); do
		nft add element inet claims egress_v6 "{ $ip timeout $TIMEOUT }" 2>/dev/null || true
	done
done
