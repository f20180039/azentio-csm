import pytest

from app.spoken import spoken_inr


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
