"""Writes the frozen reference files for the pilot's design and prints the design hash.

Run from the folder that contains scenarios.py and pilot.py:  python golden/make_golden.py
The serializer lives in pilot.design_files(), so the code and golden/ can only agree when the
rendered stimuli, tools and preregistration are byte-identical. Regenerate only for a design
change the owner approved before the first paid call, and record it in RESEARCH.md section 13.
"""
import sys

sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pilot as P  # noqa: E402

OUT = Path(__file__).resolve().parent


def main():
    files = P.design_files()
    for name in P.DESIGN_FILES:
        (OUT / name).write_bytes(files[name].encode("utf-8"))
    digest = P.design_hash(files)
    (OUT / "DESIGN_HASH").write_bytes((digest + "\n").encode("utf-8"))
    print(f"{files['stimuli.jsonl'].count(chr(10))} stimuli; design hash {digest}")


if __name__ == "__main__":
    main()
