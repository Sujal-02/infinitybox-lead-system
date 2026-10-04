"""Step 3a: merge name variants of the same organisation (legal suffixes, one-word aliases) into one account."""
import re
from datetime import date
from difflib import SequenceMatcher

from .models import Account

LEGAL = re.compile(r"\b(pvt|private|ltd|limited|llp|inc)\b")


def canon(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return " ".join(LEGAL.sub(" ", n).split())


def resolve(accounts: list[Account], name: str, city: str, segment: str, size_est=None,
            caterer: str = "", domain: str = "", today: date | None = None) -> Account:
    """Find the existing account (same domain, same canonical name, or fuzzy >=0.9) or add one."""
    c = canon(name)
    one_word_of = lambda x, y: len(x.split()) == 1 and len(x) >= 4 and x in y.split()  # "unsw" is a token of "unsw sydney"
    for a in accounts:
        ca = canon(a.name)
        if (domain and a.domain == domain) or ca == c or SequenceMatcher(None, ca, c).ratio() >= 0.9 or one_word_of(ca, c) or one_word_of(c, ca):
            a.size_est = a.size_est or size_est  # fill blanks only
            a.caterer = a.caterer or caterer
            a.domain = a.domain or domain
            return a
    a = Account(id=c.replace(" ", "-"), name=name.strip(), domain=domain, city=city, segment=segment,
                size_est=size_est, caterer=caterer, first_seen=today or date.today())
    accounts.append(a)
    return a
