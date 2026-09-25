import getpass
import sys
from pathlib import Path

from PIL import Image
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from omniparser_client import OmniParserClient
from browser_controller import BrowserController
from find_sites import find_websites, write_results
from grab import ResponseRecorder, reset_output_folder
import element_filter
import config


def parse_current_page(browser: BrowserController, parser: OmniParserClient, step_name: str, save_debug=True):
    screenshot_path = browser.screenshot()
    img = Image.open(screenshot_path)

    if save_debug:
        parsed_content = parser.parse_and_save(screenshot_path, step_name)
    else:
        # Polling still needs a screenshot for OmniParser, but do not create a
        # labeled PNG + JSON for every unsuccessful poll.
        _, _, parsed_content = parser.parse(screenshot_path)

    return parsed_content, img.size


def _find_visual_popup_x(parsed_content, img_w, img_h):
    """Find a conservative visual popup close control from OmniParser output."""
    candidates = []
    safe_labels = {
        "x", "×", "close", "dismiss", "no thanks", "not now",
        "maybe later", "later", "cancel",
    }

    for el in parsed_content or []:
        raw_text = (el.get("content") or "").strip()
        normalized = " ".join(raw_text.casefold().split())
        if normalized not in safe_labels:
            continue

        try:
            bbox_px = element_filter.normalize_bbox_to_pixels(el["bbox"], img_w, img_h)
        except Exception:
            continue

        x1, y1, x2, y2 = bbox_px
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)
        if width > 90 or height > 90 or width < 5 or height < 5:
            continue

        score = 45.0 if normalized in {"x", "×"} else 40.0 if normalized == "close" else 30.0
        if el.get("interactivity"):
            score += 35.0
        if str(el.get("source", "")).startswith("box_yolo"):
            score += 10.0
        if 0.55 <= width / height <= 1.8:
            score += 8.0

        candidates.append((score, {
            "text": raw_text,
            "center": element_filter.bbox_center(bbox_px),
            "bbox_px": bbox_px,
            "raw": el,
            "score": score,
        }))

    if not candidates:
        return None

    candidates.sort(key=lambda item: -item[0])
    best = candidates[0][1]
    if (best["score"] < 45.0 and not best["raw"].get("interactivity")
            and best["text"].casefold() not in {"x", "×", "close"}):
        return None
    return best


def _handle_visual_popup_x(browser, parsed_content, img_w, img_h):
    """Click one OmniParser-detected popup close control, if confidently found."""
    target = _find_visual_popup_x(parsed_content, img_w, img_h)
    if not target:
        return False

    print(
        f"[+] Visual popup close detected: '{target['text']}' "
        f"at {target['center']} (score={target['score']:.1f})"
    )
    try:
        browser.mouse_click(*target["center"])
        browser.page.wait_for_timeout(500)
        print("[+] Visual popup close clicked.")
        return True
    except Exception as exc:
        print(f"[!] Visual popup close click failed: {exc}")
        return False


def wait_for_login_form(browser, parser, max_wait_ms=15000, poll_interval_ms=1500):
    waited = 0
    attempt = 0

    while waited < max_wait_ms:
        remaining = max_wait_ms - waited
        wait_ms = min(poll_interval_ms, remaining)
        browser.page.wait_for_timeout(wait_ms)
        waited += wait_ms
        attempt += 1

        parsed_content, (img_w, img_h) = parse_current_page(
            browser,
            parser,
            f"waiting_for_form_{attempt}",
            save_debug=False,
        )

        if element_filter.confirm_login_form_open(parsed_content, img_w, img_h):
            print(f"[+] Login form detected after {waited}ms ({attempt} polls).")
            return parsed_content, img_w, img_h

        print(f"[!] Login form not yet detected ({waited}ms elapsed)...")

    return None, None, None


