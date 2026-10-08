"""Narrow host integration. Run on one.majjix.com after building the image."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

root = Path("/docker")
source = root / "appdata/einkartifact/source"
ignore = root / ".gitignore"
ignore_text = ignore.read_text()
if "/backups/einkartifact/" not in ignore_text.splitlines():
    ignore.write_text(ignore_text.rstrip() + "\n/backups/einkartifact/\n")
backup = (
    root
    / "backups/einkartifact"
    / ("host-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
)
backup.mkdir(parents=True, mode=0o700)
for name in ("docker-compose.yml", "export-configs-for-git.sh", ".gitignore"):
    shutil.copy2(root / name, backup / name)
    os.chmod(backup / name, 0o600)
    if name == ".gitignore":
        (backup / name).write_text(ignore_text)
compose = root / "docker-compose.yml"
text = compose.read_text()
if "\n  einkartifact:" in text:
    raise SystemExit("Service already exists; review instead of overwriting")
fragment = (source / "deployment/compose-service.yml").read_text()
fragment = fragment[fragment.index("  einkartifact:") :]
if text.count("services:\n") != 1:
    raise SystemExit("Unexpected Compose structure")
compose.write_text(text.replace("services:\n", "services:\n" + fragment, 1))
shutil.copy2(
    source / "deployment/site.example.json", root / "appdata/einkartifact/config/site.json"
)
shutil.copytree(source / "art", root / "appdata/einkartifact/art", dirs_exist_ok=True)
script = root / "export-configs-for-git.sh"
text = script.read_text()
block = """export_einkartifact() {
  local src="$BASE/einkartifact" dst="$OUT/einkartifact"
  reset_dir "$dst"
  safe_copy "$src/config/site.json" "$dst/site.json" || true
  safe_copy "$src/config/release.json" "$dst/release.json" || true
  safe_copy "$src/art/catalog.json" "$dst/catalog.json" || true
  safe_copy "$src/art/FUGLERAMME-ATTRIBUTION.md" "$dst/ATTRIBUTION.md" || true
  note "einkartifact" "high" "allowlisted config and credits; tokens and database excluded"
}

"""
if "export_einkartifact()" not in text:
    text = text.replace("main() {\n", block + "main() {\n", 1)
    text = text.replace("  export_netdata\n", "  export_netdata\n  export_einkartifact\n", 1)
    script.write_text(text)
os.chmod(root / "backups/einkartifact", 0o700)
for directory, subdirectories, files in os.walk(root / "backups/einkartifact"):
    os.chown(directory, 1000, 1000)
    for name in files:
        os.chown(Path(directory) / name, 1000, 1000)
os.chmod(root / "appdata/einkartifact/data", 0o700)
print(
    json.dumps(
        {"backup": str(backup), "compose": "service added", "config_export": "allowlisted only"}
    )
)
