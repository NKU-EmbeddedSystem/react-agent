"""Regex search over the text layer, returning page numbers and bboxes.

Searches text blocks by default (good for captions and headings); --words
searches single words (good for compound labels such as "3aj").
Pages without a text layer (scanned) or outlined text in vector schemes will
not match; look at the page images for those.

Usage: python -m pipeline.pagetools.find_text <ws> <main|si> <regex> [--words] [--pages 3-10] [--case] [--max 60]
"""

from __future__ import annotations

import argparse
import json
import re

from .common import die, fmt_bbox, load_manifest


def page_range(spec: str | None, count: int) -> range:
    if not spec:
        return range(1, count + 1)
    try:
        a, _, b = spec.partition("-")
        return range(int(a), (int(b) if b else int(a)) + 1)
    except ValueError:
        die(f"bad --pages {spec!r}; expected N or A-B")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ws")
    ap.add_argument("doc", choices=["main", "si"])
    ap.add_argument("pattern")
    ap.add_argument("--words", action="store_true", help="match single words instead of blocks")
    ap.add_argument("--pages", help="N or A-B (1-based)")
    ap.add_argument("--case", action="store_true", help="case-sensitive")
    ap.add_argument("--max", type=int, default=60)
    args = ap.parse_args()

    doc_dir, manifest = load_manifest(args.ws, args.doc)
    rx = re.compile(args.pattern, 0 if args.case else re.IGNORECASE)
    kind = "words" if args.words else "blocks"
    hits = 0
    for no in page_range(args.pages, manifest["page_count"]):
        tag = manifest["pages"][no - 1]["tag"]
        for line in open(doc_dir / kind / f"{tag}.jsonl", encoding="utf-8"):
            item = json.loads(line)
            text = " ".join(item["text"].split())
            if not text or not rx.search(text):
                continue
            hits += 1
            if hits > args.max:
                print(f"... more than {args.max} hits; narrow the pattern or --pages")
                return
            print(f"p{no:<4} {fmt_bbox(item['bbox'])}  {text[:160]}")
    if not hits:
        print("no hits")


if __name__ == "__main__":
    main()
