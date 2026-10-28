# The only way out for the families service: a forward proxy that refuses everything except CONNECT to the brain and Telegram.
# alpine 3.22 pinned by digest (2026-10-11), the same base as the family agent's proxy. Bump deliberately.
FROM alpine@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf filter /etc/tinyproxy/
USER tinyproxy
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
