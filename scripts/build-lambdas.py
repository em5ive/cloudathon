"""Build Linux-compatible reproducible Lambda ZIPs from pure Python wheels on Windows."""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import subprocess
import sys
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CA_URLS = {"us-west-2-bundle.pem": "https://truststore.pki.rds.amazonaws.com/us-west-2/us-west-2-bundle.pem"}
CA_URLS.update({f"AmazonRootCA{number}.pem": f"https://www.amazontrust.com/repository/AmazonRootCA{number}.pem" for number in range(1, 5)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-certs", action="store_true", help="Refresh public AWS CA roots; review resulting checksums.")
    args = parser.parse_args()
    certs = ROOT / "backend/shared/certs"
    certs.mkdir(parents=True, exist_ok=True)
    manifest = {}
    previous_path = certs / "manifest.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    for name, url in CA_URLS.items():
        path = certs / name
        if args.refresh_certs or not path.exists():
            with urlopen(url, timeout=30) as response:
                data = response.read(128 * 1024)
            if b"-----BEGIN CERTIFICATE-----" not in data:
                raise ValueError(f"Invalid public CA download: {url}")
            path.write_bytes(data)
        # Parses the actual certificates; never trusts an HTML/error payload.
        ssl.create_default_context(cafile=str(path))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not args.refresh_certs and name in previous and previous[name]["sha256"] != digest:
            raise ValueError(f"CA checksum mismatch: {path}; inspect it before refreshing")
        manifest[name] = {"source": url, "sha256": digest}
    previous_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    target = ROOT / ".build/dependencies"
    # A new directory avoids stale dependencies without recursively deleting existing files.
    import tempfile
    target.parent.mkdir(exist_ok=True)
    # TemporaryDirectory removes its own contents on exit. Verify the parent
    # resolves inside this checkout before creating any cleanup target.
    target.parent.resolve().relative_to(ROOT)
    with tempfile.TemporaryDirectory(prefix="lambda-deps-", dir=target.parent) as temporary:
        target = Path(temporary).resolve()
        target.relative_to(ROOT)
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
                        "--python-version", "3.13", "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--abi", "cp313",
                        "--target", str(target), "-r", str(ROOT / "backend/requirements.txt")], check=True)
        artifacts = ROOT / "artifacts"
        artifacts.mkdir(exist_ok=True)
        hashes = {}
        for service in ["products", "orders", "support", "bootstrap"]:
            entries = {}
            for path in target.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    entries[path.relative_to(target).as_posix()] = path
            for folder in [ROOT / "backend/shared", ROOT / f"backend/{service}"]:
                for path in folder.rglob("*"):
                    # Bundle source and reviewed CA material only. Terminal notes,
                    # .env files, profiles and other incidental files stay out.
                    reviewed_ca = path.parent == certs and (path.name in CA_URLS or path.name == "manifest.json")
                    if path.is_file() and "__pycache__" not in path.parts and (path.suffix == ".py" or reviewed_ca):
                        entries[path.relative_to(ROOT / "backend").as_posix()] = path
            if service == "bootstrap":
                for path in (ROOT / "database").glob("*.sql"):
                    entries[f"database/{path.name}"] = path
            archive = artifacts / f"{service}.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
                for name, path in sorted(entries.items()):
                    if path.suffix.lower() in {".pyd", ".dll", ".so"}:
                        raise ValueError(f"Unexpected native binary in pure-Python package: {name}")
                    item = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                    item.compress_type = zipfile.ZIP_DEFLATED
                    item.create_system = 3
                    item.external_attr = 0o644 << 16
                    output.writestr(item, path.read_bytes())
            hashes[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
            print(f"Built {archive.name}: {archive.stat().st_size:,} bytes")
        (artifacts / "manifest.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
