# Throwaway sshd host for Hypothex Docker integration tests (tests/docker).
# Never published. No secrets: the test's public key arrives at start in AUTHORIZED_KEY.
FROM python:3.12.7-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /usr/local/bin/

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      openssh-server git procps ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/sshd \
 && ssh-keygen -A \
 && useradd --create-home --uid 1000 --shell /bin/bash hx \
 && usermod -p '*' hx

COPY sshd_hx.conf /etc/ssh/sshd_config.d/hx.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

# the toy project `dock` (no tasks; runs are plain commands)
USER hx
RUN mkdir /home/hx/dock \
 && printf 'project: dock\n' > /home/hx/dock/hypothex.yaml \
 && git -C /home/hx/dock init -q -b main \
 && git -C /home/hx/dock add -A \
 && git -C /home/hx/dock -c user.email=t@t -c user.name=t commit -q -m init
USER root

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
