# Xiaomi Debloater - Termux edition

Run the debloater directly on your Xiaomi/Redmi/POCO phone, no PC and no root.
It uses `bloatware.json` from the main project (auto-refreshed every 14 days) and talks to
the same phone through Android's **Wireless debugging** (Android 11+).

## Install (pick one)
- **Release package (easiest):** download `xiaomi-debloater-termux_*_all.deb` from the Releases page (tags named `termux-v*`), then
  `pkg install ./xiaomi-debloater-termux_*_all.deb` and run `xdebloat`.
- **From source:** follow *Setup* below and run `python xdebloat.py`.

## Setup
1. Install Termux from F-Droid or GitHub (not the Play Store build).
2. `sh install.sh` (or `pkg install python android-tools`).
3. Settings > Developer options > **Wireless debugging** > *Pair device with pairing code*.
   Keep Termux in split-screen so the pairing dialog stays open.
4. Run `python xdebloat.py` for the menu, or use commands.

Tips: run `termux-wake-lock` so Android doesn't kill Termux mid-run. Wireless debugging needs
Wi-Fi (a hotspot from another phone works). If it drops, repeat `connect` with the new port.

## Commands
```
python xdebloat.py pair IP:PAIR_PORT CODE
python xdebloat.py connect IP:CONNECT_PORT
python xdebloat.py status                      # connection + model + MIUI/HyperOS version
python xdebloat.py list --risk safe --os auto  # --os auto detects your OS version
python xdebloat.py remove                      # uninstall for user 0 (restorable)
python xdebloat.py disable                     # reversible alternative
python xdebloat.py enable
python xdebloat.py removed                     # what can be restored
python xdebloat.py restore com.example.app
python xdebloat.py restore --file ~/.xdebloat/backups/remove-YYYYMMDD-HHMMSS.txt
python xdebloat.py restore --all
python xdebloat.py update                      # force-refresh package list
```

Global flags (put before the command): `--dry-run` (change nothing), `--yes` (skip confirmation),
`--serial ID` (when several devices are connected).
Scripting example: `python xdebloat.py --yes remove --risk safe --os auto --all`

## Safety
- `danger` and `neverRemove` packages are blocked; `caution` ones show a warning.
- Every remove/disable first saves the package list to `~/.xdebloat/backups/`, and each action is logged to `~/.xdebloat/debloater.log`.
- Package names are validated before reaching the shell.
- Removals are per-user (`pm uninstall -k --user 0`); a factory reset restores everything.
- Back up your data first. Removing the wrong system package can require a factory reset.