def verify_field_with_fallbacks(browser, field, expected_type, bbox_px=None,
                                 before_path=None, after_path=None):
    votes = []

    if bbox_px is not None and before_path and after_path:
        changed = browser.region_changed(before_path, after_path, bbox_px)
        votes.append(("visual_change", changed))

    ax_info = browser.get_ax_node_near_point(*field["center"])
    ax_ok = element_filter.ax_confirms_field(ax_info, expected_type)
    votes.append(("ax_tree", ax_ok))

    passed = [name for name, ok in votes if ok]
    failed = [name for name, ok in votes if not ok]

    print(
        f"[debug] '{expected_type}' checks — "
        f"passed: {passed or 'none'}, failed: {failed or 'none'}"
    )

    if passed:
        if failed:
            print(
                f"[!] '{expected_type}': some checks disagreed ({failed}) "
                f"but proceeding since {passed} confirmed it."
            )
        return True

    print(
        f"[!] '{expected_type}': all checks failed. "
        f"Proceeding cautiously anyway (soft-vote, no hard block)."
    )
    return True


def _typing_confirmation_bbox(field, img_w, img_h, pad_x=35, pad_y=45):
    bbox_px = field.get("confirm_bbox_px")
    if bbox_px is not None:
        return bbox_px

    raw_bbox_px = element_filter.normalize_bbox_to_pixels(
        field["raw"]["bbox"], img_w, img_h
    )

    return [
        max(0, raw_bbox_px[0] - pad_x),
        max(0, raw_bbox_px[1] - pad_y),
        min(img_w, raw_bbox_px[2] + 360),
        min(img_h, raw_bbox_px[3] + pad_y),
    ]


def _type_and_confirm_identifier(browser, field, identifier_value):
    """
    Types the identifier and confirms that the screen region associated with
    the identifier anchor changed.
    """
    img_w = field["_img_w"]
    img_h = field["_img_h"]

    confirm_bbox_px = _typing_confirmation_bbox(field, img_w, img_h)

    before_type_path = "before_type_identifier.png"
    after_type_path = "after_type_identifier.png"

    browser.screenshot(before_type_path)
    browser.type_text(identifier_value)
    browser.page.wait_for_timeout(300)
    browser.screenshot(after_type_path)

    changed = browser.region_changed(
        before_type_path,
        after_type_path,
        confirm_bbox_px,
        min_diff_area=20,
    )

    print(
        f"[debug] 'identifier' typing confirmation: "
        f"{'PASSED' if changed else 'FAILED'}"
    )

    return changed


def _click_identifier(browser, field):
    browser.mouse_click(*field["center"])
    browser.page.wait_for_timeout(300)


def _confirm_identifier_strategy(browser, id_field, identifier_value):
    if id_field["strategy"] == "interactive":
        print(
            f"[+] Identifier is interactive. Using direct mouse interaction: "
            f"'{id_field['text']}'"
        )
        _click_identifier(browser, id_field)

        # Preserve the direct-interaction behavior, but also confirm the
        # identifier entry visually.
        return _type_and_confirm_identifier(
            browser, id_field, identifier_value
        )

    print(
        f"[+] Identifier is non-interactive. "
        f"Clicking keyword/placeholder anchor: '{id_field['text']}'"
    )
    _click_identifier(browser, id_field)
    return _type_and_confirm_identifier(
        browser, id_field, identifier_value
    )


def _is_ocr_masked_password_text(text: str) -> bool:
    """
    Return True when OCR text looks like a masked password string.

    We intentionally accept several common masking glyphs because OCR output
    varies by browser/font/theme. The check is strict about repetition so normal
    words or sentences are not classified as password characters.
    """
    compact = (text or "").replace(" ", "").replace("\u00a0", "")
    if len(compact) < 3:
        return False

    masked_chars = set(".·•*●○◦▪□")
    return all(ch in masked_chars for ch in compact)


