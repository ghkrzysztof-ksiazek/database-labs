FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        sysbench mysql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Text protocol, so ProxySQL match_digest rules see the statement text.
# Prepared statements pin a backend at COM_STMT_PREPARE and skip later rules.
ENTRYPOINT ["sysbench"]
