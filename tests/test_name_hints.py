"""Tests for filename hint classification."""

from midi_parser.name_hints import category_from_name, tokens_from_name


def test_tokens_split():
    assert tokens_from_name("BA_Sub_Bass_01.mid") == ["ba", "sub", "bass", "01"]
    assert tokens_from_name("Kick-Groove.midi") == ["kick", "groove"]


def test_drums_hints():
    assert category_from_name("Kick_Loop.mid") == "Drums"
    assert category_from_name("Funky_Groove.mid") == "Drums"
    assert category_from_name("Beat_04.mid") == "Drums"


def test_bass_hints():
    assert category_from_name("BA_Line.mid") == "Bass"
    assert category_from_name("BA_Deep.mid") == "Bass"
    assert category_from_name("Sub_Bass.mid") == "Bass"
    assert category_from_name("808_Hit.mid") == "Bass"


def test_arp_hints():
    assert category_from_name("ARP_Rising.mid") == "Arp"
    assert category_from_name("Soft_Arpeggio.mid") == "Arp"


def test_chords_hints():
    assert category_from_name("CH_Maj7.mid") == "Chords"
    assert category_from_name("Pad_Warm.mid") == "Chords"
    assert category_from_name("Piano_Comp.mid") == "Chords"


def test_lead_hints():
    assert category_from_name("LD_Hook.mid") == "Lead"
    assert category_from_name("Melody_A.mid") == "Lead"
    assert category_from_name("Keys_Riff.mid") == "Lead"


def test_priority_drums_over_bass():
    # groove is drums; if both present drums wins first in order when drums token hits
    assert category_from_name("Kick_Bass.mid") == "Drums"


def test_no_hint():
    assert category_from_name("Untitled_01.mid") is None
    assert category_from_name("Clip_A.mid") is None
