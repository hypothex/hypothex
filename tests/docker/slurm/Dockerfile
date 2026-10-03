# One image for every node of the Hypothex test SLURM cluster (tests/docker/slurm).
# Debian 12 packages (Slurm 22.05), MUNGE, sshd on the login node, uv for bootstrap.
# All services share this image, so they share the MUNGE key baked in at build time.
FROM debian:12.7-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /usr/local/bin/

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      slurmctld slurmd slurmdbd slurm-client slurm-wlm-basic-plugins slurm-wlm-mysql-plugin \
      munge openssh-server python3 git procps ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN ( [ -f /etc/munge/munge.key ] || mungekey --create --keyfile /etc/munge/munge.key ) \
 && chown munge:munge /etc/munge/munge.key \
 && chmod 400 /etc/munge/munge.key \
 && mkdir -p /run/munge /run/slurm /run/sshd /var/spool/slurmctld /var/spool/slurmd \
 && chown munge:munge /run/munge \
 && chown slurm:slurm /run/slurm /var/spool/slurmctld \
 && ssh-keygen -A \
 && useradd --create-home --uid 1000 --shell /bin/bash hx \
 && usermod -p '*' hx

COPY slurm.conf /etc/slurm/slurm.conf
COPY slurmdbd.conf /etc/slurm/slurmdbd.conf
COPY cgroup.conf /etc/slurm/cgroup.conf
COPY sshd_hx.conf /etc/ssh/sshd_config.d/hx.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chown slurm:slurm /etc/slurm/slurmdbd.conf \
 && chmod 600 /etc/slurm/slurmdbd.conf \
 && chmod 644 /etc/slurm/slurm.conf /etc/slurm/cgroup.conf \
 && chmod 755 /usr/local/bin/entrypoint.sh

# the toy project `dock` on the shared /home (no tasks; runs are plain commands)
USER hx
RUN mkdir /home/hx/dock \
 && printf 'project: dock\n' > /home/hx/dock/hypothex.yaml \
 && git -C /home/hx/dock init -q -b main \
 && git -C /home/hx/dock add -A \
 && git -C /home/hx/dock -c user.email=t@t -c user.name=t commit -q -m init
USER root

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
