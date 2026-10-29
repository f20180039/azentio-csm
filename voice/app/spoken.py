_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _below_100(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def spoken_inr(n: int) -> str:
    if n == 0:
        return "zero rupees"
    parts = []
    crore, lakh, thousand = n // 10_000_000, (n // 100_000) % 100, (n // 1_000) % 100
    if crore:
        parts.append(f"{spoken_inr(crore)[:-len(' rupees')]} crore")
    if lakh:
        parts.append(f"{_below_100(lakh)} lakh")
    if thousand:
        parts.append(f"{_below_100(thousand)} thousand")
    if (n // 100) % 10:
        parts.append(f"{_ONES[(n // 100) % 10]} hundred")
    if n % 100:
        parts.append(("and " if parts else "") + _below_100(n % 100))
    return " ".join(parts) + " rupees"
