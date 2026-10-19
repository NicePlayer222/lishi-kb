#!/usr/bin/env python3
"""Push local files to GitHub through api.github.com (no git push).

Usage:
    python3 scripts/api_push.py <path> [<path> ...]

The script reads a GitHub token from GITHUB_TOKEN/GH_TOKEN or ~/.git-credentials.
It never prints the token. Existing remote files are updated by SHA; identical
content is skipped. After uploading, it deletes inbox/command.json if present.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OWNER = "NicePlayer222"
REPO = "lishi-kb"
BRANCH = "main"
API = "https://api.github.com"
TIMEOUT = 30


def load_token():
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value.strip()
    path = os.path.expanduser("~/.git-credentials")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                match = re.search(r"https://[^:]+:([^@]+)@github\.com", line.strip())
                if match:
                    return match.group(1)
    sys.exit("ERROR: no GitHub token in GITHUB_TOKEN/GH_TOKEN or ~/.git-credentials")


TOKEN = load_token()


def api(method, path, payload=None):
    url = API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", "token " + TOKEN)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("User-Agent", "lishi-runner-api")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw) if raw else None
        except Exception:
            body = raw.decode("utf-8", "replace")
        return exc.code, body
    except Exception as exc:  # network/TLS/timeout
        return None, f"{type(exc).__name__}: {exc}"


def api_retry(method, path, payload=None, attempts=3):
    last = None
    for attempt in range(attempts):
        code, body = api(method, path, payload)
        if code in (200, 201, 204, 404):
            return code, body
        last = (code, body)
        if code in (401, 403, 409, 422):
            break
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{method} {path} failed: {last}")


def content_path(path):
    return urllib.parse.quote(path, safe="/")


def get_file(path):
    code, body = api_retry(
        "GET", f"/repos/{OWNER}/{REPO}/contents/{content_path(path)}?ref={BRANCH}"
    )
    if code == 404:
        return None
    if code != 200:
        raise RuntimeError(f"GET {path}: {code} {body}")
    return body


def put_file(path, content, message):
    remote = get_file(path)
    if remote and remote.get("content"):
        try:
            remote_bytes = base64.b64decode(remote["content"])
        except Exception:
            remote_bytes = None
        if remote_bytes == content:
            print(f"SKIP {path} (unchanged)")
            return
    payload = {
        "message": message,
        "content": base64.b64encode(content).decode("ascii"),
        "branch": BRANCH,
    }
    if remote:
        payload["sha"] = remote["sha"]
    code, body = api_retry(
        "PUT", f"/repos/{OWNER}/{REPO}/contents/{content_path(path)}", payload
    )
    print(f"PUT {path} -> {code}")
    return body


def delete_file(path, message):
    remote = get_file(path)
    if not remote:
        print(f"SKIP delete {path} (not found)")
        return
    payload = {"message": message, "sha": remote["sha"], "branch": BRANCH}
    code, body = api_retry(
        "DELETE", f"/repos/{OWNER}/{REPO}/contents/{content_path(path)}", payload
    )
    print(f"DELETE {path} -> {code}")


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: api_push.py <path> [<path> ...]")
    for path in sys.argv[1:]:
        if not os.path.isfile(path):
            sys.exit(f"ERROR: missing local file: {path}")
        with open(path, "rb") as handle:
            content = handle.read()
        put_file(path, content, f"api: upload {path}")
    delete_file("inbox/command.json", "api: consume command")
    print("DONE")


if __name__ == "__main__":
    main()