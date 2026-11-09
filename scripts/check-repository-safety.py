"""Read-only Git artifact/credential checks; findings never include secret values."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import json

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIRS = {".build", ".terraform", ".aws", ".secrets", "artifacts", "reports", "node_modules", ".venv", "User Data"}
PRIVATE_NAMES = {"credentials", "Cookies", "Cookies-journal", "Login Data", "Login Data-journal", "Web Data", "Web Data-journal", "Local State", "secrets.json"}
RULES = {
    "AWS access key ID": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Private key PEM": re.compile(r"^-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----", re.MULTILINE),
    "AWS credential assignment": re.compile(r"(?im)^\s*[\"']?(?:aws_secret_access_key|aws_session_token|SecretAccessKey|SessionToken)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{20,}"),
}
IGNORE_PROBES = [".build/profile/Network/Cookies", "terraform/.terraform/provider", "terraform/example.tfstate",
                 "terraform/example.tfstate.backup", "terraform/example.tfplan", "terraform/terraform.tfvars",
                 ".aws/credentials", ".secrets/generated.json", ".env", "session-token.txt", "reports/workshop.json",
                 "artifacts/support.zip", "User Data/Default/Cookies", "browser-profile-test/Local State", "private.key"]


def git_files(*arguments):
    result = subprocess.run(["git", "ls-files", "-z", *arguments], cwd=ROOT, capture_output=True, check=True)
    return [value for value in result.stdout.decode("utf-8").split("\0") if value]


def private_path(name):
    path = PurePosixPath(name)
    return (bool(GENERATED_DIRS.intersection(path.parts)) or path.name in PRIVATE_NAMES or
            path.name.endswith((".tfstate", ".tfplan", ".plan", ".key", ".p12", ".pfx", ".jks", ".secrets.json")) or
            ".tfstate." in path.name or
            path.name.endswith((".tfvars", ".tfvars.json")) or
            (path.name.startswith(".env") and path.name != ".env.example") or
            path.name.startswith(("session-token", "session_token")))


def inspect():
    tracked = git_files()
    candidates = sorted(set(tracked + git_files("--others", "--exclude-standard")))
    findings = [{"file": name, "rule": "Sensitive/generated path is tracked"} for name in tracked if private_path(name)]
    scanned = 0
    for name in candidates:
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            contents = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        scanned += 1
        for rule, pattern in RULES.items():
            if pattern.search(contents):
                findings.append({"file": name, "rule": rule})
    ignore = subprocess.run(["git", "check-ignore", "-z", "--stdin", "--no-index"], cwd=ROOT,
                            input=("\0".join(IGNORE_PROBES) + "\0").encode("utf-8"), capture_output=True, check=False)
    if ignore.returncode not in {0, 1}:
        raise RuntimeError("Git ignore verification failed; no credential values were printed")
    ignored = set(ignore.stdout.decode("utf-8").split("\0"))
    for probe in IGNORE_PROBES:
        if probe not in ignored:
            findings.append({"file": probe, "rule": "Required ignore pattern is missing"})
    return {"status": "FAIL" if findings else "PASS", "tracked_files": len(tracked), "text_files_scanned": scanned,
            "ignore_probes": len(IGNORE_PROBES), "findings": findings,
            "limits": "Recognized credential patterns and Git index/current source only; not a proof against every secret format or a complete Git history audit. No files or index entries are deleted or changed."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/repository-safety.json")
    args = parser.parse_args()
    report = inspect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
