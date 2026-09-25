import os
import sys

OMNIPARSER_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "OmniParser")
)
sys.path.insert(0, OMNIPARSER_ROOT)

YOLO_MODEL_PATH = os.path.join(
    OMNIPARSER_ROOT,
    "weights/icon_detect/model.pt"
)
CAPTION_MODEL_PATH = os.path.join(
    OMNIPARSER_ROOT,
    "weights/icon_caption_florence"
)

VIEWPORT = {"width": 1280, "height": 800}
BOX_THRESHOLD = 0.05

SCREENSHOT_PATH = "current_screenshot.png"
BEFORE_CLICK_PATH = "before_click.png"
AFTER_CLICK_PATH = "after_click.png"
LABELED_SCREENSHOT_PATH = "labeled_screenshot.png"
PARSED_JSON_PATH = "parsed_content.json"

LOGIN_TRIGGER_KEYWORDS = [
    "log",
    "login",
    "log in",
    "log-in",
    "sign in",
    "signin",
    "sign-in",
]

FIELD_KEYWORDS = {
    "username": [
        "username",
        "user name",
        "user id",
        "userid",
        "user-id",
        "account",
        "account id",
        "login id",
        "login-id",
        "loginid",
        "member id",
        "customer id",
        "player id",
        "member",
        "account number",
        "Username",
    ],
    "email": [
        "email",
        "e-mail",
        "email address",
        "e mail address",
        "enter email",
        "enter your email",
        "enter email address",
        "enter your email address",
        "enter an email",
        "enter your email address",
        "mail address",
    ],
    "phone": [
        "phone",
        "phone number",
        "mobile",
        "mobile number",
        "phone no",
        "mobile no",
        "phoneno",
        "mobileno",
        "enter phone",
        "enter your phone",
        "enter phone number",
        "enter your phone number",
        "enter mobile",
        "enter your mobile",
        "enter mobile number",
        "enter your mobile number",
        "telephone",
        "telephone number",
        "contact number",
    ],
    "password": [
        "password",
        "pass word",
        "passcode",
        "pass code",
        "pin",
        "enter password",
        "enter your password",
        "enter passcode",
        "enter your passcode",
        "enter pin",
        "enter your pin",
    ],
    "submit": [
        "submit",
        "log in",
        "login",
        "sign in",
        "signin",
        "sign-in",
        "continue",
        "confirm",
        "log",
    ],
}

EXCLUDE_KEYWORDS = [
    "forgot",
    "forgot your password",
    "reset password",
    "reset your password",
    "continue with",
    "sign up",
    "signup",
    "sign-up",
    "create account",
    "create a new account",
    "don't have",
    "don't have an account",
    "do not have an account",
    "google",
    "facebook",
    "apple",
    "remember me",
    "remember password",
    "keep me signed in",
    "keep me logged in",
    "stay signed in",
    "new to",
    "register",
    "registration",
    "otp via",
    "resend",
    "help",
    "support",
    "privacy",
    "terms",
    "demo",
]

# Explicit placeholder-style phrases.
# These are intentionally separated from FIELD_KEYWORDS so that, when an
# identifier is non-interactive, a real input placeholder is preferred over
# a nearby tab/label such as "Email" or "Phone Number".
IDENTIFIER_PLACEHOLDER_KEYWORDS = {
    "username": [
        "enter username",
        "enter your username",
        "enter user name",
        "enter your user name",
        "enter user id",
        "enter your user id",
        "enter userid",
        "enter your userid",
        "please enter username",
        "please enter your username",
        "please enter user id",
        "please enter your user id",
        "type username",
        "type your username",
        "type user id",
        "type your user id",
        "input username",
        "input your username",
    ],
    "email": [
        "enter email",
        "enter your email",
        "enter email address",
        "enter your email address",
        "enter an email",
        "enter an email address",
        "please enter email",
        "please enter your email",
        "please enter email address",
        "please enter your email address",
        "type email",
        "type your email",
        "type email address",
        "type your email address",
        "input email",
        "input your email",
        "input email address",
        "input your email address",
    ],
    "phone": [
        "enter phone",
        "enter your phone",
        "enter phone number",
        "enter your phone number",
        "enter mobile",
        "enter your mobile",
        "enter mobile number",
        "enter your mobile number",
        "enter telephone",
        "enter telephone number",
        "please enter phone",
        "please enter your phone",
        "please enter phone number",
        "please enter your phone number",
        "please enter mobile number",
        "please enter your mobile number",
        "type phone",
        "type your phone",
        "type phone number",
        "type your phone number",
        "type mobile number",
        "type your mobile number",
        "input phone number",
        "input your phone number",
        "input mobile number",
        "input your mobile number",
        "+91(XXXX)XXX - XXX"
    ],
}

# Generic prefixes commonly used by real input placeholders.
# Used only after configured placeholder phrases are checked.
PLACEHOLDER_PREFIXES = (
    "enter ",
    "please enter ",
    "type ",
    "please type ",
    "input ",
    "please input ",
)

EYE_ICON_HINTS = [
    "eye",
    "visibility",
    "show password",
    "hide password",
]