"""Download the OpinionQA human-response files (Santurkar et al. 2023) for the waves we validate on.

    .venv/bin/python scripts/fetch_opinionqa.py            # default waves
    .venv/bin/python scripts/fetch_opinionqa.py --waves 27 42

Files land in data/opinionqa/raw/W<wave>/{info,metadata,responses}.csv, which is gitignored: the
OpinionQA repo has no license and the underlying Pew American Trends Panel data has its own terms,
so the raw data and the per-group answer distributions built from it are never committed. Only
derived scores (representativeness per question / group) go into the repo.

Source: CodaLab worksheet 0x6fb693719477478aac73fc07db333f69, bundle "human_resp". When this was
written, worksheets.codalab.org served an expired TLS certificate, so certificate verification is
off by default; pass --verify to turn it back on. The files are plain CSV and are only ever parsed
with the csv module, never executed.

Attribution: Pew Research Center, American Trends Panel. Pew Research Center bears no
responsibility for the analyses or interpretations of the data presented here.
"""

from __future__ import annotations

import argparse
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "opinionqa" / "raw"
BUNDLE = "0x050b7e72abb04d1f9b493c1743e580cf"
BASE = f"https://worksheets.codalab.org/rest/bundles/{BUNDLE}/contents/blob/human_resp"
FILES = ("info.csv", "metadata.csv", "responses.csv")
MAX_BYTES = 60_000_000  # largest wave's responses.csv is well under this

# Non-political topics by default (OpinionQA Table 1): automation and driverless vehicles, biomedical and
# food issues, America in 2050, trust in science, privacy and surveillance, relationships and family,
# economic inequality.
DEFAULT_WAVES = (27, 34, 41, 42, 49, 50, 54)

NOTICE = """Data: Pew Research Center American Trends Panel, as processed for OpinionQA (Santurkar et al. 2023,
"Whose Opinions Do Language Models Reflect?", https://github.com/tatsu-lab/opinions_qa).
Pew Research Center bears no responsibility for the analyses or interpretations of the data presented here.
Do not redistribute these files or attempt to re-identify respondents.
"""


def fetch(url: str, dest: Path, ctx: ssl.SSLContext | None) -> int:
    with urllib.request.urlopen(url, context=ctx, timeout=120) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise SystemExit(f"{url} is larger than {MAX_BYTES} bytes; refusing to save it")
    dest.write_bytes(data)
    return len(data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--waves", type=int, nargs="+", default=list(DEFAULT_WAVES))
    ap.add_argument("--verify", action="store_true", help="verify CodaLab's TLS certificate")
    ap.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = ap.parse_args()

    ctx = None if args.verify else ssl._create_unverified_context()  # noqa: S323 - see module docstring
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT.parent / "NOTICE.txt").write_text(NOTICE)
    total = 0
    for wave in args.waves:
        folder = OUT / f"W{wave}"
        folder.mkdir(exist_ok=True)
        for name in FILES:
            dest = folder / name
            if dest.exists() and not args.force:
                continue
            n = fetch(f"{BASE}/American_Trends_Panel_W{wave}/{name}", dest, ctx)
            total += n
            print(f"W{wave}/{name}: {n:,} bytes", flush=True)
    print(f"done: {total:,} bytes downloaded into {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
