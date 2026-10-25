#!/usr/bin/env python3
"""
Xiaomi Debloater for Termux (CLI) - GPL-3.0
Uses bloatware.json from https://github.com/fadeltd/xiaomi-debloater

Runs on the SAME phone via Wireless debugging (Android 11+), no PC, no root.
Run without arguments for an interactive menu.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from types import SimpleNamespace

DB_URL = "https://raw.githubusercontent.com/fadeltd/xiaomi-debloater/main/bloatware.json"
# Data (package list cache, log, backups) lives in ~/.xdebloat so it works the same
# whether run from a git clone or from the installed package.
DATA = os.environ.get("XDEBLOAT_HOME") or os.path.join(os.path.expanduser("~"), ".xdebloat")
os.makedirs(DATA, exist_ok=True)
CACHE = os.path.join(DATA, "bloatware.json")
LOG = os.path.join(DATA, "debloater.log")
BACKUPS = os.path.join(DATA, "backups")
CACHE_MAX_AGE = 14 * 86400  # refresh package list if older than 14 days
PKG_RE = re.compile(r"^[A-Za-z0-9_.]+$")

CFG = SimpleNamespace(serial=None, dry=False, yes=False)


# ---- adb helpers -------------------------------------------------------

def adb(*args):
    cmd = ["adb"]
    if CFG.serial and args and args[0] not in ("devices", "pair", "connect", "disconnect"):
        cmd += ["-s", CFG.serial]
    try:
        p = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        sys.exit("adb not found. Run: pkg install android-tools")
    except subprocess.TimeoutExpired:
        return "adb timed out"
    return (p.stdout + p.stderr).strip()


def log(pkg, action, msg, ok):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{action}\t{pkg}\t{'OK' if ok else 'FAIL'}\t{msg}\n")


def require_device():
    out = adb("devices")
    ready = [l.split()[0] for l in out.splitlines()[1:] if l.strip() and l.split()[-1] == "device"]
    if not ready:
        sys.exit("No device connected. Use 'pair' then 'connect' first (see 'status').\n" + out)
    if CFG.serial is None:
        CFG.serial = ready[0]
        if len(ready) > 1:
            print(f"Multiple devices; using {CFG.serial}. Pick another with --serial.")
    elif CFG.serial not in ready:
        sys.exit(f"Device {CFG.serial} not connected/authorized.\n{out}")


def prop(key):
    return adb("shell", "getprop", key).strip()


def device_info():
    model = prop("ro.product.model")
    android = prop("ro.build.version.release")
    hos = prop("ro.mi.os.version.name")
    miui = prop("ro.miui.ui.version.name")
    os_name = f"HyperOS ({hos})" if hos else (f"MIUI ({miui})" if miui else "not a Xiaomi OS?")
    return model, android, os_name, hos, miui


def detect_os(db):
    """Map the phone's OS to a tag used in bloatware.json (None if unknown)."""
    tags = {t for p in db.values() for t in p.get("os", [])}
    hos, miui = prop("ro.mi.os.version.name"), prop("ro.miui.ui.version.name")
    guess = None
    if hos:
        m = re.search(r"(\d+)", hos)
        guess = f"hyperos{m.group(1)}" if m else "hyperos"
    elif miui:
        guess = "miui"
    return guess if guess in tags else None


# ---- package list ------------------------------------------------------

def load_db(update=False):
    stale = os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) > CACHE_MAX_AGE
    if update or stale or not os.path.exists(CACHE):
        try:
            with urllib.request.urlopen(DB_URL, timeout=30) as r:
                data = r.read()
            json.loads(data)
            with open(CACHE, "wb") as f:
                f.write(data)
            print("Package list updated.")
        except Exception as e:
            if not os.path.exists(CACHE):
                sys.exit(f"Could not download package list: {e}")
            print(f"Update failed ({e}); using cached list.")
    with open(CACHE, encoding="utf-8") as f:
        raw = json.load(f)
    load_db.version = raw.get("version", "?")
    return {p["package"]: p for p in raw["packages"]}


def pkg_set(*flags):
    out = adb("shell", "pm", "list", "packages", *flags)
    return {l[8:].strip() for l in out.splitlines() if l.startswith("package:")}


def matches(p, a):
    if a.risk != "all" and p["risk"] != a.risk:
        return False
    if a.category and p["category"] != a.category:
        return False
    if a.os and p.get("os") and a.os not in p["os"]:
        return False
    if a.search and a.search.lower() not in (p["package"] + p["description"]).lower():
        return False
    return True


