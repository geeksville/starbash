# until we switch to using the container just use a symlink to reach the 'live/local' inflated version

sudo rm -f /test-data
sudo ln -s `pwd`/inflated/ /test-data
