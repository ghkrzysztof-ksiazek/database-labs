FROM percona/percona-orchestrator:3.2.6-24

USER root
# MariaDB client is the hook's admin client for ProxySQL. The Orchestrator
# binary itself speaks MySQL; it does not need this package.
RUN microdnf install -y mariadb && microdnf clean all
COPY proxysql-failover-hook.sh /usr/local/bin/proxysql-failover-hook.sh
RUN chmod 755 /usr/local/bin/proxysql-failover-hook.sh

# Lab-only: the sqlite directory is a Docker volume owned by root, and the
# hook writes /var/log/proxysql-failover.log. The image's default uid 1001
# cannot use either path.
USER root
