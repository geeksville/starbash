
echo "This script allows developers to generate new 'vhs' demo movies for the github README."
echo "Note: it can't work in the devcontainer you must run it on the host side."
echo "On host run 'brew install vhs'"

vhs doc/vhs/sample-session.tape
# Not needed - for the time being we just use the gif in our repo
# vhs publish doc/vhs/sample-session.gif


