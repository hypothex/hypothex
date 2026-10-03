#!/bin/bash
# Start MUNGE, then one SLURM role: slurmdbd | slurmctld (+ sshd, the login node) | slurmd.
set -euo pipefail
role="${1:?usage: entrypoint.sh slurmdbd|slurmctld|slurmd}"

wait_tcp() {
  until (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null; do
    echo "entrypoint: waiting for $1:$2" >&2
    sleep 1
  done
}

runuser -u munge -- /usr/sbin/munged --force

case "$role" in
  slurmdbd)
    wait_tcp mysql 3306
    exec /usr/sbin/slurmdbd -D
    ;;
  slurmctld)
    key="${AUTHORIZED_KEY:?entrypoint: AUTHORIZED_KEY is not set}"
    install -d -m 700 -o hx -g hx /home/hx/.ssh
    printf '%s\n' "$key" > /home/hx/.ssh/authorized_keys
    chown hx:hx /home/hx/.ssh/authorized_keys
    chmod 600 /home/hx/.ssh/authorized_keys
    /usr/sbin/sshd -e
    wait_tcp slurmdbd 6819
    sacctmgr -i add cluster hx >/dev/null 2>&1 || true
    exec /usr/sbin/slurmctld -D
    ;;
  slurmd)
    # cgroup v2 without systemd: slurmd puts slurmstepd under this slice (see cgroup.conf)
    if [ -f /sys/fs/cgroup/cgroup.controllers ]; then
      mkdir -p /sys/fs/cgroup/system.slice
    fi
    wait_tcp slurmctld 6817
    exec /usr/sbin/slurmd -D
    ;;
  *)
    echo "entrypoint: unknown role $role" >&2
    exit 2
    ;;
esac
