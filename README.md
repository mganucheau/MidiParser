# MIDI Organizer

Desktop app that scans folders for MIDI files, classifies them into **Drums**, **Bass**, **Lead**, **Chords**, **Arp**, and **Unknown**, then places them into matching destination subfolders.

Classification uses filename hints first (e.g. `BA`, `ARP`, `Kick`), then MidiBrowser-style note analysis.

The UI follows a **macOS utility** layout with Cupertino / Midi Toolkit colors.

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

## Workflow

1. Click **+** next to **Sources** and pick one or more folders (× removes a row)
2. Click **+** next to **Destination** and pick one output folder
3. Choose a mode tab:
   - **Scan** — classify MIDI into the results table (no copy)
   - **Move** — copy every `.mid` / `.midi` into the destination (flat folder)
   - **Parse** — classify and move files into category subfolders
   - **All** — scan + parse in one run
4. Optionally enable **Remove duplicates**
5. Click **Start** (use **Stop** to cancel)

The bottom bar shows a **progress** indicator, status, and current path. Use the toolbar control next to **Elapsed** to fold the counts inspector.

While working, the **timer** and live status show that the job is still moving. Results show **file count** and **total size**.
