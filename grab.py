import sys
from pathlib import Path
from urllib.parse import urlparse

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


def grab(url, output_folder="downloaded"):
   

    if "://" not in url:
        url = "https://" + url

    saved_files = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()

        
        responses = []

        def remember_response(response):
            responses.append(response)

        page.on("response", remember_response)

        # Open the page and wait until nothing more is loading.
        page.goto(url, wait_until="networkidle")

        # Scroll to the bottom: some sites only load more files when you scroll.
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)  

        for response in responses:

            scheme = urlparse(response.url).scheme
            if scheme != "http" and scheme != "https":
                continue

            file_path = local_path(response.url, output_folder)

            try:
                content = response.body()
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(content)
            except Exception as error:
                # Happens for redirects (they have no content) and rare name clashes.
                print(f"skip {response.url}: {error}")
                continue

            saved_files.append(file_path)
            print(f"saved {file_path}")

        browser.close()

    full_folder_path = Path(output_folder).resolve()
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