def _find_omniparser_masked_password(parsed_content, img_w, img_h):
    """
    Find an OmniParser OCR element that looks like masked password characters.
    Returns the strongest candidate or None.

    The AFTER screenshot is parsed independently, so confirmation is based on
    what OmniParser actually sees after typing, not on the old password keyword.
    """
    candidates = []

    for el in parsed_content or []:
        text = (el.get("content") or "").strip()
        if not _is_ocr_masked_password_text(text):
            continue

        bbox_px = element_filter.normalize_bbox_to_pixels(
            el["bbox"], img_w, img_h
        )
        x1, y1, x2, y2 = bbox_px
        width = max(x2 - x1, 1)
        height = max(y2 - y1, 1)

        # A masked password string should be horizontally longer than it is tall.
        if width < 8 or height > 40 or width / height < 1.5:
            continue

        candidates.append(
            {
                "text": text,
                "bbox_px": bbox_px,
                "center": element_filter.bbox_center(bbox_px),
                "length": len(text.replace(" ", "")),
                "raw": el,
            }
        )

    if not candidates:
        return None

    # Prefer the longest masked sequence, then the widest one.
    return max(
        candidates,
        key=lambda item: (
            item["length"],
            item["bbox_px"][2] - item["bbox_px"][0],
        ),
    )


def _find_omniparser_eye_near_password(parsed_content, password_line,
                                        img_w, img_h):
    """
    Look in OmniParser's AFTER-screenshot results for an eye/visibility
    element located near the right side of the detected masked password text.

    The eye is supporting evidence; it does not locate or focus the field.
    """
    px1, py1, px2, py2 = password_line["bbox_px"]
    pw_cy = (py1 + py2) / 2.0
    pw_x2 = px2

    candidates = []

    for el in parsed_content or []:
        text = (el.get("content") or "").strip()
        normalized = text.casefold().replace("-", " ")

        if not normalized:
            continue

        is_eye = any(
            hint.casefold() in normalized
            for hint in config.EYE_ICON_HINTS
        )
        if not is_eye:
            continue

        bbox_px = element_filter.normalize_bbox_to_pixels(
            el["bbox"], img_w, img_h
        )
        ex1, ey1, ex2, ey2 = bbox_px
        ecx, ecy = element_filter.bbox_center(bbox_px)

        # Eye should be to the right and approximately aligned with the
        # password characters.
        horizontal_gap = ecx - pw_x2
        vertical_gap = abs(ecy - pw_cy)

        if horizontal_gap < -10 or horizontal_gap > 320:
            continue
        if vertical_gap > 45:
            continue

        score = 0.0
        score += 30.0 if el.get("interactivity") else 0.0
        score += 10.0 if el.get("source", "").startswith("box_yolo") else 0.0
        score += 10.0 if "eye" in normalized else 0.0
        score += 8.0 if "visibility" in normalized else 0.0

        candidates.append((score, {"text": text, "bbox_px": bbox_px}))

    if not candidates:
        return None

    candidates.sort(key=lambda item: -item[0])
    return candidates[0][1]


def _visual_password_change_fallback(before_path, after_path):
    """
    Lightweight compatibility fallback.

    The new primary confirmation is OmniParser on the AFTER screenshot. If OCR
    cannot read the masked characters on a particular site, retain a visual
    BEFORE/AFTER change check so the existing workflow does not unnecessarily
    break.
    """
    before = np.asarray(Image.open(before_path).convert("L"), dtype=np.int16)
    after = np.asarray(Image.open(after_path).convert("L"), dtype=np.int16)

    if before.shape != after.shape:
        return False

    diff = np.abs(after - before)
    return int(np.count_nonzero(diff >= 25)) >= 20


