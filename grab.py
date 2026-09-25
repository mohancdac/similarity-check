import sys
import shutil
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def make_safe(text):
    safe_text = ""
    for character in text:
        if character.isalnum() or character in "._-":
            safe_text = safe_text + character
        else:
            safe_text = safe_text + "_"
    return safe_text


def local_path(url, output_folder):
    parsed_url = urlparse(url)

    folders_and_file = []
    for piece in parsed_url.path.split("/"):
        if piece == "" or piece == "." or piece == "..":
            continue
        folders_and_file.append(piece)


    if len(folders_and_file) == 0 or parsed_url.path.endswith("/"):
        folders_and_file.append("index.html")


    if parsed_url.query != "":
        query = make_safe(parsed_url.query)
        query = query[:50]  # keep file names short
        folders_and_file[-1] = folders_and_file[-1] + "_" + query

    site_folder = parsed_url.netloc.replace(":", "_")

    return Path(output_folder, site_folder, *folders_and_file)


def save_file(url, content, site_folder):
    """Save the content of a URL under site_folder and return the path it was saved to."""
    file_path = local_path(url, site_folder)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        return file_path
    except OSError:
        pass

    # A URL can be both a file and a folder, for example:
    #   /books/site.co               -> a file called "site.co"
    #   /books/site.co/contact-list  -> needs "site.co" to be a folder
    # Then save it as one flat file instead:  books_site.co_contact-list
    parsed_url = urlparse(url)
    flat_name = make_safe(parsed_url.path.strip("/"))
    if parsed_url.query != "":
        flat_name = flat_name + "_" + make_safe(parsed_url.query)
    host_folder = parsed_url.netloc.replace(":", "_")

    file_path = Path(site_folder, host_folder, flat_name[:200])
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    return file_path


def site_name(url):
    if "://" not in url:
        url = "https://" + url
    return urlparse(url).netloc.replace(":", "_")


def reset_output_folder(output_folder, url=None):
    output_path = Path(output_folder)
    if url is not None:
        output_path = output_path / site_name(url)

    if output_path.is_dir():
        shutil.rmtree(output_path)
    elif output_path.exists():
        output_path.unlink()
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


class ResponseRecorder:
    def __init__(self, output_folder, url):
        self.site_folder = Path(output_folder) / site_name(url)
        self.responses = []
        self.saved_count = 0

    def attach(self, page):
        page.on("response", self._remember_response)

    def _remember_response(self, response):
        self.responses.append(response)

    def save_new_responses(self, phase):
        saved_files = []
        responses = self.responses[self.saved_count:]
        self.saved_count = len(self.responses)

        for response in responses:
            if urlparse(response.url).scheme not in {"http", "https"}:
                continue

            try:
                content = response.body()
                file_path = save_file(response.url, content, self.site_folder)
            except Exception as error:
                print(f"skip {response.url}: {error}")
                continue

            saved_files.append(file_path)
            print(f"saved ({phase}) {file_path}")

        print(f"{len(saved_files)} files saved for {phase}")
        return saved_files


def grab(url, output_folder="downloaded"):
    if "://" not in url:
        url = "https://" + url

    # Each site gets its own folder: downloaded/wfix.fun/...
    # (":" is replaced like in local_path, e.g. "localhost:8000" -> "localhost_8000")
    site_folder = Path(output_folder, site_name(url))

    saved_files = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()

        
        responses = []

        def remember_response(response):
            responses.append(response)

        page.on("response", remember_response)

        # Open the page and wait only until the HTML is ready and its scripts have started.
        # Waiting for "load" would also wait for every image, and sites with big
        # GIFs can take over 30 seconds for that, which made Playwright give up.
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # Then give everything else (scripts, images, lazy files) up to 30 seconds.
        # Sites with slow images or live data (odds, chat) may never go fully quiet,
        # so don't fail if they don't; just save what arrived.
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            print("page still loading after 30 seconds, saving what arrived so far")

        # Scroll to the bottom: some sites only load more files when you scroll.
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)  

        for response in responses:

            scheme = urlparse(response.url).scheme
            if scheme != "http" and scheme != "https":
                continue

            try:
                content = response.body()
            except Exception as error:
                # Happens for redirects: they have no content.
                print(f"skip {response.url}: {error}")
                continue

            try:
                file_path = save_file(response.url, content, site_folder)
            except OSError as error:
                print(f"skip {response.url}: {error}")
                continue

            saved_files.append(file_path)
            print(f"saved {file_path}")

        browser.close()

    full_folder_path = site_folder.resolve()
    print(f"{len(saved_files)} files saved under {full_folder_path}")
    return saved_files


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python grab.py <url> [output_folder]")

    url = sys.argv[1]

    if len(sys.argv) >= 3:
        output_folder = sys.argv[2]
    else:
        output_folder = "downloaded"

    grab(url, output_folder)

    from find_sites import find_websites, write_results

    site_folder = Path(output_folder, site_name(url))
    output_file = site_folder / "websites.txt"
    sure, maybe = find_websites(site_folder, exclude_paths=[output_file])
    output_path = write_results(sure, maybe, output_file)
    print(f"Results written to {output_path.resolve()}")
