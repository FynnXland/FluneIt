"""Guard: no credentials and no key files in the repository.

Run from the repository root. Exits with 1 if something is found.
"""
import re
import subprocess
import sys

# Built from parts so this file does not report itself.
PATTERN = re.compile(r"\b(?:" + "|".join([
    "gh" + r"[opsur]_[A-Za-z0-9]{30,}", "github" + r"_pat_[A-Za-z0-9_]{30,}",
    "sk" + r"-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}", "AI" + r"za[0-9A-Za-z_-]{35}",
    "AK" + r"IA[0-9A-Z]{16}", "xo" + r"x[abprs]-[A-Za-z0-9-]{10,}",
    "sk" + r"_live_[A-Za-z0-9]{20,}", "hf" + r"_[A-Za-z0-9]{30,}",
    "npm" + r"_[A-Za-z0-9]{36}", "pypi" + r"-[A-Za-z0-9_-]{50,}",
]) + r")|-----BEGIN [A-Z ]*PRI" + "VATE KEY")
# .env and .env.local are forbidden, .env.example/.sample/.template are fine.
KEY_FILE = re.compile(
    r"(^|/)\.env(\.(?!(example|sample|template)$)[^/]+)?$|\.(pem|key|p12|pfx|jks|keystore)$")
# Personal data that must never be published: the app's own settings file.
PRIVATE_FILE = re.compile(r"(^|/)config\.json$")

raw = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
files = [f for f in raw.decode("utf-8").split("\0") if f]
findings = [f"key file tracked: {f}" for f in files if KEY_FILE.search(f)]
findings += [f"personal settings tracked: {f}" for f in files if PRIVATE_FILE.search(f)]
for name in files:
    try:
        with open(name, encoding="utf-8") as fh:
            text = fh.read()
    except (UnicodeDecodeError, OSError):
        continue  # binary file
    for m in PATTERN.finditer(text):
        findings.append(f"{name}:{text.count(chr(10), 0, m.start()) + 1}: "
                        f"looks like {m.group(0)[:4]}...")
print("\n".join(findings) or "no findings")
sys.exit(1 if findings else 0)
