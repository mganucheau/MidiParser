# MIDI Organizer

Desktop app that scans a folder tree for MIDI files, classifies them into **Drums**, **Bass**, **Lead**, **Chords**, **Arp**, and **Unknown**, then copies them into matching destination subfolders.

Classification uses filename hints first (e.g. `BA`, `ARP`, `Kick`), then MidiBrowser-style note analysis.

The UI follows the same **Cupertino / Midi Toolkit** design system (colors, type, chrome layout) as [MidiBrowser](https://github.com/mganucheau/MidiBrowser).

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

1. **Add** one or more **source** folders, or click **Scan Computer** to search from `/`
2. Browse to a **destination** folder (existing libraries are reused — only missing category folders are created)
3. Click **Scan** (or use Scan Computer / **Resume Scan**) to preview classifications and counts
4. Choose **Copy** or **Move**, then **Organize**

Options:

- **Scan Computer** — whole-disk MIDI discovery from `/` with crash-safe checkpoints (`~/.midi_parser/`)
- **Resume Scan** — continue a halted or crashed whole-computer scan
- **Copy / Move** — leave sources in place, or relocate them into the destination
- **Dry run** — preview without copying or moving
- **Remove duplicates** — skip identical content (SHA-256), including files already in the destination from a prior session
- **Halt** — cancel an in-progress scan or copy/move (checkpointed scans can resume)

While working, a **timer** and live status (phase, path, counts) show that the job is still moving. The results header shows **file count** and **total size**.
