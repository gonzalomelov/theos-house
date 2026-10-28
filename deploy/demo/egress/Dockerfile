# The only way out for the demo: a forward proxy that refuses everything except CONNECT to the brain.
# Pin alpine by digest at deploy time.
FROM alpine:3.22
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf filter /etc/tinyproxy/
USER tinyproxy
EXPOSE 8888
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
