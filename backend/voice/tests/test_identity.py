from datetime import date

from app.identity import digit_run, extract_dob, extract_mobile, unexplained_numbers

TODAY = date(2026, 10, 31)


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
    assert extract_dob("twelfth April two thousand", TODAY) == "2000-04-12"
    assert extract_dob("twelfth April two thousand and five", TODAY) == "2005-04-12"
    assert extract_dob("12th April 1990", TODAY) == "1990-04-12"
    assert extract_dob("due on 2026-11-05", TODAY) is None  # not a birth date: this year
    assert extract_dob("SR-40102", TODAY) is None
    assert extract_dob("third November 85", TODAY) is None  # two-digit year: left to the caller to repeat
    assert extract_dob("I want my loan", TODAY) is None
