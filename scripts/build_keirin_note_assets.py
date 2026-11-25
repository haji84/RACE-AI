"""Bundle the imported note into the existing allowlisted presentation assets."""
from hashlib import sha256
from pathlib import Path
import json


def build(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    web = root / 'web'
    parts = [web/'keirin-note-source/staking.js', web/'keirin-note-source/staking_flexible.js',
             web/'keirin-note-source/rollover.js', web/'confidence.js', web/'keirin-joint-forecast.js',
             web/'keirin-rider-history.js', web/'keirin-note-model.js', web/'keirin-note-feed.js', web/'keirin-note-view.js']
    original = (web/'race-app-core.js').read_bytes()
    prefix = b"if (typeof window === 'object' && typeof location === 'object') window.RaceNoteInitialFragment = location.hash;\n"
    bundle = prefix + original + b'\n' + b'\n'.join(path.read_bytes() for path in parts)
    (web/'app.js').write_bytes(bundle)
    css = (web/'race-style-core.css').read_bytes() + b'\n' + (web/'keirin-note.css').read_bytes()
    (web/'style.css').write_bytes(css)
    return dict(app_sha256=sha256(bundle).hexdigest(), style_sha256=sha256(css).hexdigest(),
                original_app_sha256=sha256(original).hexdigest(), additional_live_asset_paths=0)


if __name__ == '__main__':
    print(json.dumps(build(), sort_keys=True))
