# Start from a 'scratch' image. It's literally empty.
FROM scratch

# backpointer for info on ghcr.io
LABEL org.opencontainers.image.source https://github.com/geeksville/starbash
LABEL org.opencontainers.image.description "Test-data for starbash development.  See https://github.com/geeksville/starbash/test-data for more information."

# Copy all files from inflated/ into /test-data
COPY inflated/ /test-data/

# Declare this directory as a volume so --volumes-from can mount it
VOLUME /test-data