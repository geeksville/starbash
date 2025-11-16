# until we switch to using the container just use a symlink to reach the 'live/local' inflated version

set -e

# in case we had mounted it from a container
sudo umount /test-data || true
# If it exists it should be a bare empty directory now
sudo rmdir /test-data || true
# link to our local project copy
sudo ln -s `pwd`/inflated /test-data
