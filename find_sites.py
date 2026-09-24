import re
import sys
from pathlib import Path

DOMAIN_ENDINGS_FILE = Path(__file__).parent / "tlds.txt"

WEBSITE = r"([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+)"

LINK_PATTERN = re.compile("//" + WEBSITE)

EMAIL_PATTERN = re.compile("[a-zA-Z0-9._%+-]@" + WEBSITE)


QUOTED_PATTERN = re.compile("[\"'`]" + WEBSITE + "(?=[\"'`/:])")


def load_domain_endings():
    """Read tlds.txt and return a set like {"com", "xyz", "in", ...}."""
    endings = set()
    for line in DOMAIN_ENDINGS_FILE.read_text().splitlines():
        if line.startswith("#"):  # the first line is a comment with the date
            continue
        endings.add(line.strip().lower())
    return endings


def is_real_domain(name, domain_endings):
    ending = name.split(".")[-1]
    return ending in domain_endings


def find_websites_in_text(text, pattern, domain_endings):
    
    websites = []
    for name in pattern.findall(text):
        name = name.lower()
        if is_real_domain(name, domain_endings):
            websites.append(name)
    return websites


def find_websites(folder="downloaded"):
    domain_endings = load_domain_endings()
    sure = set()
    maybe = set()

    for file_path in Path(folder).rglob("*"):
        if not file_path.is_file():
            continue

        text = file_path.read_text(errors="ignore")

        for website in find_websites_in_text(text, LINK_PATTERN, domain_endings):
            sure.add(website)
        for website in find_websites_in_text(text, EMAIL_PATTERN, domain_endings):
            sure.add(website)
        for website in find_websites_in_text(text, QUOTED_PATTERN, domain_endings):
            maybe.add(website)

    maybe = maybe - sure

    return sorted(sure), sorted(maybe)


if __name__ == "__main__":

    if len(sys.argv) >= 2:
        folder = sys.argv[1]
    else:
        folder = "downloaded"

    sure, maybe = find_websites(folder)

    print(f"=== {len(sure)} websites (found in links and emails) ===")
    for website in sure:
        print(website)

    print()
    print(f"=== {len(maybe)} maybe websites (bare names in quotes, check by eye) ===")
    for website in maybe:
        print(website)
