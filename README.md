# MIDI Organizer

Desktop app that scans a folder tree for MIDI files, classifies them into **Drums**, **Bass**, **Lead**, **Chords**, **Arp**, and **Unknown**, then copies them into matching destination subfolders.

Classification uses filename hints first (e.g. `BA`, `ARP`, `Kick`), then MidiBrowser-style note analysis.

## Requirements

- Python 3.11+ with Tk support (on Homebrew: `brew install python-tk@3.14`)

## Install

```bash
cd MidiParser
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Launch

```bash
midi-organize
# or
python -m midi_parser
```

1. **Add** one or more **source** folders (multi-select via Add)
2. Browse to a **destination** folder (existing libraries are reused — only missing category folders are created)
3. Click **Scan** to preview classifications and counts
4. Choose **Copy** or **Move**, then **Organize**

Options:

- **Copy / Move** — leave sources in place, or relocate them into the destination
- **Dry run** — preview without copying or moving
- **Remove duplicates** — skip identical content (SHA-256), including files already in the destination from a prior session
- **Halt** — cancel an in-progress scan or copy/move

While working, the status line shows the phase (discover / classify / transfer), counts, and the current path so you can tell the job is still moving. Large roots (e.g. `/`) spend a long time in **discover** before the determinate progress bar advances.
