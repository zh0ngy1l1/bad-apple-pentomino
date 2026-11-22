"""Recover the one RGB still from its pinned upstream run-length encoded frame."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import urlopen

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
URL = ("https://raw.githubusercontent.com/SirPigari/bad-apple-api/"
       "02584fdee35c5ba4d003402a20660377fbeccbb4/api/framedata/30fps/frame0226.json")
DIGEST = "de4b4f9e1290de1ee8711b504ec4c173fd15294de46e94024937a2c9cb118cd3"
RGB_DIGEST = "0f81fa82dcee8c7a8725cb2d93adbabce0baac0a93939ba7f561532bf684e9ff"


def main():
    # Pass a downloaded JSON path to use the same decoder without network access.
    if len(sys.argv) > 1:
        raw = Path(sys.argv[1]).read_bytes()
    else:
        with urlopen(URL, timeout=30) as response:
            raw = response.read()
    if hashlib.sha256(raw).hexdigest() != DIGEST:
        raise ValueError("Unexpected source bytes")
    data = json.loads(raw)
    values, lengths = np.asarray(data["pixel_data"]).T
    rgb = np.repeat(values.astype(np.uint8), lengths).reshape(data["height"],data["width"],3)
    if data["sound_timestamp"] != 7.5 or hashlib.sha256(rgb.tobytes()).hexdigest() != RGB_DIGEST:
        raise ValueError("Unexpected decoded frame")
    Image.fromarray(rgb).save(ROOT/"data/frame0226.png")
    print("Recovered the 480 × 360 RGB frame at 7.500 s.")


if __name__ == "__main__":
    main()
