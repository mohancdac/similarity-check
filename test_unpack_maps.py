import json
import tempfile
from pathlib import Path

from unpack_maps import unpack_all

with tempfile.TemporaryDirectory() as downloaded, tempfile.TemporaryDirectory() as output:
    Path(downloaded, "site.com/cdn.site.com/assets").mkdir(parents=True)

    source_map = {
        "sources": [
            "webpack://app/./src/App.tsx",   # webpack style
            "../src/utils.ts",               # vite style
            "../../../../etc/evil.txt",      # tries to escape the output folder
            "src/no-code.ts",                # listed, but its code is missing (null)
        ],
        "sourcesContent": ["const app = 1", "const utils = 2", "evil", None],
    }
    Path(downloaded, "site.com/cdn.site.com/assets/main.js.map").write_text(json.dumps(source_map))
    Path(downloaded, "site.com/cdn.site.com/assets/broken.js.map").write_text("<html>not a map</html>")

    total = unpack_all(downloaded, output)

    assert total == 3, total
    assert Path(output, "site.com/cdn.site.com/app/src/App.tsx").read_text() == "const app = 1"
    assert Path(output, "site.com/cdn.site.com/src/utils.ts").read_text() == "const utils = 2"
    assert Path(output, "site.com/cdn.site.com/etc/evil.txt").read_text() == "evil"  # stayed inside
    assert not Path(output, "site.com/cdn.site.com/src/no-code.ts").exists()

print("ok")
