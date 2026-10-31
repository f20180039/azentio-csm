from datetime import date

from app.identity import digit_run, extract_dob, extract_mobile, unexplained_numbers
from app.speech import normalise_refs, normalise_spoken_digits

TODAY = date(2026, 10, 31)
SEED_MOBILE = "9876500002"  # CUST-1002 (backend/simulator/data/seed/customers.json)
SEED_LAST_DIGITS = range(1, 9)  # every seeded customer's mobile is 98765 0000N; CUST-1009 is the odd one out
ODD_SEED_MOBILE = "9380939280"
DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def heard(said: str) -> str:
    """The text the brain reads a turn from: the live path's normalise_refs (which expands spoken digits first), then
    SupportBrain.reply's normalise_spoken_digits, in that order."""
    return normalise_spoken_digits(normalise_refs(said))


def mobile_said(said: str) -> str | None:
    return extract_mobile(heard(said))


def test_repeated_digit_forms_give_the_mobile():
    for said in ("nine eight seven six five, zero zero zero zero two", "98765, 00002",
                 "nine eight seven six five double-zero double-zero two",
                 "nine eight seven six five double o double o two", "nine eight seven six five double oh double oh two"):
        assert mobile_said(said) == SEED_MOBILE, said


def test_still_correct_forms_unchanged():
    for said in ("nine eight seven six five four times zero two", "98765 0000 2", "98765 00 00 2",
                 "my number is 9 8 7 6 5 0 0 0 0 2", "9876500002", "+91 98765-00002"):
        assert mobile_said(said) == SEED_MOBILE, said
    assert normalise_refs("SR four double zero two zero zero") == "SR-400200"


def test_every_seed_mobile_is_heard_in_the_forms_callers_use():
    for n in SEED_LAST_DIGITS:
        word, mobile = DIGIT_WORDS[n], f"98765{n:05d}"
        for said in (f"nine eight seven six five zero zero zero zero {word}",
                     f"nine eight seven six five, zero zero zero zero {word}",
                     f"nine eight seven six five zero zero zero zero, {word}",
                     f"nine eight seven six five, zero zero zero zero, {word}",
                     f"nine eight seven six five, four zeros, {word}",
                     f"nine eight seven six five four times zero {word}",
                     f"nine eight seven six five double zero double zero {word}",
                     f"nine eight seven six five double oh double oh {word}",
                     f"98765 0000{n}", f"98765, 0000{n}", f"98765 00 00 {n}", f"98765-0000{n}"):
            assert mobile_said(said) == mobile, said
    assert mobile_said("nine three eight zero nine three nine two eight zero") == ODD_SEED_MOBILE


def test_an_over_long_number_is_not_cut():
    said = "98765 double zero triple zero two"
    assert mobile_said(said) is None
    assert len(digit_run(heard(said))) == 11
    assert mobile_said("my account number is 1234567890123456") is None


def test_a_collapsed_repeat_is_a_short_attempt():
    # Whisper sometimes writes "zero zero zero zero" as "zero zero": the digits are gone, so the number is re-asked with its count
    said = "nine eight seven six five zero zero two"
    assert mobile_said(said) is None
    assert digit_run(heard(said)) == "98765002"


def test_commas_do_not_merge_unrelated_numbers():
    assert mobile_said("I paid 500, 2 times") is None
    assert mobile_said("CMP-98765, 00002") is None  # a reference's digits never start a number
    text = heard("SR-40102, 98765 00002")
    assert extract_mobile(text) == SEED_MOBILE and "SR-40102" in text


def test_a_date_after_a_short_number_keeps_its_day():
    # a pause then "5 December 1995": the 5 is the day, never the short number's missing digit (fix round 1, item 1)
    for said in ("98765 0006, 5 December 1995", "987650006, 5 December 1995",
                 "nine eight seven six five zero zero zero six, five december nineteen ninety five"):
        text = heard(said)
        assert extract_mobile(text) is None and digit_run(text) == "987650006" and extract_dob(text, TODAY) == "1995-12-05", said
    text = heard("98765 0002, 3 November 1985")
    assert extract_mobile(text) is None and digit_run(text) == "987650002" and extract_dob(text, TODAY) == "1985-11-03"
    text = heard("98765 0006, 5/12/1995")
    assert extract_mobile(text) is None and digit_run(text) == "987650006" and extract_dob(text, TODAY) == "1995-12-05"
    # a date said first stays a date and lends no digit; what follows is read on its own, and '<nine digits>, <one>' is the
    # seed form "nine eight seven six five zero zero zero zero, N" (brief addendum), so it is one number
    text = heard("1995-12-05, 98765 0006, 5")
    assert extract_dob(text, TODAY) == "1995-12-05" and extract_mobile(text) == "9876500065"


