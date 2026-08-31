"""ADR-30 review finding 10: genuine browser-level (Playwright/Chromium)
responsive-viewport and native-keyboard verification for the run-control
page.

Run directly, NOT pytest-collected (mirrors tests/crash/*.py's own
convention for verification that needs infrastructure outside the default
suite) -- this needs the optional ``playwright`` package plus its Chromium
browser (``pip install playwright && python -m playwright install
chromium``), neither of which are declared project dependencies, and a
real Dashboard instance already running and reachable.

Usage:
    python tests/browser/run_control_responsive_and_keyboard_check.py \\
        http://127.0.0.1:8420 1

The second argument is the id of an already-registered, launch-capable
repository with a READY read model and at least one configured issue.

Why this exists instead of a pytest test: the mcp claude-in-chrome
extension's own window-resize control does not reliably shrink an already
maximized OS window in every session (confirmed directly in this review:
``resize_window`` reports success but ``window.innerWidth`` is unchanged,
on both the original tab and a freshly created one), and its CDP-relayed
synthetic key events do not reliably trigger a native default action for
every element in every session either -- a real Chromium instance under
direct Playwright control has neither limitation and is the more
authoritative check for exactly these two properties. See
docs/reviews/DASHBOARD_ISSUE_RUN_CONTROL_BUILD_EVIDENCE.md for the original
build's own precedent of documenting (not silently claiming past) a
tooling/session boundary of this kind.

Checks, all against the real run-control page:
- No document-level horizontal overflow at 320/768/1024/1440 CSS px, with
  the run-selected/run-all controls visible at every width.
- A real native Space key press toggles an issue-row checkbox and enables
  "Run selected" (not just moves focus to it).
- A real native Enter key press activates "Run all" and opens the
  confirmation dialog, which autofocuses "Start run".
- Shift+Tab from "Start run" reaches "Cancel"; a second Shift+Tab wraps
  back to "Start run" -- a genuine focus trap, not just the dialog's own
  keydown listener reacting to the event.
- Escape closes the dialog and returns focus to the invoking "Run all"
  button.
- Zero console errors across a full reload.
"""
from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <base_url> <repo_id>", file=sys.stderr)
        return 2
    base_url, repo_id = argv[1], argv[2]
    url = f"{base_url.rstrip('/')}/repositories/{repo_id}/run-control"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright is not installed -- pip install playwright && "
            "python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1

    widths = (320, 768, 1024, 1440)
    results: dict = {"url": url, "viewports": [], "keyboard": {}}
    ok = True

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in widths:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(url)
            page.wait_for_selector("#run-control-run-all", state="attached")
            page.wait_for_timeout(500)
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            entry = {
                "width": width, "scrollWidth": scroll_width, "clientWidth": client_width,
                "overflow": scroll_width > client_width,
                "runSelectedVisible": page.is_visible("#run-control-run-selected"),
                "runAllVisible": page.is_visible("#run-control-run-all"),
            }
            results["viewports"].append(entry)
            if entry["overflow"] or not entry["runSelectedVisible"] or not entry["runAllVisible"]:
                ok = False
            page.close()

        page = browser.new_page(viewport={"width": 1280, "height": 900})
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.goto(url)
        page.wait_for_selector("#run-control-run-all", state="attached")
        page.wait_for_timeout(500)

        checkbox = page.locator("tbody input[type=checkbox]").first
        checkbox.focus()
        page.keyboard.press("Space")
        checked_after_space = checkbox.is_checked()
        run_selected_enabled_after_space = not page.is_disabled("#run-control-run-selected")

        page.locator("#run-control-run-all").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector("[role=dialog]", state="visible")
        autofocus_text = page.evaluate("document.activeElement.textContent")
        page.keyboard.press("Shift+Tab")
        after_one_shift_tab = page.evaluate("document.activeElement.textContent")
        page.keyboard.press("Shift+Tab")
        after_two_shift_tab = page.evaluate("document.activeElement.textContent")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        dialog_gone = page.locator("[role=dialog]").count() == 0
        focus_returned = page.evaluate("document.activeElement.id") == "run-control-run-all"

        kb = {
            "checkedAfterSpace": checked_after_space,
            "runSelectedEnabledAfterSpace": run_selected_enabled_after_space,
            "dialogAutofocusText": autofocus_text,
            "afterOneShiftTab": after_one_shift_tab,
            "afterTwoShiftTabWrapsBack": after_two_shift_tab,
            "dialogGoneAfterEscape": dialog_gone,
            "focusReturnedToInvokingButton": focus_returned,
            "consoleErrors": console_errors,
        }
        results["keyboard"] = kb
        if not (checked_after_space and run_selected_enabled_after_space
                and autofocus_text == "Start run" and after_one_shift_tab == "Cancel"
                and after_two_shift_tab == "Start run" and dialog_gone and focus_returned
                and not console_errors):
            ok = False
        page.close()
        browser.close()

    print(json.dumps(results, indent=2))
    print("ALL RUN-CONTROL RESPONSIVE/KEYBOARD CHECKS PASSED" if ok else "CHECK FAILURE -- see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