def candidates(db, a, names):
    if a.os == "auto":
        a.os = detect_os(db)
        print(f"OS filter: {a.os or 'none (OS not in list tags)'}")
    return [db[n] for n in sorted(names & db.keys()) if matches(db[n], a)]


def show(rows):
    for i, p in enumerate(rows, 1):
        print(f"{i:>3}. [{p['risk']}] {p['package']}\n     {p['description']}")
    print(f"\n{len(rows)} package(s).")


def parse_selection(text, n):
    text = text.strip().lower()
    if text == "all":
        return list(range(n))
    picked = set()
    for part in text.replace(",", " ").split():
        if "-" in part:
            x, y = part.split("-", 1)
            if x.isdigit() and y.isdigit():
                picked.update(range(int(x) - 1, int(y)))
        elif part.isdigit():
            picked.add(int(part) - 1)
    return sorted(i for i in picked if 0 <= i < n)


def save_backup(action, names):
    os.makedirs(BACKUPS, exist_ok=True)
    path = os.path.join(BACKUPS, f"{action}-{time.strftime('%Y%m%d-%H%M%S')}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(names) + "\n")
    print(f"Saved list to {path} (restore with: restore --file <path>)")


def apply(action, names, cmd_fn, ok_fn):
    names = [n for n in names if PKG_RE.match(n)]
    if not names:
        print("No valid package names.")
        return
    if action in ("remove", "disable") and names and not CFG.dry:
        save_backup(action, names)
    done = 0
    for n in names:
        if CFG.dry:
            print(f"DRY  {action} {n}")
            continue
        out = cmd_fn(n)
        ok = ok_fn(out)
        done += ok
        log(n, action, out, ok)
        print(("OK   " if ok else "FAIL ") + n + ("" if ok else f"  ({out})"))
    if not CFG.dry:
        print(f"\n{done}/{len(names)} succeeded. Reboot if something looks off.")


# ---- commands ----------------------------------------------------------

def cmd_pair(a):
    print(adb("pair", a.hostport, a.code))


def cmd_connect(a):
    print(adb("connect", a.hostport))


def cmd_status(a):
    print(adb("devices"))
    if "device" in adb("devices").split("attached", 1)[-1]:
        require_device()
        model, android, os_name, _, _ = device_info()
        print(f"Model: {model}\nAndroid: {android}\nOS: {os_name}")


def cmd_update(a):
    load_db(update=True)


def cmd_list(a):
    require_device()
    show(candidates(load_db(), a, pkg_set("--user", "0")))


def _destructive(a, label, cmd_fn, ok_fn, pool_flags):
    require_device()
    rows = [p for p in candidates(load_db(), a, pkg_set("--user", "0", *pool_flags))
            if p["risk"] != "danger" and not p.get("neverRemove")]
    if not rows:
        print("Nothing to do with these filters.")
        return
    if getattr(a, "all", False):
        chosen = rows
        print(f"{len(chosen)} package(s) selected.")
    else:
        show(rows)
        sel = parse_selection(input(f"Numbers to {label} (e.g. 1 3 5-8, 'all', Enter = cancel): "), len(rows))
        if not sel:
            return
        chosen = [rows[i] for i in sel]
    if any(p["risk"] == "caution" for p in chosen):
        print("\nWARNING: selection includes 'caution' packages.")
    if not (CFG.yes or CFG.dry) and input(f"{label.capitalize()} {len(chosen)} package(s)? (yes/no): ").strip().lower() != "yes":
        print("Cancelled.")
        return
    apply(label, [p["package"] for p in chosen], cmd_fn, ok_fn)


def cmd_remove(a):
    _destructive(a, "remove",
                 lambda n: adb("shell", "pm", "uninstall", "-k", "--user", "0", n),
                 lambda o: "Success" in o, [])


def cmd_disable(a):
    _destructive(a, "disable",
                 lambda n: adb("shell", "pm", "disable-user", "--user", "0", n),
                 lambda o: "disabled" in o.lower(), ["-e"])


def cmd_enable(a):
    require_device()
    db = load_db()
    names = sorted(pkg_set("--user", "0", "-d"))
    if not names:
        print("No disabled packages.")
        return
    rows = [db.get(n, {"package": n, "risk": "?", "description": "(not in list)"}) for n in names]
    if getattr(a, "all", False):
        chosen = rows
    else:
        show(rows)
        sel = parse_selection(input("Numbers to enable (Enter = cancel): "), len(rows))
        chosen = [rows[i] for i in sel]
    apply("enable", [p["package"] for p in chosen],
          lambda n: adb("shell", "pm", "enable", "--user", "0", n),
          lambda o: "enabled" in o.lower())


def restorable(db):
    return sorted((pkg_set("-u", "--user", "0") - pkg_set("--user", "0")) & db.keys())


def cmd_removed(a):
    require_device()
    db = load_db()
    gone = restorable(db)
    for n in gone:
        print(f"{n}\n     {db[n]['description']}")
    print(f"\n{len(gone)} restorable package(s).")


def cmd_restore(a):
    require_device()
    names = list(a.packages)
    if a.file:
        with open(a.file, encoding="utf-8") as f:
            names += [l.strip() for l in f if l.strip()]
    if a.all:
        names += restorable(load_db())
    if not names:
        sys.exit("Nothing to restore. Give package names, --file, or --all.")
    apply("restore", sorted(set(names)),
          lambda n: adb("shell", "cmd", "package", "install-existing", n),
          lambda o: "installed" in o.lower())


# ---- interactive menu --------------------------------------------------

def ask_filters():
    risk = input("Risk [safe/caution/all] (Enter = safe): ").strip().lower() or "safe"
    if risk not in ("safe", "caution", "danger", "all"):
        risk = "safe"
    osf = input("OS filter [auto/miui/hyperos3] (Enter = none): ").strip().lower() or None
    search = input("Search text (Enter = none): ").strip() or None
    return SimpleNamespace(risk=risk, category=None, os=osf, search=search, all=False)


def menu():
    while True:
        print("\n=== Xiaomi Debloater (Termux) ===")
        print("1 Pair   2 Connect   3 Status   4 List   5 Remove   6 Disable")
        print("7 Enable   8 Restore removed   9 Update list   0 Exit")
        c = input("> ").strip()
        if c == "0":
            return
        if c == "1":
            cmd_pair(SimpleNamespace(hostport=input("IP:pairing port: ").strip(),
                                     code=input("Pairing code: ").strip()))
        elif c == "2":
            cmd_connect(SimpleNamespace(hostport=input("IP:connect port: ").strip()))
        elif c == "3":
            cmd_status(None)
        elif c == "4":
            cmd_list(ask_filters())
        elif c == "5":
            cmd_remove(ask_filters())
        elif c == "6":
            cmd_disable(ask_filters())
        elif c == "7":
            cmd_enable(SimpleNamespace(all=False))
        elif c == "8":
            cmd_removed(None)
            names = input("Package(s) to restore (space separated, Enter = none): ").split()
            if names:
                cmd_restore(SimpleNamespace(packages=names, file=None, all=False))
        elif c == "9":
            cmd_update(None)


def main():
    ap = argparse.ArgumentParser(description="Xiaomi Debloater for Termux")
    ap.add_argument("--serial", help="adb device serial (when several are connected)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be done, change nothing")
    ap.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("pair", help="pair (host:port + 6-digit code)")
    s.add_argument("hostport")
    s.add_argument("code")
    s.set_defaults(fn=cmd_pair)

    s = sub.add_parser("connect", help="connect (host:port)")
    s.add_argument("hostport")
    s.set_defaults(fn=cmd_connect)

    sub.add_parser("status", help="show connection and phone info").set_defaults(fn=cmd_status)
    sub.add_parser("update", help="download latest package list").set_defaults(fn=cmd_update)

    for name, fn, hlp in (("list", cmd_list, "show installed bloatware"),
                          ("remove", cmd_remove, "uninstall for user 0 (restorable)"),
                          ("disable", cmd_disable, "disable packages (reversible)")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("--risk", choices=["safe", "caution", "danger", "all"], default="safe")
        s.add_argument("--category", choices=["bloatware", "oem", "system", "user"])
        s.add_argument("--os", help="miui, hyperos3 or auto (detect from phone)")
        s.add_argument("--search")
        if name != "list":
            s.add_argument("--all", action="store_true", help="select every match, no numbered prompt")
        s.set_defaults(fn=fn)

    s = sub.add_parser("enable", help="re-enable disabled packages")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_enable)

    sub.add_parser("removed", help="list restorable packages").set_defaults(fn=cmd_removed)

    s = sub.add_parser("restore", help="restore removed package(s)")
    s.add_argument("packages", nargs="*")
    s.add_argument("--file", help="restore every package in a saved backup list")
    s.add_argument("--all", action="store_true", help="restore everything that was removed")
    s.set_defaults(fn=cmd_restore)

    args = ap.parse_args()
    CFG.serial, CFG.dry, CFG.yes = args.serial, args.dry_run, args.yes
    if not args.cmd:
        menu()
    else:
        args.fn(args)


if __name__ == "__main__":
    main()
