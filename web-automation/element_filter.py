import re
import config


# ---------- basic helpers ----------

def normalize_bbox_to_pixels(bbox_norm, img_width, img_height):
    x1, y1, x2, y2 = bbox_norm
    return [x1 * img_width, y1 * img_height, x2 * img_width, y2 * img_height]


def bbox_center(bbox_px):
    x1, y1, x2, y2 = bbox_px
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def get_element_text(element: dict) -> str:
    raw = element.get("content") or ""
    text = raw.casefold().replace("-", " ")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------- robust keyword matching ----------

def _word_match(text: str, keyword: str) -> bool:
    return re.search(
        rf"\b{re.escape(keyword.casefold())}\b",
        text
    ) is not None


def contains_excluded(text: str) -> bool:
    return any(
        _word_match(text, kw)
        for kw in config.EXCLUDE_KEYWORDS
    )


def matches_field(text: str, field_name: str) -> bool:
    if contains_excluded(text):
        return False
    return any(
        _word_match(text, kw)
        for kw in config.FIELD_KEYWORDS.get(field_name, [])
    )


def matches_login_trigger(text: str) -> bool:
    if contains_excluded(text):
        return False
    return any(
        _word_match(text, kw)
        for kw in config.LOGIN_TRIGGER_KEYWORDS
    )


# ---------- identifier detection ----------

def _identifier_match(text: str) -> bool:
    return any(
        matches_field(text, field_name)
        for field_name in ("username", "email", "phone")
    )


def _placeholder_match(text: str, field_name: str) -> bool:
    """
    Return True when *text* looks like the actual input placeholder for a
    username/email/phone field.

    Placeholder phrases are intentionally treated separately from normal
    field keywords. This prevents a tab or label such as ``Email`` from
    competing equally with a nearby input placeholder such as
    ``Please enter the email address``.
    """
    if contains_excluded(text):
        return False

    configured = config.IDENTIFIER_PLACEHOLDER_KEYWORDS.get(field_name, [])
    if any(_word_match(text, kw) for kw in configured):
        return True

    # Generic fallback for sites whose placeholder wording is not explicitly
    # listed in config.py. We still require a field-specific keyword.
    if not text.startswith(config.PLACEHOLDER_PREFIXES):
        return False

    return matches_field(text, field_name)


def _identifier_placeholder_type(text: str):
    """Return the identifier type if text is a placeholder, else None."""
    for field_name in ("email", "phone", "username"):
        if _placeholder_match(text, field_name):
            return field_name
    return None


def _identifier_score(text: str, interactive: bool, source: str) -> float:
    score = 0.0

    # Directly interactive candidates remain strong.
    score += 50.0 if interactive else 0.0

    # OCR/YOLO content tends to provide useful visual anchors.
    score += 10.0 if source.startswith("box_yolo") else 0.0

    # CRITICAL PRIORITY: a placeholder is a much better anchor than a generic
    # field label/tab when interactivity is false. The large bonus makes
    # non-interactive placeholders outrank ordinary non-interactive keywords.
    placeholder_type = _identifier_placeholder_type(text)
    if placeholder_type:
        score += 40.0

    # More specific field terms receive the existing weight.
    if any(_word_match(text, kw) for kw in config.FIELD_KEYWORDS["email"]):
        score += 15.0
    if any(_word_match(text, kw) for kw in config.FIELD_KEYWORDS["phone"]):
        score += 14.0
    if any(_word_match(text, kw) for kw in config.FIELD_KEYWORDS["username"]):
        score += 13.0

    return score


