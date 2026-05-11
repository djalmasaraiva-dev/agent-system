"""One-shot conversion: SVG → PNG @ 1600px for Medium upload.

Output goes into ./png-for-medium/ (kept out of git via .gitignore).

Usage:
    cd article/
    uv run --with cairosvg python convert_svgs_to_png.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cairosvg

HERE = Path(__file__).parent
OUT = HERE / "png-for-medium"
OUT.mkdir(exist_ok=True)


def main() -> int:
    svgs = sorted(HERE.glob("figure-*.svg"))
    if not svgs:
        print("No SVGs found.")
        return 1

    for svg in svgs:
        png = OUT / (svg.stem + ".png")
        cairosvg.svg2png(url=str(svg), write_to=str(png), output_width=1600)
        print(f"  ✓ {svg.name} → {png.relative_to(HERE)}  ({png.stat().st_size / 1024:.0f} KB)")

    # Also copy existing PNGs over for upload convenience.
    import shutil

    for png in HERE.glob("figure-*.png"):
        dst = OUT / png.name
        if not dst.exists():
            shutil.copy2(png, dst)
            print(f"  · {png.name} (copied PNG, already raster)")

    print(f"\n{len(list(OUT.glob('*.png')))} files in {OUT.relative_to(HERE)}/ — ready for Medium upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
