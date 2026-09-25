import random
import time
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
import config


class BrowserController:
    def __init__(self, headless=False):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.context = self.browser.new_context(
            viewport=config.VIEWPORT,
            device_scale_factor=1,  # keeps OmniParser pixel coords 1:1 with the page
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        self.page = self.context.new_page()

        # Native JS dialogs (alert/confirm/prompt) are handled independently
        # of OmniParser and cannot interfere with the rest of the workflow.
        self.page.on("dialog", self._handle_dialog)

    def _handle_dialog(self, dialog):
        try:
            dialog.dismiss()
        except Exception:
            pass

    def dismiss_role_dialogs(self, max_attempts=2):
        """
        Best-effort handling of visible HTML modal dialogs.

        Only high-confidence dismissal controls INSIDE a visible
        [role="dialog"] / [aria-modal="true"] are clicked.
        Generic Accept/Allow/Continue/Submit/Login controls are never used.
        """
        dismissed = 0

        for _ in range(max_attempts):
            try:
                clicked = self.page.evaluate(
                    """
                    () => {
                        const normalize = s => (s || "")
                            .replace(/\\s+/g, " ")
                            .trim()
                            .toLowerCase();

                        const visible = el => {
                            if (!el) return false;
                            const r = el.getBoundingClientRect();
                            const s = getComputedStyle(el);
                            return (
                                r.width > 2 &&
                                r.height > 2 &&
                                s.display !== "none" &&
                                s.visibility !== "hidden" &&
                                Number(s.opacity || 1) > 0
                            );
                        };

                        const safe = new Set([
                            "close",
                            "dismiss",
                            "no thanks",
                            "no thank you",
                            "not now",
                            "maybe later",
                            "later",
                            "cancel",
                            "x",
                            "×"
                        ]);

                        const dialogs = Array.from(
                            document.querySelectorAll(
                                '[role="dialog"], [aria-modal="true"]'
                            )
                        );

                        for (const dialog of dialogs) {
                            if (!visible(dialog)) continue;

                            const controls = Array.from(
                                dialog.querySelectorAll(
                                    'button, [role="button"], ' +
                                    'input[type="button"], input[type="submit"], a'
                                )
                            );

                            for (const control of controls) {
                                if (!visible(control)) continue;

                                const label = normalize(
                                    control.getAttribute("aria-label") ||
                                    control.getAttribute("title") ||
                                    control.innerText ||
                                    control.value
                                );

                                if (!safe.has(label)) continue;

                                try {
                                    control.scrollIntoView({
                                        block: "center",
                                        inline: "center"
                                    });
                                    control.click();
                                    return true;
                                } catch (_) {}
                            }
                        }

                        return false;
                    }
                    """
                )
            except Exception:
                break

            if not clicked:
                break

            dismissed += 1
            self._human_pause(0.2, 0.4)
            try:
                self.page.wait_for_timeout(250)
            except Exception:
                break

        return dismissed

    def wait_for_rendering(self, timeout_ms=20000, poll_ms=500):
        """
        Bounded Playwright readiness wait for heavy JS pages.

        DOMContentLoaded can occur before React/Vue/Angular has painted the
        useful UI. This waits for basic rendered content without looking for
        any login-specific selectors.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0

        while time.monotonic() < deadline:
            try:
                has_content = bool(self.page.evaluate(
                    """() => {
                        const body = document.body;
                        if (!body) return false;
                        const text = (body.innerText || '').trim();
                        const count = body.querySelectorAll('*').length;
                        return text.length > 0 || count >= 20;
                    }"""
                ))
            except Exception:
                has_content = False

            self.dismiss_role_dialogs()

            if has_content:
                self.page.wait_for_timeout(300)
                self.dismiss_role_dialogs()
                return True

            self.page.wait_for_timeout(poll_ms)

        self.dismiss_role_dialogs()
        return False

    # ---------- navigation ----------

    def open(self, url: str):
        self.page.goto(url, wait_until="domcontentloaded", timeout=1000000)
        self._human_pause(2.5, 4.5)

        # Preserve the existing navigation behavior while giving heavy
        # client-rendered pages a bounded opportunity to paint.
        self.wait_for_rendering(timeout_ms=20000, poll_ms=500)

        # Final popup pass immediately before main.py's first screenshot.
        self.dismiss_role_dialogs()

    # ---------- screenshots ----------

    def screenshot(self, path=None):
        path = path or config.SCREENSHOT_PATH
        self.page.screenshot(path=path, full_page=False)
        return path

    # ---------- human-like timing ----------

    def _human_pause(self, min_s=0.3, max_s=1.2):
        time.sleep(random.uniform(min_s, max_s))

    # ---------- mouse / keyboard (no DOM selectors) ----------

    def human_mouse_move(self, x: float, y: float):
        steps = random.randint(15, 30)
        self.page.mouse.move(
            x + random.uniform(-3, 3), y + random.uniform(-3, 3), steps=steps
        )
        self._human_pause(0.1, 0.3)

    def mouse_click(self, x: float, y: float):
        self.human_mouse_move(x, y)
        self._human_pause(0.15, 0.4)
        self.page.mouse.down()
        self._human_pause(0.05, 0.15)
        self.page.mouse.up()
        self._human_pause(0.3, 0.8)

    def type_text(self, text: str):
        for ch in text:
            self.page.keyboard.type(ch, delay=random.uniform(60, 180))

    def mouse_type(self, x: float, y: float, text: str):
        self.mouse_click(x, y)
        self._human_pause(0.2, 0.5)
        self.type_text(text)
        self._human_pause(0.3, 0.7)

    # ---------- fallback 2: visual region-change confirmation ----------

    def region_changed(self, img_before_path, img_after_path, bbox_px, min_diff_area=20):
        before = Image.open(img_before_path).convert("RGB").crop(tuple(bbox_px))
        after = Image.open(img_after_path).convert("RGB").crop(tuple(bbox_px))
        diff = ImageChops.difference(before, after)
        box = diff.getbbox()
        if box is None:
            return False
        area = (box[2] - box[0]) * (box[3] - box[1])
        return area >= min_diff_area

    # ---------- fallback 3: accessibility / DOM semantic check (read-only) ----------

    def get_ax_node_near_point(self, x: float, y: float):
        handle = self.page.evaluate_handle(
            "([x, y]) => document.elementFromPoint(x, y)", [x, y]
        )
        if handle is None:
            return None
        element = handle.as_element()
        if element is None:
            return None
        try:
            info = element.evaluate(
                """el => ({
                    tag: el.tagName,
                    type: el.getAttribute('type'),
                    role: el.getAttribute('role'),
                    ariaLabel: el.getAttribute('aria-label'),
                    placeholder: el.getAttribute('placeholder'),
                    name: el.getAttribute('name'),
                })"""
            )
        except Exception:
            return None
        return info

    def tab_to_field(self, direction="forward"):
        key = "Tab" if direction == "forward" else "Shift+Tab"
        self.page.keyboard.press(key)
        self._human_pause(0.2, 0.4)

    def fallback_tab_fill_login(self, identifier_value: str, password_value: str, anchor_center: tuple):
        """
        Used when structural/visual field detection is incomplete.
        Clicks the one confidently-known field (the anchor, usually password),
        then tabs backward to reach the identifier field, types, tabs forward
        twice (through password) to reach submit, and presses Enter.
        """
        self.mouse_click(*anchor_center)
        self._human_pause(0.2, 0.4)

        # Assume anchor is the password field: go back one to reach identifier
        self.tab_to_field("backward")
        self.type_text(identifier_value)

        # Forward once to return to password
        self.tab_to_field("forward")
        self.type_text(password_value)

        # Forward again to reach submit, then activate via keyboard (Enter)
        self.tab_to_field("forward")
        self._human_pause(0.3, 0.6)
        self.page.keyboard.press("Enter")

    # ---------- teardown ----------

    def close(self):
        self._human_pause(0.5, 1.5)
        self.context.close()
        self.browser.close()
        self.playwright.stop()