def test_leftover_digits_the_code_read_do_not_open_the_model():
    assert not unexplained_numbers("9282, 766, 0006")  # read, just not a mobile: the model may not send its own guess
    assert not unexplained_numbers("98765 0006, 5 December 1995")
    assert unexplained_numbers("ನನ್ನ ಸಂಖ್ಯೆ ಒಂಬತ್ತು ಎಂಟು") and unexplained_numbers("1 Jan 90")


def test_oh_outside_a_number_stays_a_word():
    text = heard("oh, okay, my number is nine eight seven six five double oh double oh two")
    assert "oh, okay" in text and extract_mobile(text) == SEED_MOBILE


def test_extract_mobile_forms():
    for said in ("9876500002", "98765 00002", "+91 98765-00002", "+919876500002", "919876500002", "09876500002",
                 "my number is 98765 00002 and my date of birth is 3rd November 1985",
                 "nine eight seven six five zero zero zero zero two", "nine eight seven six five oh oh oh oh two",
                 "nine eight seven six five four times zero two", "98765 triple zero 02",
                 "earlier I gave 9380939280 but the right one is 98765 00002"):
        assert extract_mobile(said) == "9876500002", said
    assert extract_mobile("9380939280 98765 00002") == "9876500002"  # a correction said straight after: the last one
    assert extract_mobile("9876500002 3 November 1985") == "9876500002"  # the day did not join the number
    assert extract_mobile("3 November 1985 98765 00002") == "9876500002"  # nor did the year
    assert extract_mobile("98765 0002 3 November 1985") is None  # a short number stays short: the day is not borrowed
    assert extract_mobile("my account 123456789012 please") is None
    assert extract_mobile("I want my loan") is None
    assert extract_mobile("SR-40102 please") is None
    assert extract_mobile("born 1985-11-03") is None


def test_digit_run_finds_a_short_number():
    assert digit_run("98765 0002") == "987650002"
    assert digit_run("98765 0002, born 3 November 1985") == "987650002"
    assert digit_run("98765 0002 3 November 1985") == "987650002"
    assert digit_run("+91 98765 0002") == "987650002"
    assert digit_run("I want my loan") is None


def test_unexplained_numbers_are_only_those_the_code_did_not_read():
    for said in ("My number is 98765 00002", "98765 00002, 3rd November 1985", "98765 0002, born 3 November 1985",
                 "3 November 1985", "I want my loan", "due on 2026-11-05",
                 "what is the status of my loan PL-31002", "SR-40102 please", "I will pay 5 to 6 lakh", "Question 0",
                 "the EMI of 12,450 rupees and the balance of 1,00,000", "Rs 9800 is due; TXN-88213 failed; CUST-1002 CMP-50011"):
        assert not unexplained_numbers(said), said
    for said in ("born third November 85", "9876500002, 3 Nov 85", "1 Jan 90", "ನನ್ನ ಸಂಖ್ಯೆ ಒಂಬತ್ತು ಎಂಟು", "मेरा नंबर नौ आठ सात"):
        assert unexplained_numbers(said), said


def test_extract_dob_forms():
    for said in ("1985-11-03", "03/11/1985", "03-11-1985", "3/11/1985", "3 November 1985", "3rd November 1985",
                 "3rd of November 1985", "November 3, 1985", "Nov 3 1985", "third November nineteen eighty five",
                 "third of November nineteen eighty-five", "the third of November, nineteen eighty five",
                 "my date of birth is 3rd November 1985 and my number is 98765 00002"):
        assert extract_dob(said, TODAY) == "1985-11-03", said
    assert extract_dob("the ninth of March nineteen eighty-two", TODAY) == "1982-03-09"
    assert extract_dob("November third nineteen eighty five", TODAY) == "1985-11-03"  # month first, in words
    assert extract_dob("five December nineteen ninety five", TODAY) == "1995-12-05"  # the day as a cardinal word
    assert extract_dob("twenty five of December 1995", TODAY) == "1995-12-25"
    assert extract_dob("twelfth April two thousand", TODAY) == "2000-04-12"
    assert extract_dob("twelfth April two thousand and five", TODAY) == "2005-04-12"
    assert extract_dob("12th April 1990", TODAY) == "1990-04-12"
    assert extract_dob("due on 2026-11-05", TODAY) is None  # not a birth date: this year
    assert extract_dob("SR-40102", TODAY) is None
    assert extract_dob("third November 85", TODAY) is None  # two-digit year: left to the caller to repeat
    assert extract_dob("I want my loan", TODAY) is None
