"""Verify ZIP hashes, source freshness, Python 3.13 syntax and safe package contents."""
import ast
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / "artifacts/manifest.json").read_text(encoding="utf-8"))
    for service in ("products", "orders", "support", "bootstrap"):
        archive_path = ROOT / f"artifacts/{service}.zip"
        assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == manifest[archive_path.name], f"Hash mismatch: {service}"
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None, f"Corrupt archive: {service}"
            names = archive.namelist()
            required = {f"{service}/handler.py", "shared/db.py", "shared/http.py", "pg8000/dbapi.py", "shared/certs/us-west-2-bundle.pem"}
            if service == "bootstrap":
                required.update({"database/schema.sql", "database/seed.sql"})
            assert required <= set(names), f"Missing required entries: {service}"
            for name in names:
                assert not name.startswith("/") and ".." not in Path(name).parts, f"Unsafe ZIP path: {name}"
                assert Path(name).suffix not in {".pyd", ".dll", ".so", ".pyc", ".key", ".tfstate"}, f"Unexpected binary/private file: {name}"
                assert not any(part.startswith(".") for part in Path(name).parts), f"Hidden artifact: {name}"
                if name.endswith(".py"):
                    ast.parse(archive.read(name), filename=name, feature_version=(3, 13))
                local = ROOT / (name if name.startswith("database/") else "backend/" + name)
                if local.is_file():
                    assert archive.read(name) == local.read_bytes(), f"Stale packaged source: {name}"
                if name.startswith((service + "/", "shared/")):
                    assert name.endswith((".py", ".pem")) or name == "shared/certs/manifest.json", f"Incidental backend file bundled: {name}"
            source = ast.parse(archive.read(f"{service}/handler.py"), feature_version=(3, 13))
            assert any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "handler" for item in source.body), f"Handler missing: {service}"
            print(f"PASS: {service}.zip — hash, CRC, source freshness, Python 3.13 syntax, handler and safe contents")
    print("Runtime imports, TLS handshakes and actual Lambda execution are not tested by package inspection.")


if __name__ == "__main__":
    main()
