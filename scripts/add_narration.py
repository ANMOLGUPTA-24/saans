"""Narrate the demo with Piper, fitted to the recorded beats.

Piper is a neural text-to-speech model that runs offline under MIT —
free, no key, no account, which is the only kind of dependency this
project takes on.

Each line is written to the length of the beat it sits on, generated,
measured, and laid onto a silent track at that beat's start. A line that
overruns its window is nudged with atempo up to a limit; past that the
script refuses rather than letting the voice run over the next shot, so
the words and the pictures cannot drift apart.

    python scripts/add_narration.py

Reads build/demo-raw.webm + build/timeline.json, writes
build/saans-demo-narrated.mp4.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
VOICE = pathlib.Path.home() / ".local/share/piper-voices/en_US-ryan-high.onnx"
VO = BUILD / "vo"
SILENT = BUILD / "saans-demo.mp4"          # the captioned, trimmed cut
OUT = BUILD / "saans-demo-narrated.mp4"
MAX_TEMPO = 1.14                            # beyond this it sounds rushed

# Written to fit. Numbers are spelled the way they should be read, because
# a TTS model says "135%" and "µg·h" badly.
LINES: dict[str, str] = {
    "top bar + timetable":
        "It is Sunday morning in Delhi. Before the school gates open, someone has to "
        "decide whether the games period happens. Saans decides it, from the live "
        "forecast, class by class, and records why.",
    "Class 11-C Outdoors":
        "Class eleven C keeps its recess outdoors. It is the one class with nobody on "
        "the respiratory register.",
    "clause tooltip":
        "Same evidence, different needs. And every decision cites the clause that "
        "produced it.",
    "dose bars, 135% and 208%":
        "An air quality index is a colour, for a city, for a day. What a child absorbs "
        "is a dose. Concentration, times time outdoors, times how hard they are "
        "breathing. A child at games moves about three times the air through their "
        "lungs. So one games period costs a hundred and thirty five per cent of a "
        "child's entire weekly limit.",
    "Delhi map, 772 schools":
        "Seven hundred and seventy two real Delhi schools, every one that Open Street "
        "Map names and locates, clipped to the city border. At all of them, today, one "
        "games period passes a child's whole week.",
    "hourly chart":
        "This is the air it was decided from, hour by hour, against India's national "
        "bands. The strip below is the mixing layer: how far the air can rise before "
        "it stops.",
    "Cedar clauses + pull quote":
        "No language model decides anything that affects a child's lungs. The protocol "
        "is Cedar, AWS's open source policy language. It is not a prompt. A period "
        "stays outdoors only if Cedar returns allow.",
    "decision stability":
        "This runs on a forecast, so: how wrong can the forecast be? Every call is "
        "re-decided across plus or minus forty per cent error. All four games period "
        "calls hold. Borderline calls are labelled marginal.",
    "replay":
        "Replayed over real measured days: forty two per cent of a child's inhaled "
        "dose prevented.",
    "November smog":
        "Forty seven per cent across last November's smog season.",
    "back to the fortnight, quiet day highlighted":
        "And on the twenty eighth of September, with clean air, it did nothing at all.",
    "the 05:45 job":
        "One button runs the whole morning.",
    "MODEL_WAIT":
        "The local model drafts the notice.",
    "receipts + AWS services":
        "And there are the receipts. A Dynamo D B ledger, the notice in S three, "
        "Event Bridge on the schedule, S E S delivering it. Cedar and the Strands "
        "Agents S D K, on the build it path. No AWS account, no key, no spend.",
    "hold":
        "Saans. The bad air day protocol for Indian schools.",
}


def dur(path: pathlib.Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def say(text: str, path: pathlib.Path) -> None:
    r = subprocess.run([sys.executable, "-m", "piper", "-m", str(VOICE), "-f", str(path)],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0 or not path.exists():
        print(r.stderr[-900:], file=sys.stderr)
        raise SystemExit(f"piper failed on: {text[:60]}")


def main() -> None:
    if not VOICE.exists():
        raise SystemExit(f"voice model missing: {VOICE}")
    if not SILENT.exists():
        raise SystemExit("run scripts/burn_captions.py first")
    timeline = json.loads((BUILD / "timeline.json").read_text())
    VO.mkdir(exist_ok=True)

    total = dur(SILENT)
    raw_total = max(b["end"] for b in timeline)
    shift = raw_total - total  # the captioned cut was trimmed of its pre-roll

    print(f"video {total:.1f}s, {len(timeline)} beats\n")
    clips, problems = [], []
    for i, b in enumerate(timeline):
        text = LINES.get(b["label"])
        if not text:
            continue
        start = max(0.0, b["start"] - shift)
        window = b["end"] - b["start"]
        wav = VO / f"v{i:02d}.wav"
        say(text, wav)
        spoken = dur(wav)

        tempo = 1.0
        if spoken > window - 0.25:
            tempo = min(MAX_TEMPO, spoken / max(0.1, window - 0.35))
            fitted = VO / f"v{i:02d}_fit.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav),
                            "-filter:a", f"atempo={tempo:.3f}", str(fitted)], check=True)
            wav, spoken = fitted, dur(fitted)

        over = spoken - window
        flag = ""
        if over > 0.05:
            flag = f"  OVERRUNS by {over:.1f}s"
            problems.append((b["label"], over))
        print(f"  {start:6.1f}s  {window:5.1f}s window  {spoken:5.1f}s spoken"
              f"  x{tempo:.2f}{flag}")
        clips.append((start, wav))

    if problems:
        print("\nThese lines do not fit. Shorten them in LINES and re-run:", file=sys.stderr)
        for label, over in problems:
            print(f"  {label}: {over:.1f}s too long", file=sys.stderr)
        raise SystemExit(1)

    # Lay every clip onto one silent bed of exactly the video's length.
    inputs: list[str] = []
    for _, wav in clips:
        inputs += ["-i", str(wav)]
    parts = [f"anullsrc=r=22050:cl=mono:d={total:.3f}[bed]"]
    mix = "[bed]"
    for n, (start, _) in enumerate(clips):
        parts.append(f"[{n}:a]adelay={int(start*1000)}|{int(start*1000)},"
                     f"aformat=sample_fmts=fltp:sample_rates=22050:channel_layouts=mono[d{n}]")
    amix_in = mix + "".join(f"[d{n}]" for n in range(len(clips)))
    parts.append(f"{amix_in}amix=inputs={len(clips)+1}:normalize=0:duration=first,"
                 f"alimiter=limit=0.95,aresample=48000[out]")
    track = BUILD / "narration.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs,
                    "-f", "lavfi", "-i", f"anullsrc=r=22050:cl=mono:d={total:.3f}",
                    "-filter_complex", ";".join(parts[1:]).replace("[bed]", f"[{len(clips)}:a]"),
                    "-map", "[out]", str(track)], check=True)

    # Without this the summed track peaks at full scale and clips on some
    # players. -16 LUFS with 1.5 dB of true-peak headroom is what YouTube
    # wants anyway, so it will not be re-normalised on upload.
    norm = BUILD / "narration-norm.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(track),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000",
                    str(norm)], check=True)

    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SILENT), "-i", str(norm),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                    "-shortest", "-movflags", "+faststart", str(OUT)], check=True)

    d = dur(OUT)
    m, s = divmod(d, 60)
    print(f"\nwrote {OUT}")
    print(f"  {int(m)}:{s:04.1f}  {OUT.stat().st_size/1e6:.1f} MB")
    if d >= 180:
        raise SystemExit("OVER the three-minute limit")
    print(f"  {180-d:.1f}s under the limit")


if __name__ == "__main__":
    main()
