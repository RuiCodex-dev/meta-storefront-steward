"""Pre-commit secret scan: regex patterns over staged files (and, with --all, the whole history).

Exit 1 on any hit. Prints file and pattern name only, never the matched value.
Runs gitleaks too when it is installed.
"""
import re
import shutil
import subprocess
import sys

PATTERNS = {
    "meta_api_key": r"LLM_[A-Za-z0-9|_\-]{20,}",
    "hf_token": r"hf_[A-Za-z0-9]{20,}",
    "openai_like": r"sk-[A-Za-z0-9_\-]{20,}",
    "google_api_key": r"AIza[0-9A-Za-z_\-]{30,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "service_account": r'"client_email"\s*:\s*"[^"]+gserviceaccount\.com"',
    "linear_key": r"lin_api_[A-Za-z0-9]{20,}",
    "github_token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "play_review_link": r"reviewId=[A-Za-z0-9_\-]{10,}",
    "play_developer_id": r"pubsite_prod_\d{10,}",
}


def staged_text() -> dict:
    files = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                           capture_output=True, text=True).stdout.split()
    out = {}
    for f in files:
        blob = subprocess.run(["git", "show", f":{f}"], capture_output=True).stdout
        out[f] = blob.decode("utf-8", "replace")
    return out


def main() -> int:
    hits = []
    if "--all" in sys.argv:
        log = subprocess.run(["git", "log", "-p", "--all"], capture_output=True).stdout.decode("utf-8", "replace")
        texts = {"<history>": log}
    else:
        texts = staged_text()
    for f, t in texts.items():
        if f.endswith("secret_scan.py"):
            continue
        for name, pat in PATTERNS.items():
            if re.search(pat, t):
                hits.append((f, name))
    if shutil.which("gitleaks") or shutil.os.path.exists(r"C:\Users\Admin\go\bin\gitleaks.exe"):
        exe = shutil.which("gitleaks") or r"C:\Users\Admin\go\bin\gitleaks.exe"
        args = [exe, "git", "--no-banner", "--redact"] if "--all" in sys.argv else [exe, "git", "--staged", "--no-banner", "--redact"]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode not in (0,):
            hits.append(("gitleaks", r.stdout.strip()[-300:] or r.stderr.strip()[-300:]))
    for f, name in hits:
        print(f"SECRET-SCAN HIT: {f}: {name}")
    print("secret scan:", "FAIL" if hits else "clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
