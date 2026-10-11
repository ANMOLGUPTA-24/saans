"""Record the three-minute demo, driving the real dashboard.

Runs against the local app rather than the published page, because the
rules require the video to *show* AWS, and only the running engine
produces live DynamoDB, S3 and SES receipts.

    python scripts/record_demo.py

Produces build/demo-raw.webm, which burn_captions.py turns into the
final mp4. There is no narration: a synthetic voice would sound worse
than silence, and the captions carry the argument. The script in
docs/video-script.md is timed to these same beats if you want to record
your own voice over it.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "build"
URL = "http://127.0.0.1:8000/"
W, H = 1600, 900

# Each beat: (seconds, what the viewer should be looking at).
# Total must stay under 180s with room to spare.


TIMELINE: list[dict] = []
T0 = [0.0]


def mark(label: str) -> float:
    return time.monotonic() - T0[0]


def beat(page, seconds: float, label: str) -> None:
    start = mark(label)
    page.wait_for_timeout(int(seconds * 1000))
    end = mark(label)
    TIMELINE.append({"label": label, "start": round(start, 2), "end": round(end, 2)})
    print(f"  {start:6.1f}s  {label} ({seconds}s)", flush=True)


def smooth_scroll(page, to: int, ms: int = 900) -> None:
    page.evaluate(
        """([to, ms]) => new Promise(res => {
            const start = window.scrollY, delta = to - start, t0 = performance.now();
            function step(t){
              const k = Math.min(1, (t - t0) / ms);
              const e = k < .5 ? 2*k*k : 1 - Math.pow(-2*k+2, 2)/2;  // ease in-out
              window.scrollTo(0, start + delta * e);
              if (k < 1) requestAnimationFrame(step); else res();
            }
            requestAnimationFrame(step);
        })""",
        [to, ms],
    )
    page.wait_for_timeout(ms + 120)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--force-device-scale-factor=1"])
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(OUT),
            record_video_size={"width": W, "height": H},
            reduced_motion="no-preference",
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded")

        # Everything must be painted before frame one.
        page.wait_for_selector("table.tt", timeout=90_000)
        page.wait_for_selector("#protocol .cl", timeout=90_000)
        page.wait_for_selector(".leaflet-container canvas", timeout=90_000)
        page.wait_for_timeout(2500)
        T0[0] = time.monotonic()
        print("page ready, recording beats:", flush=True)

        # 1 — the board, cold. Let the yellow register.
        beat(page, 12, "top bar + timetable")

        # 2 — Class 11-C keeps a period. The policy engine discriminating.
        page.hover("table.tt tbody tr:nth-child(4) td.cell.out")
        beat(page, 7, "Class 11-C Outdoors")

        # 3 — a clause chip, so the tooltip is on camera (rules: it must be shown)
        chip = page.locator("table.tt .clause").first
        chip.hover()
        beat(page, 7, "clause tooltip")

        # 4 — dose against the WHO week: the one loud moment
        smooth_scroll(page, 430)
        beat(page, 16, "dose bars, 135% and 208%")

        # 5 — the city
        smooth_scroll(page, 120)
        page.hover(".leaflet-container")
        beat(page, 13, "Delhi map, 772 schools")

        # 6 — the air it was decided from
        smooth_scroll(page, 760)
        beat(page, 12, "hourly chart")

        # 7 — the protocol, in Cedar
        page.click('button[data-tab="protocol"]')
        beat(page, 15, "Cedar clauses + pull quote")

        # 8 — forecast error
        page.click('button[data-tab="stability"]')
        beat(page, 13, "decision stability")

        # 9 — what it is worth, and the quiet day
        page.click('button[data-tab="replay"]')
        beat(page, 9, "replay")
        page.click("#btn-nov")
        beat(page, 8, "November smog")
        page.click("#btn-recent")
        beat(page, 8, "back to the fortnight, quiet day highlighted")

        # 10 — AWS, with receipts. This is the bit the rules require.
        page.click('button[data-tab="run"]')
        beat(page, 5, "the 05:45 job")
        wait_start = mark("run")
        page.click("#btn-run")
        try:
            page.wait_for_selector(".rcpt", timeout=180_000)
        except Exception:
            print("  ! receipts did not appear", file=sys.stderr)
        wait_end = mark("run")
        TIMELINE.append({"label": "MODEL_WAIT", "start": round(wait_start, 2),
                         "end": round(wait_end, 2)})
        print(f"  {wait_start:6.1f}s  model drafting ({wait_end-wait_start:.1f}s)", flush=True)
        beat(page, 15, "receipts + AWS services")
        beat(page, 4, "hold")
        ctx.close()
        browser.close()

    vids = sorted(OUT.glob("*.webm"), key=lambda f: f.stat().st_mtime)
    if not vids:
        raise SystemExit("no video produced")
    raw = OUT / "demo-raw.webm"
    if vids[-1] != raw:
        vids[-1].replace(raw)
    (OUT / "timeline.json").write_text(json.dumps(TIMELINE, indent=1))
    print(f"\nwrote {raw} ({raw.stat().st_size/1e6:.1f} MB)")
    print(f"wrote {OUT/'timeline.json'} — {len(TIMELINE)} beats")


if __name__ == "__main__":
    main()