def _classify_ax_role(ax_info: dict):
    """
    Resolve the effective accessibility role for a candidate element from
    the raw dict returned by BrowserController.get_ax_node_near_point.

    A real text input has an effective role of "textbox" (confirmed via
    Chrome's Accessibility Inspector: role="textbox" plus a default
    action of "Activate" on the actual <input> DOMNode). A tab/toggle
    control carrying the same keyword text (e.g. a "Phone" tab above a
    "Phone number" input) does not resolve to "textbox" even when it is
    interactive.

    Playwright has no API that reports the "Activate" action itself, so
    this uses "role" instead, falling back to tag/type when no explicit
    role attribute is present (plain <input> elements rarely carry an
    explicit role="" attribute despite having an implicit textbox role).
    """
    if not ax_info:
        return None

    explicit = (ax_info.get("role") or "").strip().lower()
    if explicit:
        return explicit

    tag = (ax_info.get("tag") or "").lower()
    itype = (ax_info.get("type") or "").lower()

    if tag == "textarea":
        return "textbox"
    if tag == "input":
        if itype in ("", "text", "email", "tel", "search", "password", "number", "url"):
            return "textbox"
        if itype == "radio":
            return "radio"
        if itype == "checkbox":
            return "checkbox"
        if itype in ("button", "submit"):
            return "button"
    if tag == "button":
        return "button"
    if tag == "a":
        return "link"

    return "generic"


