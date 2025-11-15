# until we switch to using the container just use a symlink to reach the 'live/local' inflated version

sudo umount /test-data
sudo ln -s `pwd`/inflated /test-data
