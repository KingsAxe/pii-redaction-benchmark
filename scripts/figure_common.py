"""Small Pillow helpers and input provenance for offline benchmark figures."""
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

from PIL import ImageFont

if __package__:
    from .runner_common import ROOT, require_custom_freeze, write_json
else:
    from runner_common import ROOT, require_custom_freeze, write_json

FIGURES = ROOT / "results/figures"
FONT_PATHS = {"regular": Path("C:/Windows/Fonts/arial.ttf"),
              "bold": Path("C:/Windows/Fonts/arialbd.ttf"),
              "mono": Path("C:/Windows/Fonts/consola.ttf")}
INK = "#17212B"


def font(size, kind="regular"):
    return ImageFont.truetype(str(FONT_PATHS[kind]), size)


def file_record(path):
    path = Path(path).resolve()
    try:
        name = path.relative_to(ROOT).as_posix()
    except ValueError:
        name = str(path)
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_evidence():
    record = json.loads((ROOT / "results/reporting_integrity.json").read_text(encoding="utf-8"))
    expected = {name: values["after_sha256"] for name, values in record["protected_files"].items()}
    expected.update({f"results/{name}": values["after_sha256"]
                     for name, values in record["report_comparison"]["reports"].items()})
    for name, digest in expected.items():
        if file_record(ROOT / name)["sha256"] != digest:
            raise ValueError(f"Evidence hash mismatch: {name}")
    for config in ("custom", "custom_generic"):
        require_custom_freeze(config=config)


def save_figure(image, filename, name, inputs, command, **description):
    FIGURES.mkdir(parents=True, exist_ok=True)
    manifest_path = FIGURES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    path = FIGURES / filename
    previous = manifest.get("figures", {}).get(name, {})
    if path.exists() and path.name not in previous.get("outputs", []):
        raise ValueError(f"Refusing to overwrite an unrelated image: {path}")
    image.save(path, dpi=(300, 300))
    entry = {"inputs": [file_record(p) for p in inputs],
             "fonts": [file_record(p) for p in FONT_PATHS.values()],
             "reproduction_command": command, "outputs": [path.name],
             "output_sha256": file_record(path)["sha256"],
             "dimensions_px": list(image.size), **description}
    manifest.update({"renderer": "Pillow", "pillow_version": version("pillow"), "seed": 42,
                     "svg_status": "Not generated: Pillow does not export SVG"})
    manifest.setdefault("figures", {})[name] = entry
    write_json(manifest_path, manifest)
    print(path)
    return path