def find_identifier_field(parsed_content, img_w, img_h, browser=None):
    """
    Identifier strategy (vision-first; DOM is a fallback check only, never
    part of scoring or of the primary detection pass):

      1) placeholder + interactivity=True
         -> direct mouse interaction with the placeholder candidate.

      2) placeholder + interactivity=False
         -> click the placeholder itself as the mouse anchor.

      3) ordinary identifier keyword/label
         -> fallback anchor only when no placeholder candidate is available.

    All candidates are found and scored purely from OmniParser's output,
    exactly as before -- no DOM/live-page dependency in this part at all.

    Fallback role verification (new):
      DOM is consulted ONLY when, after scoring, the top candidate is:
        - interactivity=True, AND
        - has no placeholder text of its own.
      That is precisely the ambiguous case: a bare keyword/label hit is
      exactly what a same-labeled tab/toggle control also produces, and a
      placeholder-bearing candidate doesn't need this check because the
      placeholder bonus already makes it a reliable pick on its own.

      In that narrow case only, the live accessibility role at the
      candidate's center is checked (via `browser`, if provided). If it
      resolves to "textbox", the candidate is accepted. If it resolves to
      anything else (tab, radio, button, link), the candidate is skipped
      and the next best-scoring candidate is tried the same way. If no
      candidate ever passes, the original top-scoring candidate is
      returned anyway (fail-safe: something is better than nothing).

      If `browser` is None, this fallback is never invoked and behavior is
      identical to the original keyword-only implementation.

    No geometric search for a separate input rectangle is used.
    """
    candidates = []

    for el in parsed_content:
        text = get_element_text(el)
        if not text or len(text.split()) > 8:
            continue
        if not _identifier_match(text):
            continue

        bbox_px = normalize_bbox_to_pixels(
            el["bbox"], img_w, img_h
        )
        interactive = bool(el.get("interactivity"))
        placeholder_type = _identifier_placeholder_type(text)
        strategy = (
            "interactive_placeholder"
            if interactive and placeholder_type
            else "interactive"
            if interactive
            else "placeholder_anchor"
            if placeholder_type
            else "keyword_anchor"
        )

        # Broad confirmation region around the keyword/placeholder.
        confirm_bbox_px = [
            max(0, bbox_px[0] - 25),
            max(0, bbox_px[1] - 15),
            min(img_w, bbox_px[2] + 380),
            min(img_h, bbox_px[3] + 120),
        ]

        candidates.append((
            _identifier_score(
                text,
                interactive,
                el.get("source", "")
            ),
            {
                "text": text,
                "center": bbox_center(bbox_px),
                "raw": el,
                "strategy": strategy,
                "confirm_bbox_px": confirm_bbox_px,
                "interactive": interactive,
                "placeholder_type": placeholder_type,
            },
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: -item[0]
    )

    for _, candidate in candidates:
        # Placeholder present, or not interactive -> already unambiguous,
        # never touch the DOM for these.
        is_ambiguous = candidate["interactive"] and not candidate["placeholder_type"]
        if browser is None or not is_ambiguous:
            return candidate

        try:
            ax_info = browser.get_ax_node_near_point(*candidate["center"])
            ax_role = _classify_ax_role(ax_info)
        except Exception:
            ax_role = None

        # Fail open: an inconclusive DOM read still trusts the keyword hit
        # rather than blocking on it.
        if ax_role in (None, "textbox"):
            return candidate
        # Otherwise this looks like a tab/toggle wearing the same label as
        # the real field -- skip it and try the next best candidate.

    # Every interactive, placeholder-less candidate resolved to a
    # tab/toggle. Fall back to the single best-scoring candidate overall.
    return candidates[0][1]


# ---------- password keyword detection ----------

def _password_candidates(parsed_content, img_w, img_h):
    """
    Password detection is now keyword-driven only.

    IMPORTANT:
      - Excluded false positives are rejected.
      - interactivity=True is preferred.
      - interactivity=False is still accepted as a password anchor.
      - The password is NOT located using password/eye geometry.
      - main.py uses Tab to reach the password field.
    """
    candidates = []

    for el in parsed_content:
        text = get_element_text(el)
        if not text or len(text.split()) > 8:
            continue
        if not matches_field(text, "password"):
            continue

        bbox_px = normalize_bbox_to_pixels(
            el["bbox"], img_w, img_h
        )
        interactive = bool(el.get("interactivity"))

        score = 0.0
        score += 50.0 if interactive else 0.0
        score += 10.0 if el.get("source", "").startswith("box_yolo") else 0.0
        score += 20.0 if _word_match(text, "password") else 0.0
        score += 5.0 if _word_match(text, "passcode") else 0.0
        score += 3.0 if _word_match(text, "pin") else 0.0

        # Fallback visual region centered around the detected password
        # keyword if the eye icon is absent.
        confirm_bbox_px = [
            max(0, bbox_px[0] - 40),
            max(0, bbox_px[1] - 55),
            min(img_w, bbox_px[2] + 380),
            min(img_h, bbox_px[3] + 120),
        ]

        candidates.append((
            score,
            {
                "text": text,
                "center": bbox_center(bbox_px),
                "raw": el,
                "strategy": "tab_password",
                "confirm_bbox_px": confirm_bbox_px,
            },
        ))

    candidates.sort(
        key=lambda item: -item[0]
    )
    return candidates


def find_password_eye_icon(parsed_content, img_w, img_h):
    """
    Find a likely eye/visibility icon used by a password field.

    The eye itself is the anchor only. It is NOT used to locate or click the
    password field. main.py uses the eye position to confirm that the region
    immediately to its left changed after Tab + password typing.
    """
    candidates = []

    for el in parsed_content:
        text = get_element_text(el)
        if not text:
            continue

        if not any(
            hint.casefold() in text
            for hint in config.EYE_ICON_HINTS
        ):
            continue

        bbox_px = normalize_bbox_to_pixels(
            el["bbox"], img_w, img_h
        )

        score = 0.0
        score += 30.0 if el.get("interactivity") else 0.0
        score += 10.0 if el.get("source", "").startswith("box_yolo") else 0.0
        score += 10.0 if _word_match(text, "eye") else 0.0
        score += 8.0 if _word_match(text, "visibility") else 0.0

        candidates.append((
            score,
            {
                "text": text,
                "center": bbox_center(bbox_px),
                "bbox_px": bbox_px,
                "raw": el,
            },
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: -item[0]
    )
    return candidates[0][1]


# ---------- submit detection ----------

def find_submit_button(parsed_content, img_w, img_h):
    """
    Submit detection is global.

    Require:
      - interactivity=True
      - submit-related keyword

    No password-relative geometry is used.
    """
    candidates = []

    for el in parsed_content:
        if not el.get("interactivity"):
            continue

        text = get_element_text(el)
        if not text or len(text.split()) > 8:
            continue
        if contains_excluded(text):
            continue
        if not matches_field(text, "submit"):
            continue

        bbox_px = normalize_bbox_to_pixels(
            el["bbox"], img_w, img_h
        )

        score = 20.0

        strong_terms = (
            "submit",
            "log in",
            "login",
            "sign in",
            "signin",
            "sign-in",
            "log",
        )
        medium_terms = (
            "continue",
            "confirm",
        )

        if any(
            _word_match(text, term)
            for term in strong_terms
        ):
            score += 25.0
        elif any(
            _word_match(text, term)
            for term in medium_terms
        ):
            score += 12.0

        score += 10.0 if el.get(
            "source", ""
        ).startswith("box_yolo") else 0.0

        candidates.append((
            score,
            {
                "text": text,
                "center": bbox_center(bbox_px),
                "raw": el,
                "strategy": "interactive",
            },
        ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: -item[0]
    )
    return candidates[0][1]


# ---------- login form confirmation ----------

def confirm_login_form_open(parsed_content, img_w, img_h) -> bool:
    # Login-form detection remains keyword-driven.
    # The password keyword does not need interactivity=True.
    for el in parsed_content:
        if matches_field(
            get_element_text(el),
            "password"
        ):
            return True

    return False


def locate_login_trigger(parsed_content, img_w, img_h):
    best, best_score = None, 0

    for el in parsed_content:
        text = get_element_text(el)
        if not text or len(text.split()) > 3:
            continue
        if not matches_login_trigger(text):
            continue

        score = 10 if el.get("interactivity") else 0
        score += 5 if el.get(
            "source", ""
        ).startswith("box_yolo") else 0

        if score >= best_score:
            best_score = score
            bbox_px = normalize_bbox_to_pixels(
                el["bbox"], img_w, img_h
            )
            best = {
                "text": text,
                "center": bbox_center(bbox_px),
                "raw": el,
            }

    return best


def locate_credential_fields(parsed_content, img_w, img_h, browser=None):
    """
    Final upgraded hierarchy:

      IDENTIFIER
        - keyword + interactive=True + live role=textbox -> direct click/type
        - keyword + interactive=True + live role!=textbox (tab/radio/button/
          link) -> demoted, click keyword/placeholder anchor instead
        - keyword + interactive=False -> click keyword/placeholder anchor

      PASSWORD
        - any real, non-excluded password keyword is enough to establish the
          password anchor.
        - no password geometry.
        - no eye-based password-field locator.
        - main.py presses Tab after the identifier.

      SUBMIT
        - interactive=True + submit keyword.
        - no geometry.

    `browser` is optional and only used inside find_identifier_field's
    fallback role check (see its docstring) -- it is consulted at most once
    per ambiguous top candidate, never for every candidate. Pass None to
    skip the check entirely and keep the original keyword-only behavior.
    """
    id_field = find_identifier_field(
        parsed_content,
        img_w,
        img_h,
        browser=browser
    )

    password_candidates = _password_candidates(
        parsed_content,
        img_w,
        img_h
    )
    pw_field = (
        password_candidates[0][1]
        if password_candidates
        else None
    )

    submit_field = find_submit_button(
        parsed_content,
        img_w,
        img_h
    )

    return id_field, pw_field, submit_field


def ax_confirms_field(ax_info: dict, expected: str) -> bool:
    if not ax_info:
        return False

    tag = (ax_info.get("tag") or "").lower()
    itype = (ax_info.get("type") or "").lower()
    role = (ax_info.get("role") or "").lower()
    label = (ax_info.get("ariaLabel") or "").lower()
    placeholder = (ax_info.get("placeholder") or "").lower()
    name = (ax_info.get("name") or "").lower()
    combined = f"{label} {placeholder} {name}"

    if expected == "password":
        return (
            itype == "password"
            or "pass" in combined
        )

    if expected == "identifier":
        is_input = (
            tag == "input"
            and itype in ("text", "email", "tel", "")
        )
        return is_input and any(
            kw in combined
            for kw in (
                "user",
                "email",
                "phone",
                "account",
                "mobile",
            )
        )

    if expected == "submit":
        is_button_like = (
            tag == "button"
            or itype == "submit"
            or role == "button"
        )
        return is_button_like and any(
            kw in combined
            for kw in (
                "login",
                "log in",
                "sign in",
                "submit",
                "continue",
                "confirm",
            )
        )

    return False