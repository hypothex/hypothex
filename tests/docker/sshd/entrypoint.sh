#!/bin/sh
# Install the test's public key for user hx, then run sshd in the foreground.
set -eu
if [ -z "${AUTHORIZED_KEY:-}" ]; then
  echo "entrypoint: AUTHORIZED_KEY is not set" >&2
  exit 1
fi
install -d -m 700 -o hx -g hx /home/hx/.ssh
printf '%s\n' "$AUTHORIZED_KEY" > /home/hx/.ssh/authorized_keys
chown hx:hx /home/hx/.ssh/authorized_keys
chmod 600 /home/hx/.ssh/authorized_keys
exec /usr/sbin/sshd -D -e
