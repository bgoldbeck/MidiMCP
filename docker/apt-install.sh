#!/bin/sh
# Install Ubuntu packages in their own image layer, then drop the apt indexes.
# Used once per Dockerfile layer so each package group is cached and uploaded separately.
# apt-get update is retried: Ubuntu mirrors briefly serve mismatched indexes while syncing.
set -eu
for attempt in 1 2 3 4 5; do
  apt-get -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update && break
  echo "apt-get update failed (attempt $attempt/5), retrying in 30s..." >&2
  rm -rf /var/lib/apt/lists/*
  sleep 30
done
apt-get -o Acquire::Retries=3 install -y --no-install-recommends "$@"
rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /var/log/apt /var/log/dpkg.log
