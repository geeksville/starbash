# Start from a 'scratch' image. It's literally empty.
FROM scratch

# backpointer for info on ghcr.io
LABEL org.opencontainers.image.source https://github.com/geeksville/starbash
LABEL org.opencontainers.image.description "Test-data for starbash development.  See https://github.com/geeksville/starbash/test-data for more information."

# Copy your big, dumb files into the "box"
COPY inflated/README.md /README.md