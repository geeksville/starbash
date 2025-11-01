echo "Redirecting to current xauth file..."
rm ~/myxauth.lnk
ln -s /run/user/1000/xauth_* ~/myxauth.lnk
