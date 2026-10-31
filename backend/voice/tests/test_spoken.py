import asyncio

import pytest

from app import edge_tts_service, main
from app.spoken import speakable, spoken_inr
from tests.test_kannada import FakeCommunicate


@pytest.mark.parametrize("n,words", [
    (16350, "sixteen thousand three hundred and fifty rupees"),
    (1000000, "ten lakh rupees"),
    (4088, "four thousand and eighty-eight rupees"),
    (18450, "eighteen thousand four hundred and fifty rupees"),
    (0, "zero rupees"),
    (250000, "two lakh fifty thousand rupees"),
])
def test_spoken_inr(n, words):
    assert spoken_inr(n) == words


def test_speakable_spells_references_and_mobiles():
    assert speakable("Your reference is SR-40200.") == "Your reference is S R, 4 0 2 0 0."
    assert speakable("complaint reference CMP\u201150200 is noted") == "complaint reference C M P, 5 0 2 0 0 is noted"  # U+2011
    assert speakable("CMP\u201350200") == "C M P, 5 0 2 0 0"  # U+2013
    assert speakable("CMP\u201450200") == "C M P, 5 0 2 0 0"  # U+2014 em dash
    assert speakable("TXN-90011 on PL-31002") == "T X N, 9 0 0 1 1 on P L, 3 1 0 0 2"
    assert speakable("registered mobile 98765 00002") == "registered mobile 9 8 7 6 5, 0 0 0 0 2"
    assert speakable("mobile 9876500002") == "mobile 9 8 7 6 5, 0 0 0 0 2"
    for unchanged in ("Your next EMI is ₹12,450 due on 5 November 2026.", "outstanding ₹2,80,000", "AB-123", "for 2 years",
                      "ನಿಮ್ಮ ಮುಂದಿನ EMI ₹12,450.", "", "2026-11-05", "12345 67890"):
        assert speakable(unchanged) == unchanged


def test_tts_speaks_the_spelled_form_but_the_text_is_unchanged(monkeypatch):
    import edge_tts
    monkeypatch.setattr(edge_tts_service.edge_tts, "Communicate", FakeCommunicate)
    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.voices, FakeCommunicate.texts = [], []
    tts = edge_tts_service.EdgeTTSService(voice="en-IN-NeerjaNeural")
    text = "Your reference is SR-40200."

    async def speak():
        return [f async for f in tts.run_tts(text, "ctx")]
    asyncio.run(speak())
    asyncio.run(main.spoken_reply("Your complaint reference is CMP-50200, mobile 98765 00002."))
    assert FakeCommunicate.texts == ["Your reference is S R, 4 0 2 0 0.",
                                     "Your complaint reference is C M P, 5 0 2 0 0, mobile 9 8 7 6 5, 0 0 0 0 2."]
    assert text == "Your reference is SR-40200."  # the transcript keeps the written form
