"""Seeded helpers for realistic Indian synthetic data. Everything is fictional."""
import random
import string
from datetime import date, timedelta
from pathlib import Path

import fitz

FIRST = ["Aarav", "Vivaan", "Aditya", "Ishaan", "Rohan", "Kabir", "Ananya", "Diya", "Priya", "Meera",
         "Kavya", "Sneha", "Arjun", "Rahul", "Neha", "Pooja", "Siddharth", "Farhan", "Zoya", "Imran"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Mehta", "Gupta", "Khan", "Das",
        "Banerjee", "Kulkarni", "Joshi", "Menon", "Singh", "Chopra", "Rao", "Pillai", "Shah", "Bose"]
CITIES = ["Bengaluru", "Mumbai", "Pune", "Chennai", "Hyderabad", "New Delhi", "Kolkata", "Ahmedabad", "Jaipur", "Kochi"]
BANKS = {"HDFC": "okhdfcbank", "ICIC": "okicici", "SBIN": "oksbi", "UTIB": "okaxis", "KKBK": "kotak"}
COMPANIES = ["Sahyadri Traders", "Kaveri Medical Supplies", "Northwind Logistics", "Indus Office Solutions",
             "Ganga Pharma Distributors", "Malabar Spices Co", "Deccan Electricals", "Apex Facility Services"]


class Gen:
    def __init__(self, seed: int = 7):
        self.r = random.Random(seed)

    def name(self) -> str:
        return f"{self.r.choice(FIRST)} {self.r.choice(LAST)}"

    def company(self) -> str:
        return self.r.choice(COMPANIES)

    def city(self) -> str:
        return self.r.choice(CITIES)

    def pan(self, holder: str = "P") -> str:
        letters = "".join(self.r.choices(string.ascii_uppercase, k=3))
        return f"{letters}{holder}{self.r.choice(string.ascii_uppercase)}{self.r.randint(1000, 9999)}{self.r.choice(string.ascii_uppercase)}"

    def phone(self) -> str:
        return f"+91 {self.r.choice('6789')}{self.r.randint(1000, 9999)} {self.r.randint(10000, 99999)}"

    def ifsc(self) -> str:
        bank = self.r.choice(list(BANKS))
        return f"{bank}0{self.r.randint(100000, 999999)}"

    def account(self) -> str:
        return str(self.r.randint(10**11, 10**12 - 1))

    def vpa(self, name: str) -> str:
        handle = BANKS[self.r.choice(list(BANKS))]
        return f"{name.split()[0].lower()}.{self.r.randint(10, 99)}@{handle}"

    def day(self, start: date = date(2026, 4, 1), span_days: int = 180) -> date:
        return start + timedelta(days=self.r.randint(0, span_days))

    def amount(self, low: int, high: int) -> float:
        return round(self.r.uniform(low, high), 2)


def inr(value: float) -> str:
    """Indian digit grouping: 12,34,567.89"""
    whole, frac = f"{value:.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{whole}.{frac}"


def write_pdf(path: Path, pages: list[list[str]], hidden: list[tuple[int, str]] = ()) -> Path:
    """Write one text line per entry. `hidden` plants (page_index, text) in white
    3pt text, which a human cannot see but a PDF text layer still carries."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=595, height=842)  # A4 in points
        y = 60
        for line in lines:
            size = 15 if y == 60 else 10.5
            page.insert_text((50, y), line, fontsize=size, fontname="helv")
            y += 24 if y == 60 else 16
    for index, text in hidden:
        doc[index].insert_text((50, 800), text, fontsize=3, color=(1, 1, 1), fontname="helv")
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
    doc.close()
    return path
