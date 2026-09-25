This project downloads a website's front end and source files.

Usage:

```text
python3 grab.py <url> [output_folder]
python3 find_sites.py [download_folder] [output_file.txt]
```

Running `grab.py` downloads the website into `downloaded/<site-name>/`, scans
the captured files, and writes `websites.txt` inside that same site folder. Page
loading waits for `domcontentloaded` and then captures resources for the scroll
window, so persistent WebSocket connections do not block the download
indefinitely.

The authenticated automation flow can be run with:

```text
python3 web-automation/main.py
```

It captures network resources from the shared browser session before and after
login, stores them under `downloaded/<site-name>/`, and regenerates that site's
`websites.txt` after the flow finishes.