def _confirm_password_after_tab(browser, pw_field, password_value, parsed_content):
    """
    Password confirmation strategy.

      1. Identifier has already been confirmed.
      2. Press Tab once to move focus to the password field.
      3. Capture BEFORE screenshot.
      4. Type the password.
      5. Capture AFTER screenshot.
      6. Run OmniParser AGAIN on the AFTER screenshot.
      7. Require OCR/parsed content that looks like masked password characters.
      8. Prefer an OmniParser eye/visibility signal near the masked text.
      9. If OCR cannot read the mask, use the preserved visual fallback.

    The previously detected password keyword is NOT used as the confirmation
    anchor.
    """
    print("[+] Pressing Tab to move from identifier to password field.")
    browser.tab_to_field("forward")

    before_type_path = "before_type_password.png"
    after_type_path = "after_type_password.png"

    browser.screenshot(before_type_path)
    browser.type_text(password_value)
    browser.page.wait_for_timeout(300)
    browser.screenshot(after_type_path)

    # PRIMARY: parse the AFTER screenshot so OmniParser sees what appeared after
    # the password was typed.
    parser = OmniParserClient.get()
    _, _, after_parsed_content = parser.parse(after_type_path)
    after_img = Image.open(after_type_path)
    img_w, img_h = after_img.size

    password_line = _find_omniparser_masked_password(
        after_parsed_content,
        img_w,
        img_h,
    )

    if password_line is not None:
        eye = _find_omniparser_eye_near_password(
            after_parsed_content,
            password_line,
            img_w,
            img_h,
        )

        if eye:
            print(
                "[debug] Password confirmation: PASSED "
                "(OmniParser found masked password characters + nearby eye)."
            )
        else:
            print(
                "[debug] Password confirmation: PASSED "
                "(OmniParser found masked password characters; eye not detected)."
            )

        return True

    print(
        "[!] OmniParser could not confidently read masked password characters "
        "in the AFTER screenshot."
    )

    # SECONDARY: preserve a visual fallback so sites with poor OCR do not break.
    if _visual_password_change_fallback(
        before_type_path,
        after_type_path,
    ):
        print(
            "[debug] Password confirmation: PASSED "
            "(visual BEFORE/AFTER fallback)."
        )
        return True

    print("[!] Password confirmation FAILED.")
    return False


def run_login(browser, id_field, pw_field, submit_field,
              identifier_value, password_value, parsed_content):
    """Login path: identifier anchor + Tab password + interactive submit."""
    print("[+] Login fields located. Using upgraded field interaction strategy.")

    # --- 1. Identifier ---
    if not _confirm_identifier_strategy(browser, id_field, identifier_value):
        print("[!] Identifier entry could not be visually confirmed.")
        return False

    # --- 2. Password ---
    if not _confirm_password_after_tab(
        browser, pw_field, password_value, parsed_content
    ):
        print("[!] Password entry could not be visually confirmed.")
        return False

    # --- 3. Submit ---
    if submit_field is None:
        print(
            "[!] Submit button was not detected as an interactive "
            "submit element. Aborting."
        )
        return False

    print(f"[+] Clicking submit: '{submit_field['text']}'")
    browser.mouse_click(*submit_field["center"])
    return True


