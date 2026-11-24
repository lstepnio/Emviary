#!/bin/sh
set -eu
exec ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 one-codex sudo -n /usr/local/sbin/one-rollout-backup capture emviary
