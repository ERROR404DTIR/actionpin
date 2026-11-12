#!/usr/bin/env python3
"""actionpin - audit and pin GitHub Actions to commit SHAs. Zero dependencies."""
import argparse
import glob
import os
import re
import sys
import urllib.error
import urllib.request

USES = re.compile(r"^(?P<pre>\s*(?:-\s*)?uses:\s*)(?P<name>[^\s@#'\"]+)@(?P<ref>[^\s#'\"]+)(?P<post>\s*#.*)?\s*$")
SHA = re.compile(r"^[0-9a-f]{40}$")
TAG = re.compile(r"^v?\d+(\.\d+)*([-+.\w]*)$")
TTY = sys.stdout.isatty()


def paint(code, s):
    return f"\033[{code}m{s}\033[0m" if TTY else s


def find_files(root):
    out = []
    for ext in ("yml", "yaml"):
        out += glob.glob(os.path.join(root, ".github", "workflows", "*." + ext))
        out += glob.glob(os.path.join(root, ".github", "actions", "**", "action." + ext), recursive=True)
    return sorted(set(out))


def scan(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    hits = []
    for i, line in enumerate(lines):
        m = USES.match(line)
        if m and not m["name"].startswith(("./", "docker://")):
            hits.append((i, m))
    return lines, hits


def resolve(repo, ref, token, cache):
    key = (repo, ref)
    if key not in cache:
        url = f"https://api.github.com/repos/{repo}/commits/{ref}"
        headers = {"Accept": "application/vnd.github.sha", "User-Agent": "actionpin/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
                sha = r.read().decode().strip()
            cache[key] = sha if SHA.match(sha) else None
        except (urllib.error.URLError, OSError):
            cache[key] = None
    return cache[key]


def main():
    ap = argparse.ArgumentParser(prog="actionpin", description="Find unpinned GitHub Actions and pin them to commit SHAs.")
    ap.add_argument("path", nargs="?", default=".", help="repo root (default: .)")
    ap.add_argument("--pin", action="store_true", help="resolve SHAs and show the proposed changes (dry run)")
    ap.add_argument("--write", action="store_true", help="with --pin: apply the changes to the files")
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), help="GitHub token (default: $GITHUB_TOKEN)")
    a = ap.parse_args()

    files = find_files(a.path)
    if not files:
        print("no workflow files found in .github/workflows")
        return 0
    cache, total, unpinned, failed = {}, 0, 0, 0
    for path in files:
        lines, hits = scan(path)
        changed = False
        for i, m in hits:
            total += 1
            if SHA.match(m["ref"]):
                continue
            unpinned += 1
            kind = "tag" if TAG.match(m["ref"]) else "branch"
            loc = f"{os.path.relpath(path, a.path)}:{i + 1}"
            tag = paint("33", kind) if kind == "tag" else paint("31", kind + " (mutable!)")
            line = f"{loc:<40} {m['name']}@{m['ref']}  [{tag}]"
            if a.pin:
                sha = resolve("/".join(m["name"].split("/")[:2]), m["ref"], a.token, cache)
                if not sha:
                    failed += 1
                    print(line + paint("31", "  -> could not resolve"))
                    continue
                print(line + paint("32", f"  -> {sha[:12]}"))
                lines[i] = f"{m['pre']}{m['name']}@{sha}  # {m['ref']}"
                changed = True
            else:
                print(line)
        if changed and a.write:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
    print(f"\n{total} action refs, {total - unpinned} pinned, {unpinned} unpinned" + (f", {failed} unresolved" if failed else ""))
    if a.pin and not a.write and unpinned - failed:
        print("dry run - add --write to apply")
    if a.pin and a.write:
        return 1 if failed else 0
    return 1 if unpinned else 0


if __name__ == "__main__":
    sys.exit(main())
