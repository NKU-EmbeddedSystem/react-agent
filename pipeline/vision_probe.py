"""Small opt-in image transport canary; answers exist only in the image and controller memory.

Run on the server with ``python -m pipeline.vision_probe --out work/vision-probe/<run>``.
The controller rejects a result if the model used tools: file inspection must not masquerade as vision.
"""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .codex import run_codex
from .config import CodexConfig
from .papers import write_json


def run(out: Path):
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    image = Image.new("RGB", (1100, 300), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
    colors = {"red": "#d62828", "blue": "#1459c7", "green": "#21833c"}
    order = list(colors)
    secrets.SystemRandom().shuffle(order)
    codes = ["".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(7)) for _ in order]
    expected = {"codes": codes, "colors": order}
    for i, (color, code) in enumerate(zip(order, codes)):
        x = 25 + i * 360
        draw.rectangle((x, 30, x + 320, 270), outline=colors[color], width=12)
        draw.ellipse((x + 125, 55, x + 195, 125), fill=colors[color])
        draw.text((x + 25, 165), code, fill="black", font=font)
    image.save(out / "canary.png")
    schema = {"type": "object", "properties": {key: {"type": "array", "items": {"type": "string"}}
                                                for key in expected},
              "required": list(expected), "additionalProperties": False}
    write_json(out / "schema.json", schema)
    scratch = out / "scratch"
    scratch.mkdir()
    result = run_codex("Read only the attached image. Do not use any tools, commands, files or agents. "
                       "Return the seven-character codes in the three panels from left to right, and the "
                       "English color names of their borders in the same order. Return only the JSON object.",
                       schema=out / "schema.json", out_json=out / "answer.json", events_log=out / "events.jsonl",
                       images=[out / "canary.png"], writable=(scratch,), cwd=scratch,
                       cfg=CodexConfig(timeout_s=240, max_repair_rounds=0))
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines() if line.strip()]
    tool_events = [e for e in events if e.get("item", {}).get("type") in
                   ("command_execution", "mcp_tool_call", "web_search", "image_view")]
    report = {"passed": result.data == expected and not tool_events, "expected": expected,
              "answer": result.data, "tool_events": len(tool_events), "thread_id": result.thread_id,
              "model": CodexConfig().identity(), "usage": result.usage,
              "interpretation": "A pass proves image perception for this call, not loss-free forwarding of all historical calls."}
    write_json(out / "report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
