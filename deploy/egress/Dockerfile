# The only way out to the internet for the agent: a forward proxy that refuses everything except
# HTTPS tunnels to the hosts in the filter file. Same pattern as the Recipe Sender chat on this server.
# alpine pinned by digest (3.22, 2026-10-11). Bump deliberately.
FROM alpine@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf filter /etc/tinyproxy/
USER tinyproxy
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
