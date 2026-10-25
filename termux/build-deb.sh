#!/bin/sh
# Builds the Termux .deb and a .tar.gz into termux/dist. Usage: sh build-deb.sh VERSION [OWNER]
set -eu
VERSION="${1:?usage: build-deb.sh VERSION [OWNER]}"
OWNER="${2:-maintainer}"
cd "$(dirname "$0")"
P=/data/data/com.termux/files/usr
B="$(mktemp -d)"
trap 'rm -rf "$B"' EXIT
rm -rf dist
mkdir -p "$B/DEBIAN" "$B$P/bin" "$B$P/share/xiaomi-debloater" dist
install -m 755 xdebloat.py "$B$P/share/xiaomi-debloater/xdebloat.py"
cat > "$B$P/bin/xdebloat" <<WRAP
#!$P/bin/sh
exec python $P/share/xiaomi-debloater/xdebloat.py "\$@"
WRAP
chmod 755 "$B$P/bin/xdebloat"
cat > "$B/DEBIAN/control" <<CTRL
Package: xiaomi-debloater-termux
Version: $VERSION
Architecture: all
Maintainer: $OWNER <noreply@github.com>
Depends: python, android-tools
Section: utils
Homepage: https://github.com/fadeltd/xiaomi-debloater
Description: Xiaomi/HyperOS debloater CLI for Termux (no root, Wireless debugging)
 Removes or disables MIUI and HyperOS bloatware from the phone it runs on.
CTRL
dpkg-deb --root-owner-group --build "$B" "dist/xiaomi-debloater-termux_${VERSION}_all.deb"
tar czf "dist/xiaomi-debloater-termux-${VERSION}.tar.gz" xdebloat.py README.md install.sh
(cd dist && sha256sum ./* | sed 's# \./# #' > SHA256SUMS)
