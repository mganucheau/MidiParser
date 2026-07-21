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

### Recommended: collect whole-disk MIDI, then sort

1. Click **Collect MIDI…** and choose a dump folder — copies every `.mid` / `.midi` from `/` into that one folder (**no classification**; walk + copy only)
2. When prompted, add the dump folder as a source (or **Add** it yourself)
3. Browse to an organize **destination** (category library)
4. Click **Scan** to classify, then **Organize**

### Classify a known folder

1. **Add** one or more **source** folders
2. Browse to a **destination** folder (existing libraries are reused — only missing category folders are created)
3. Click **Scan** to preview classifications and counts
4. Choose **Copy** or **Move**, then **Organize**

Options:

- **Collect MIDI…** — fast whole-computer dump into one folder (no parsing). Prefer this over Scan Computer when you only need to gather files first. If the destination runs out of space, collect **pauses** and **resumes automatically** when enough free space is available (use **Halt** to stop).
- **Scan Computer** — whole-disk discovery from `/` **and classify every file** (opens each MIDI; can take many hours). Crash-safe checkpoints in `~/.midi_parser/`.
- **Resume Scan** — continue a halted or crashed whole-computer *classify* scan
- **Copy / Move** — leave sources in place, or relocate them into the destination
- **Dry run** — preview without copying or moving
- **Remove duplicates** — skip identical content (SHA-256), including files already in the destination from a prior session
- **Halt** — cancel an in-progress collect, scan, or copy/move (checkpointed classify scans can resume)

While working, a **timer** and live status (phase, path, counts) show that the job is still moving. The results header shows **file count** and **total size**.
