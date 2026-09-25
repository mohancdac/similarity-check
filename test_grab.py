import functools
import http.server
import tempfile
import threading
from pathlib import Path

from grab import grab, local_path, save_file

# path sanitising: no escaping the output dir
assert local_path("http://x.com/../../etc/passwd", "out") == Path("out/x.com/etc/passwd")
assert local_path("http://x.com/", "out") == Path("out/x.com/index.html")
assert local_path("http://x.com/a.js?v=1", "out") == Path("out/x.com/a.js_v_1")

# a URL that is both a file and a folder: both get saved, the second under a flat name
with tempfile.TemporaryDirectory() as out:
    first = save_file("https://api.x.com/books/site.co", b"info", out)
    second = save_file("https://api.x.com/books/site.co/contact?a=1", b"contacts", out)
    assert first == Path(out, "api.x.com/books/site.co") and first.read_bytes() == b"info"
    assert second == Path(out, "api.x.com/books_site.co_contact_a_1") and second.read_bytes() == b"contacts"

    # and the other order: the folder exists first, then the file is wanted
    save_file("https://api.x.com/a/b/c.json", b"c", out)
    third = save_file("https://api.x.com/a/b", b"b", out)
    assert third == Path(out, "api.x.com/a_b") and third.read_bytes() == b"b"

# end to end: serve a page with a static and a dynamically loaded script
with tempfile.TemporaryDirectory() as site, tempfile.TemporaryDirectory() as out:
    Path(site, "static").mkdir()
    Path(site, "index.html").write_text('<script src="static/main.js"></script>')
    Path(site, "static/main.js").write_text(
        "const s=document.createElement('script');s.src='static/chunk.js';document.head.append(s);")
    Path(site, "static/chunk.js").write_text("console.log('lazy')")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=site)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"127.0.0.1_{server.server_port}"

    grab(f"http://127.0.0.1:{server.server_port}/", out)
    server.shutdown()

    for f in ("index.html", "static/main.js", "static/chunk.js"):
        assert Path(out, host, host, f).read_bytes() == Path(site, f).read_bytes(), f

print("ok")
