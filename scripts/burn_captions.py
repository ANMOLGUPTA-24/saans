"""Turn the raw screen capture into the submission video.

There is no narration. A synthetic voice would sound worse than silence,
so the captions carry the argument instead — which also means the video
reads with the sound off, the way most of them are first watched.

Captions are rendered as PNG cards with Pillow rather than burned by
libass, because this ffmpeg build has no subtitles filter, and because
rendering them ourselves keeps the same paper-and-ink treatment as the
dashboard.

    python scripts/burn_captions.py

Writes build/saans-demo.mp4, trimmed of its pre-roll and checked to be
under the three-minute limit.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
RAW = BUILD / "demo-raw.webm"
CARDS = BUILD / "cards"
OUT = BUILD / "saans-demo.mp4"
LIMIT_S = 180.0

W, H = 1600, 900
BAND_H = 132
PAPER = (231, 233, 228)
INK = (0, 0, 0)
INK2 = (78, 86, 77)
LOUD = (233, 63, 51)

BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# label -> (headline, supporting line). Keyed to the beats the recorder
# logged, so the words and the pictures cannot drift apart.
CAPTIONS: dict[str, tuple[str, str]] = {
    "top bar + timetable": (
        "Before the gates open, someone has to decide: does the games period happen?",
        "Saans decides it from the live forecast, per class, and records why.",
    ),
    "Class 11-C Outdoors": (
        "Class 11-C keeps recess outdoors. It is the one class with nobody on the register.",
        "Same evidence, different needs — a policy engine, not a blanket ban.",
    ),
    "clause tooltip": (
        "Every decision cites the clause that produced it.",
        "",
    ),
    "dose bars, 135% and 208%": (
        "One games period costs 135% of a child's entire WHO week.",
        "Dose = concentration × time outdoors × how hard they breathe. A child at games "
        "moves ~3× the air. That last term is what an AQI reading drops.",
    ),
    "Delhi map, 772 schools": (
        "772 real Delhi schools. At every one of them, today, one games period "
        "passes a child's whole WHO week.",
        "Locations from OpenStreetMap, clipped to the NCT border. Coloured by CPCB band.",
    ),
    "hourly chart": (
        "The air it was decided from — hour by hour, against CPCB's national bands.",
        "The strip below is the mixing layer: how far the air can rise before it stops.",
    ),
    "Cedar clauses + pull quote": (
        "No language model decides anything that affects a child's lungs.",
        "The protocol is Cedar — AWS's open-source policy language. Not a prompt. "
        "A period stays outdoors only if Cedar returns allow.",
    ),
    "decision stability": (
        "How wrong can the forecast be before the decision changes?",
        "Every call re-decided across ±40% forecast error. All four games-period calls "
        "hold. Borderline calls are labelled marginal rather than given false confidence.",
    ),
    "replay": (
        "42% of a child's inhaled dose prevented, across 10 real school days.",
        "Replayed over measured air — no modelling of our own.",
    ),
    "November smog": (
        "47% across last November's smog season.",
        "",
    ),
    "back to the fortnight, quiet day highlighted": (
        "And on 28 September, with clean air, it did nothing at all.",
        "A protocol that fires on a good day gets switched off in a fortnight — "
        "and then it is not there on the day that matters.",
    ),
    "the 05:45 job": (
        "The 05:45 job: decide, draft the notice, write the ledger, store it, send it.",
        "",
    ),
    "MODEL_WAIT": (
        "The local model drafting the line that goes home to parents.",
        "Its draft is checked against the record before it is used.",
    ),
    "receipts + AWS services": (
        "DynamoDB ledger. S3 notice. EventBridge schedule. SES delivery.",
        "Cedar and Strands Agents SDK on the Build It path — no AWS account, no key, "
        "no spend. The same calls deploy to real AWS with one environment variable.",
    ),
    "hold": (
        "Saans — the bad air day protocol for Indian schools",
        "github.com/ANMOLGUPTA-24/saans   ·   anmolgupta-24.github.io/saans",
    ),
}


def wrap(draw, text: str, font, max_w: int) -> list[str]:
    if not text:
        return []
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card(headline: str, sub: str, loud: bool, path: pathlib.Path) -> None:
    img = Image.new("RGBA", (W, BAND_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, BAND_H], fill=PAPER + (242,))
    d.rectangle([0, 0, W, 3], fill=INK)

    f_head = ImageFont.truetype(BOLD, 31)
    f_sub = ImageFont.truetype(REG, 19)
    pad = 38
    maxw = W - pad * 2

    y = 20
    for line in wrap(d, headline, f_head, maxw)[:2]:
        d.text((pad, y), line, font=f_head, fill=LOUD if loud else INK)
        y += 36
    y += 4
    for line in wrap(d, sub, f_sub, maxw)[:2]:
        d.text((pad, y), line, font=f_sub, fill=INK2)
        y += 25
    img.save(path)


def main() -> None:
    if not RAW.exists():
        raise SystemExit(f"{RAW} missing — run scripts/record_demo.py first")
    timeline = json.loads((BUILD / "timeline.json").read_text())
    CARDS.mkdir(exist_ok=True)

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(RAW)], capture_output=True, text=True).stdout.strip())
    last_end = max(b["end"] for b in timeline)
    # Playwright starts recording at page creation; the beats start later.
    offset = max(0.0, dur - last_end)
    print(f"raw {dur:.1f}s, beats end {last_end:.1f}s, trimming {offset:.2f}s of pre-roll")

    inputs, filters, idx = ["-ss", f"{offset:.3f}", "-i", str(RAW)], [], 1
    chain = "[0:v]"
    loud_beats = {"dose bars, 135% and 208%", "Delhi map, 772 schools",
                  "Cedar clauses + pull quote"}
    for i, b in enumerate(timeline):
        cap = CAPTIONS.get(b["label"])
        if not cap:
            continue
        p = CARDS / f"c{i:02d}.png"
        card(cap[0], cap[1], b["label"] in loud_beats, p)
        inputs += ["-i", str(p)]
        start, end = b["start"], b["end"]
        nxt = f"[v{idx}]"
        filters.append(
            f"{chain}[{idx}:v]overlay=0:{H-BAND_H}:"
            f"enable='between(t,{start:.2f},{end:.2f})'{nxt}"
        )
        chain = nxt
        idx += 1

    final = chain
    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", ";".join(filters),
           "-map", final, "-an",
           "-c:v", "libx264", "-preset", "slow", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-r", "25", str(OUT)]
    print(f"compositing {idx-1} caption cards…")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2500:], file=sys.stderr)
        raise SystemExit("ffmpeg failed")

    out_dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(OUT)], capture_output=True, text=True).stdout.strip())
    mins, secs = divmod(out_dur, 60)
    print(f"\nwrote {OUT}")
    print(f"  {int(mins)}:{secs:04.1f}  ({out_dur:.1f}s)  {OUT.stat().st_size/1e6:.1f} MB")
    if out_dur >= LIMIT_S:
        raise SystemExit(f"OVER THE 3-MINUTE LIMIT by {out_dur-LIMIT_S:.1f}s")
    print(f"  {LIMIT_S-out_dur:.1f}s under the three-minute limit")


if __name__ == "__main__":
    main()
