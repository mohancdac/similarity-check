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


def find_websites(folder="downloaded", exclude_paths=None):
    domain_endings = load_domain_endings()
    sure = set()
    maybe = set()
    excluded = {
        Path(path).resolve()
        for path in (exclude_paths or [])
    }

    for file_path in Path(folder).rglob("*"):
        if not file_path.is_file() or file_path.resolve() in excluded:
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


def format_results(sure, maybe):
    lines = [f"=== {len(sure)} websites (found in links and emails) ==="]
    lines.extend(sure)
    lines.extend([
        "",
        f"=== {len(maybe)} maybe websites (bare names in quotes, check by eye) ===",
    ])
    lines.extend(maybe)
    return "\n".join(lines) + "\n"


def write_results(sure, maybe, output_file="websites.txt"):
    output_path = Path(output_file)
    if output_path.suffix.lower() != ".txt":
        output_path = output_path.with_suffix(output_path.suffix + ".txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    output_path.write_text(format_results(sure, maybe))
    return output_path


if __name__ == "__main__":
    # python find_sites.py wfix.fun           -> reads downloaded/wfix.fun/, writes downloaded/wfix.fun/websites.txt
    # python find_sites.py wfix.fun myfolder  -> reads myfolder/wfix.fun/,   writes myfolder/wfix.fun/websites.txt
    if len(sys.argv) < 2:
        sys.exit("usage: python find_sites.py <site_name> [downloads_folder]")

    site_name = sys.argv[1]
    site_name = site_name.replace("https://", "").replace("http://", "")
    site_name = site_name.strip("/").replace("/", "_").replace(":", "_")

    if len(sys.argv) >= 3:
        downloads_folder = sys.argv[2]
    else:
        downloads_folder = "downloaded"

    site_folder = Path(downloads_folder, site_name)
    if not site_folder.is_dir():
        sys.exit(f"{site_folder} not found; run: python grab.py {site_name}")

    output_file = site_folder / "websites.txt"
    sure, maybe = find_websites(site_folder, exclude_paths=[output_file])
    output_path = write_results(sure, maybe, output_file)
    print(f"{len(sure)} websites and {len(maybe)} maybe websites saved to {output_path.resolve()}")
