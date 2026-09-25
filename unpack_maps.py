import json
import sys
from pathlib import Path

from grab import local_path


def unpack_map(map_path, output_folder):
    """Write out every original file stored inside one .map file. Returns how many were written.

    A source map is JSON like:
      {"sources": ["webpack://app/./src/App.tsx", ...],
       "sourcesContent": ["import React from 'react' ...", ...]}
    sources[0] is the file name, sourcesContent[0] is its original code, and so on.
    """
    source_map = json.loads(map_path.read_text(encoding="utf-8", errors="ignore"))
    sources = source_map.get("sources", [])
    contents = source_map.get("sourcesContent") or []

    written = 0
    for index in range(len(sources)):
        # Some maps only list the file names, without the code. Nothing to recover then.
        if index >= len(contents) or contents[index] is None:
            continue

        # "webpack://app/./src/App.tsx"  ->  output_folder/app/src/App.tsx
        # local_path also drops "..", so a map can never write outside output_folder.
        file_path = local_path(sources[index], output_folder)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(contents[index], encoding="utf-8")
        except OSError as error:
            print(f"skip {sources[index]}: {error}")
            continue
        written = written + 1

    return written


def unpack_all(downloaded_folder="downloaded", output_folder="original_sources"):
    """Unpack every .map file in downloaded_folder into output_folder/<site>/<host>/..."""
    total = 0

    for map_path in sorted(Path(downloaded_folder).rglob("*.map")):
        # Keep each site's code apart:
        #   downloaded/wfix.fun/cdn.site.com/...  ->  original_sources/wfix.fun/cdn.site.com/...
        parts = map_path.relative_to(downloaded_folder).parts
        site_name = parts[0]
        host = parts[1]

        try:
            count = unpack_map(map_path, Path(output_folder, site_name, host))
        except ValueError as error:  # not valid JSON
            print(f"skip {map_path}: {error}")
            continue

        print(f"{count} files from {map_path}")
        total = total + count

    full_folder_path = Path(output_folder).resolve()
    print(f"{total} original files saved under {full_folder_path}")
    return total


if __name__ == "__main__":
    # python unpack_maps.py                          -> downloaded -> original_sources
    # python unpack_maps.py myfolder mysources       -> myfolder   -> mysources
    if len(sys.argv) >= 2:
        downloaded_folder = sys.argv[1]
    else:
        downloaded_folder = "downloaded"

    if len(sys.argv) >= 3:
        output_folder = sys.argv[2]
    else:
        output_folder = "original_sources"

    unpack_all(downloaded_folder, output_folder)
