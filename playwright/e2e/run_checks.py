import json
import os
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8000")
ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "./artifacts")

def main() -> int:
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)
    report = {
        "target_url": TARGET_URL,
        "ts": datetime.utcnow().isoformat() + "Z",
        "console": [],
        "pageerrors": [],
        "network": {"requests": [], "responses": []},
        "dom": {},
        "ok": True,
        "failures": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # CI-friendly
        context = browser.new_context(record_video_dir=ARTIFACTS_DIR)
        page = context.new_page()

        # Console + errors
        page.on("console", lambda msg: report["console"].append({"type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda err: report["pageerrors"].append({"text": str(err)}))

        # Network
        page.on("request", lambda req: report["network"]["requests"].append({"method": req.method, "url": req.url}))
        page.on("response", lambda res: report["network"]["responses"].append({"status": res.status, "url": res.url}))

        # Trace for post-mortem debugging
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30_000)

            # Example DOM reads (replace selectors with your real UI)
            report["dom"]["live_segments"] = page.locator("#liveSegments").inner_text(timeout=5_000)
            report["dom"]["consolidated"] = page.locator("#consolidatedText").inner_text(timeout=5_000)
            report["dom"]["event_log"] = page.locator("#eventLog").inner_text(timeout=5_000)

            # Basic assertions (examples)
            if not report["dom"]["consolidated"].strip():
                report["ok"] = False
                report["failures"].append("Consolidated transcript is empty.")

        except Exception as e:
            report["ok"] = False
            report["failures"].append(f"Exception: {e}")
            page.screenshot(path=os.path.join(ARTIFACTS_DIR, "error.png"), full_page=True)

        finally:
            context.tracing.stop(path=os.path.join(ARTIFACTS_DIR, "trace.zip"))
            context.close()
            browser.close()

    with open(os.path.join(ARTIFACTS_DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return 0 if report["ok"] else 1

if __name__ == "__main__":
    sys.exit(main())
