"""Import the provided Site privately; print only receipt hashes and counts."""
import argparse
import json
from race_ai.keirin_note_view import import_site, seal_note


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-root', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--encrypted-dir', required=True)
    parser.add_argument('--private-dir', required=True)
    args = parser.parse_args()
    note = import_site(args.site_root, source_commit=args.source_commit)
    result = seal_note(note, args.encrypted_dir, args.private_dir)
    # File paths are owner-local output handles, not a URL containing a key.
    print(json.dumps(dict(result, dates=note['dates'], files=len(note['files'])), sort_keys=True))


if __name__ == '__main__':
    main()
