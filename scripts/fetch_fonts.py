"""Download DejaVu Sans (regular + bold) into assets/fonts/ for the PDF report.

    python scripts/fetch_fonts.py
"""
import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FILES = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf"]
MIRRORS = [
    "https://cdn.jsdelivr.net/npm/dejavu-fonts-ttf@2.37.3/ttf/",
    "https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/mpl-data/fonts/ttf/",
]


def _get(name: str, out: Path) -> None:
    last = None
    for base in MIRRORS:
        try:
            urllib.request.urlretrieve(base + name, out)
            if out.stat().st_size > 0:
                return
        except Exception as e:  # noqa: BLE001
            last = e
    raise last or RuntimeError("no mirror worked")


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        out = DEST / name
        if out.exists() and out.stat().st_size > 0:
            print(f"ok    {name}")
            continue
        print(f"fetch {name} ...")
        try:
            _get(name, out)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED: {e}\nDownload {name} manually into {DEST}", file=sys.stderr)
            return 1
    print(f"done  -> {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
