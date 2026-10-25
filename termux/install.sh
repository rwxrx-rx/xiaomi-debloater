#!/data/data/com.termux/files/usr/bin/sh
# One-time setup for Xiaomi Debloater on Termux
pkg update -y && pkg install -y python android-tools
echo "Done. Run: python xdebloat.py"
