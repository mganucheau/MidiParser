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

1. Browse to a **source** folder containing MIDI files
2. Browse to a **destination** folder
3. Click **Scan** to preview classifications and counts
4. Click **Organize** to copy files into category subfolders

Options:

- **Dry run** — preview without copying
- **Remove duplicates** — skip files with identical content (SHA-256); first occurrence is kept
