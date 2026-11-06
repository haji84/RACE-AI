"""Fixed presentation assets for the initial official-profile illustration batch."""
import base64
import json

REGISTRATIONS = ('3415', '3897', '3941', '4238', '4320', '4444')
IMAGES = tuple('assets/racer-portraits/boat-' + number + '.webp' for number in REGISTRATIONS)
FILES = ('racer-portraits.js',) + IMAGES


def inline_script(body, read):
    """Embed only the fixed images for an offline, self-contained private export."""
    marker = 'const embedded = null;'
    if body.count(marker) != 1:
        raise ValueError('SAVED_PORTRAIT_SCRIPT_INVALID')
    images = {number: 'data:image/webp;base64,' + base64.b64encode(read(path)).decode('ascii')
              for number, path in zip(REGISTRATIONS, IMAGES)}
    return body.replace(marker, 'const embedded = ' + json.dumps(images, separators=(',', ':')) + ';')