def main():
    url = input("Enter the URL: ").strip()
    identifier_value = input("Enter username/email/phone: ").strip()
    password_value = getpass.getpass("Enter password: ")

    output_folder = PROJECT_ROOT / "downloaded"
    site_folder = reset_output_folder(output_folder, url)
    output_file = site_folder / "websites.txt"

    browser = BrowserController(headless=False)
    recorder = ResponseRecorder(output_folder, url)
    recorder.attach(browser.page)
    parser = OmniParserClient.get()

    try:
        browser.open(url)
        parsed_content, (img_w, img_h) = parse_current_page(
            browser, parser, "initial_page", save_debug=True
        )

        import time as _time

        def _refresh_and_check_prelogin_popups(parsed, width, height, label):
            """Handle popup paths before login click only and refresh stale OCR data."""
            changed = False

            dismissed = browser.dismiss_role_dialogs()
            if dismissed:
                print(f"[+] Role-dialog popup dismissed ({label}).")
                changed = True
                parsed, (width, height) = parse_current_page(
                    browser, parser, f"{label}_after_role_popup", save_debug=False
                )

            visual_closed = _handle_visual_popup_x(browser, parsed, width, height)
            if visual_closed:
                changed = True
                parsed, (width, height) = parse_current_page(
                    browser, parser, f"{label}_after_visual_popup", save_debug=False
                )

            return parsed, width, height, changed

        # PRE-LOGIN ONLY: run both popup paths even when login is already visible.
        # A small popup may not hide the login text but can still block its click.
        parsed_content, img_w, img_h, _ = _refresh_and_check_prelogin_popups(
            parsed_content, img_w, img_h, "initial_prelogin_popup_check"
        )

        login_trigger = element_filter.locate_login_trigger(
            parsed_content, img_w, img_h
        )

        # Bounded recovery for heavy client-rendered pages.
        recovery_deadline = _time.monotonic() + 20000 / 1000.0
        recovery_attempt = 0

        while not login_trigger and _time.monotonic() < recovery_deadline:
            browser.page.wait_for_timeout(750)
            recovery_attempt += 1

            parsed_content, (img_w, img_h) = parse_current_page(
                browser,
                parser,
                f"login_recovery_{recovery_attempt}",
                save_debug=False,
            )

            # Popup handling is still PRE-LOGIN only.
            parsed_content, img_w, img_h, popup_changed = _refresh_and_check_prelogin_popups(
                parsed_content,
                img_w,
                img_h,
                f"login_recovery_{recovery_attempt}_popup",
            )

            login_trigger = element_filter.locate_login_trigger(
                parsed_content, img_w, img_h
            )

            if login_trigger:
                print(
                    f"[+] Login trigger detected during recovery "
                    f"({recovery_attempt} attempts)."
                )
                break

            status = " after popup handling" if popup_changed else ""
            print(
                f"[!] Login trigger not yet detected "
                f"({recovery_attempt} recovery attempts){status}..."
            )

        # Final PRE-LOGIN pass immediately before click. No popup handling is
        # performed after this click, so a login form's own X cannot be closed.
        if login_trigger:
            parsed_content, img_w, img_h, _ = _refresh_and_check_prelogin_popups(
                parsed_content,
                img_w,
                img_h,
                "final_prelogin_popup_check",
            )
            login_trigger = element_filter.locate_login_trigger(
                parsed_content, img_w, img_h
            )

        if not login_trigger:
            print("[!] No login trigger found. Exiting.")
            return

        print(
            f"[+] Clicking login trigger: '{login_trigger['text']}' "
            f"at {login_trigger['center']}"
        )
        browser.mouse_click(*login_trigger["center"])

        parsed_content, img_w, img_h = wait_for_login_form(browser, parser)
        if parsed_content is None:
            print(
                "[!] Login form never appeared within the max wait window. "
                "Aborting."
            )
            return

        recorder.save_new_responses("before-login")

        id_field, pw_field, submit_field = element_filter.locate_credential_fields(
            parsed_content, img_w, img_h, browser=browser
        )

        for label, f in [
            ("identifier", id_field),
            ("password", pw_field),
            ("submit", submit_field),
        ]:
            print(
                f"[debug] {label}: "
                f"{f['text'] if f else 'NO MATCH'} "
                f"{f['center'] if f else ''} "
                f"strategy={f.get('strategy') if f else ''}"
            )

        for f in (id_field, pw_field, submit_field):
            if f is not None:
                f["_img_w"], f["_img_h"] = img_w, img_h

        if not id_field:
            print(
                "[!] Could not locate the identifier field/anchor. Aborting."
            )
            return

        if not pw_field:
            print(
                "[!] Could not locate a password keyword/field anchor. "
                "Aborting."
            )
            return

        login_ok = run_login(
            browser,
            id_field,
            pw_field,
            submit_field,
            identifier_value,
            password_value,
            parsed_content,
        )
        if not login_ok:
            print(
                "[!] Credential entry could not be confirmed. "
                "Aborting before submit."
            )
            return

        browser.page.wait_for_timeout(4000)
        new_url = browser.page.url
        print(f"[+] Post-submit URL: {new_url}")

        parsed_content, (img_w, img_h) = parse_current_page(
            browser, parser, "post_submit", save_debug=True
        )

        browser.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        browser.page.wait_for_timeout(2000)
        recorder.save_new_responses("after-login")

        if element_filter.confirm_login_form_open(
            parsed_content, img_w, img_h
        ):
            print(
                "[!] Login form still present — submission may have failed "
                "or credentials rejected."
            )
        else:
            print("[+] Login form gone — submission likely succeeded.")

    finally:
        sure, maybe = find_websites(site_folder, exclude_paths=[output_file])
        output_path = write_results(sure, maybe, output_file)
        print(f"Results written to {output_path.resolve()}")
        browser.close()


if __name__ == "__main__":
    main()