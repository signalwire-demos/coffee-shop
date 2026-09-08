"""Catalog for the demo. Edit freely: the tools read from here."""

# Water is on the menu so that asking for it resolves EXACTLY instead of
# being fuzzy-matched to a Latte, which is what used to happen. It costs
# nothing; what we ask for instead is a donation to the cat rescue, which is
# what the Cat Paw Cookie is about too.
DONATION_TIERS = [10.0, 20.0, 30.0]
DONATION_SKU = "W1"
DONATION_CAUSE = "cat food and litter for the rescue"


def is_donation(item):
    return bool(item) and item.get("sku") == DONATION_SKU


def donation_choices():
    """The tiers, said the way a person would say them."""
    amounts = ["$%.2f" % t for t in DONATION_TIERS]
    return ", ".join(amounts[:-1]) + " or " + amounts[-1]


def donation_tier(amount):
    """Match a spoken amount to a tier. Returns (tier, error)."""
    if amount is None or str(amount).strip() == "":
        return None, "no amount"
    digits = "".join(ch for ch in str(amount) if ch.isdigit() or ch == ".")
    try:
        want = float(digits)
    except ValueError:
        return None, "not a number"
    for tier in DONATION_TIERS:
        if abs(tier - want) < 0.005:
            return tier, None
    return None, "not a tier"


CATALOG = [
    {
        "sku": "C1",
        "section": "Drinks",
        "name": "Drip Coffee",
        "price": 2.75,
        "description": "House blend, brewed fresh all morning."
    },
    {
        "sku": "C2",
        "section": "Drinks",
        "name": "Latte",
        "price": 4.25,
        "description": "Double espresso, steamed milk, a little art."
    },
    {
        "sku": "C3",
        "section": "Drinks",
        "name": "Cappuccino",
        "price": 4.0,
        "description": "Espresso under a thick cap of foam."
    },
    {
        "sku": "C4",
        "section": "Drinks",
        "name": "Cold Brew",
        "price": 4.5,
        "description": "Steeped eighteen hours, served over ice."
    },
    {
        "sku": "C5",
        "section": "Drinks",
        "name": "Chai Latte",
        "price": 4.25,
        "description": "Spiced black tea with steamed milk."
    },
    {
        "sku": DONATION_SKU,
        "section": "Drinks",
        "name": "Water",
        "price": 0.0,
        # options: [] or it inherits every option in OPTIONS, which made a
        # large water cost $1.10 and a medium one $0.60 -- size surcharges
        # applied to something free. The donation is not a size either: it
        # goes through the donate tool, the only place the tiers are taken.
        "options": [],
        "description": ("Filtered, cold, and free. We ask for a donation for "
                        + DONATION_CAUSE + " instead.")
    },
    {
        "sku": "P1",
        "section": "Pastries",
        "name": "Blueberry Muffin",
        "price": 3.25,
        "description": "Baked this morning, still warm.",
        "options": []
    },
    {
        "sku": "P2",
        "section": "Pastries",
        "name": "Almond Croissant",
        "price": 3.75,
        "description": "Flaky, filled with almond cream.",
        "options": []
    },
    {
        "sku": "P3",
        "section": "Pastries",
        "name": "Cinnamon Roll",
        "price": 4.0,
        "description": "Iced, and big enough to share.",
        "options": []
    },
    {
        "sku": "P4",
        "section": "Pastries",
        "name": "Cat Paw Cookie",
        "price": 2.5,
        "description": "Shortbread, shaped like you would hope.",
        "options": []
    }
]

# Allowed values per option. Anything else is refused with a suggestion,
# Allowed values per option with the surcharge each adds. Accepts
# ['small','large'] or {'small': 0, 'large': 1.10}; both normalise here so
# the board, the handlers and the agent all price identically.
OPTIONS = {
    "size": {
        "small": 0.0,
        "medium": 0.6,
        "large": 1.1
    },
    # The donation tiers, declared here so a tool's enum can be checked
    # against them the same way sizes are. Adding a tier means editing one
    # place, and the enum check catches it if the tool falls behind.
    "amount": {("%d" % t): t for t in DONATION_TIERS},
}

NUMBER_WORDS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "couple": 2,
    "few": 3,
    "dozen": 12
}


def parse_quantity(value, default=1):
    """Accept 2, "2", "two", "a couple" -- callers speak, they do not type."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return max(1, min(99, int(value)))
    text = str(value).strip().lower()
    import re as _re
    digits = _re.search(r'\d+', text)
    if digits:
        return max(1, min(99, int(digits.group())))
    # Longest first: "a couple" must not match the leading "a".
    for word, n in sorted(NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        if _re.search(rf'\b{word}\b', text):
            return n
    return default


def _depluralise(word):
    """Candidate singular forms, best first.

    English cannot be reversed reliably by suffix: 'cookies' is cookie+s but
    'babies' is baby+ies, and both end in -ies. Rather than guess, offer the
    plausible stems and let the catalog decide which one exists.
    """
    out = [word]
    if len(word) > 3:
        if word.endswith("ies"):
            out += [word[:-1], word[:-3] + "y"]        # cookies -> cookie / baby
        elif word.endswith("es"):
            out += [word[:-1], word[:-2]]              # lattes -> latte, boxes -> box
        elif word.endswith("s") and not word.endswith("ss"):
            out.append(word[:-1])                      # muffins -> muffin
    return out


def _normalise(text, singular=True):
    """Speech, not typing: drop articles and quantity words."""
    import re as _re

    q = _re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())
    words = [w for w in q.split() if w]
    drop = set(NUMBER_WORDS) | {"the", "some", "please", "and", "of", "with", "my"}
    words = [w for w in words if w not in drop] or words
    return " ".join(words).strip()


def _forms(text):
    """Every phrasing worth trying for one spoken item name."""
    base = _normalise(text)
    if not base:
        return []
    words = base.split()
    forms = [base]
    for cand in _depluralise(words[-1])[1:]:
        forms.append(" ".join(words[:-1] + [cand]))
    return forms
# Words that describe HOW they want it, not WHAT it is. These do not count
# against a partial match.
_SIZE_WORDS = {"small", "medium", "large", "regular", "big", "extra", "double",
               "single", "hot", "iced", "cold", "please", "one", "two", "cup"}


def find_item(text):
    """Resolve speech to an item. Returns (item, confidence).

    confidence: exact | partial | fuzzy | ambiguous | None. Below partial the
    caller is asked to confirm rather than the agent guessing.
    """
    if not text:
        return None, None
    forms = _forms(text)
    if not forms:
        return None, None

    for q in forms:
        for item in CATALOG:
            name = _normalise(item["name"])
            # Spacing is not reliable from speech: "catpaw cookie" and
            # "cat paw cookie" are the same order. Compare de-spaced too.
            if (q == name or q == item["sku"].lower()
                    or q.replace(" ", "") == name.replace(" ", "")):
                return item, "exact"

    # A written off-menu answer beats a guess. Without this "iced coffee"
    # partial-matched Drip Coffee and "cat food" fuzzy-matched the Cat Paw
    # Cookie, both of which are confidently wrong. Exact matches above still
    # win, so plain "latte" is unaffected.
    if off_menu(text):
        return None, "off_menu"

    q = forms[0]
    contains = [i for i in CATALOG for f in forms
                if f in _normalise(i["name"]) or _normalise(i["name"]) in f]
    contains = list({i["sku"]: i for i in contains}.values())
    if len(contains) == 1:
        # "pumpkin spice latte" contains "latte", and answering it with a
        # plain Latte charges the caller for a drink they did not ask for.
        # If the query carries two or more significant words the item name
        # does not account for, confirm instead of assuming. One extra word
        # is usually a size ("large latte"), which is handled elsewhere.
        name_words = {w for w in _normalise(contains[0]["name"]).split()
                      if len(w) > 2}
        extra = {w for w in q.split() if len(w) > 2} - name_words - _SIZE_WORDS
        if len(extra) >= 2:
            return contains[0], "fuzzy"
        return contains[0], "partial"
    if len(contains) > 1:
        return None, "ambiguous"

    words = {w for w in q.split() if len(w) > 2}
    scored = []
    for item in CATALOG:
        overlap = len(words & {w for w in _normalise(item["name"]).split() if len(w) > 2})
        if overlap:
            scored.append((overlap, item))
    if not scored:
        return None, None
    scored.sort(key=lambda p: -p[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, "ambiguous"
    # A clear multi-word overlap is good enough to act on; a single weak word
    # is worth double-checking.
    import difflib
    best = scored[0][1]
    ratio = difflib.SequenceMatcher(None, q, _normalise(best["name"])).ratio()
    # One clear candidate: add it and say what was assumed, rather than
    # making the caller confirm a thing they already asked for.
    if scored[0][0] >= 2 or ratio >= 0.72:
        return best, "partial"
    return best, "fuzzy"
# Things a coffee shop gets asked for constantly and does not stock. Fuzzy
# string distance answered "water" with "Latte" and "tea" with "Latte", which
# is worse than admitting we do not have it -- so the common asks get a real
# answer written by a person, and the rest get an honest no.
#
# Keys are matched as whole words against what the caller said.
OFF_MENU: dict[str, tuple[str, str]] = {
    # asked for            (what to say we lack,   what to offer instead)
    "espresso":            ("a straight espresso", "Latte"),
    "americano":           ("an americano",        "Drip Coffee"),
    "macchiato":           ("a macchiato",         "Cappuccino"),
    "mocha":               ("a mocha",             "Latte"),
    "flat white":          ("a flat white",        "Latte"),
    "tea":                 ("plain tea",           "Chai Latte"),
    "green tea":           ("green tea",           "Chai Latte"),
    "black tea":           ("black tea",           "Chai Latte"),
    "hot chocolate":       ("hot chocolate",       "Chai Latte"),
    "iced coffee":         ("iced coffee",         "Cold Brew"),
    "iced latte":          ("an iced latte",       "Cold Brew"),
    "frappe":              ("blended drinks",      "Cold Brew"),
    "smoothie":            ("smoothies",           "Cold Brew"),
    "decaf":               ("decaf",               "Chai Latte"),
    "bagel":               ("bagels",              "Almond Croissant"),
    "toast":               ("toast",               "Almond Croissant"),
    "scone":               ("scones",              "Blueberry Muffin"),
    "donut":               ("donuts",              "Cinnamon Roll"),
    "doughnut":            ("doughnuts",           "Cinnamon Roll"),
    "brownie":             ("brownies",            "Cat Paw Cookie"),
    "banana bread":        ("banana bread",        "Blueberry Muffin"),
    "sandwich":            ("sandwiches",          ""),
    "panini":              ("paninis",             ""),
    "soup":                ("soup",                ""),
    "salad":               ("salads",              ""),
    "pizza":               ("pizza",               ""),
    "beer":                ("alcohol",             ""),
    "wine":                ("alcohol",             ""),
    "juice":               ("juice",               ""),
    "soda":                ("soft drinks",         ""),
    "milkshake":           ("milkshakes",          ""),
    "cat food":            ("cat food to sell",    "Water"),
    "litter":              ("litter to sell",      "Water"),
}


def off_menu(text):
    """A written answer for something we do not stock, or None.

    Returns (what_we_lack, suggested_item_or_None). The suggestion is a real
    catalog item, looked up rather than trusted, so a typo here cannot make
    the agent offer something that does not exist.
    """
    q = _normalise(text or "")
    if not q:
        return None
    words = set(q.split())
    # Longest key first, so "iced coffee" beats "coffee" and "green tea"
    # beats "tea".
    for key in sorted(OFF_MENU, key=lambda k: -len(k)):
        k = _normalise(key)
        if k == q or k in q or (" " not in k and k in words):
            lack, suggestion = OFF_MENU[key]
            item = None
            if suggestion:
                item = next((i for i in CATALOG
                             if _normalise(i["name"]) == _normalise(suggestion)),
                            None)
            return lack, item
    return None


def nearest(text, limit=2):
    """Closest catalog items to something we do not stock.

    Reading the whole menu back is a wall of speech. Naming the one thing they
    probably meant is what someone behind the counter would do.
    """
    import difflib

    q = _normalise(text)
    if not q:
        return []
    names = {_normalise(i["name"]): i for i in CATALOG}
    # 0.45 was loose enough to answer "water" with "Latte" and "tea" with
    # "Latte". A suggestion nobody asked for is worse than an honest no.
    close = difflib.get_close_matches(q, list(names), n=limit, cutoff=0.62)
    if close:
        return [names[c] for c in close]
    words = {w for w in q.split() if len(w) > 2}
    scored = []
    for item in CATALOG:
        overlap = len(words & set(_normalise(item["name"]).split()))
        if overlap:
            scored.append((overlap, item))
    scored.sort(key=lambda p: -p[0])
    return [i for _, i in scored[:limit]]
def matches_for(text):
    """Every plausible item, for a disambiguating question."""
    if not text:
        return list(CATALOG)
    q = str(text).strip().lower()
    hits = [i for i in CATALOG if q in i['name'].lower()]
    if hits:
        return hits
    words = {w for w in q.replace('-', ' ').split() if len(w) > 2}
    return [i for i in CATALOG
            if words & {w for w in i["name"].lower().split() if len(w) > 2}
           ] or list(CATALOG)


def options_for(item):
    """Which options apply to this item: omit "options" to inherit all,
    or set [] for none. Without this a muffin gets small/medium/large."""
    declared = item.get('options')
    if declared is None:
        return OPTIONS
    return {k: v for k, v in OPTIONS.items() if k in declared}


def validate_option(name, value, item=None):
    """(ok, canonical_or_None, allowed_names, surcharge)."""
    scope = options_for(item) if item is not None else OPTIONS
    if name not in scope:
        # Present on the menu but not for this item: accept and ignore.
        # Refusing here blocked an order the caller could actually place.
        return True, '', [], 0.0
    allowed = scope.get(name) or {}
    names = list(allowed)
    if not allowed:
        return True, (str(value).strip() if value else ''), [], 0.0
    if not value:
        return True, '', names, 0.0
    v = str(value).strip().lower()
    for a in names:
        if v == a.lower():
            return True, a, names, allowed[a]
    for a in names:
        if v in a.lower() or a.lower() in v:
            return True, a, names, allowed[a]
    return False, None, names, 0.0


def priced_option(item=None):
    """The first option that changes the price for this item, if any."""
    for key, values in (options_for(item) if item is not None else OPTIONS).items():
        if any(v for v in values.values()):
            return key, values
    return None, {}


def price_row(item):
    """[(value, absolute price)] for this item, or [] if it has one price."""
    key, values = priced_option(item)
    if not key:
        return []
    return [(v, round(item['price'] + d, 2)) for v, d in values.items()]


def spoken_prices(item):
    """How the agent should quote this item aloud."""
    row = price_row(item)
    if not row:
        return f"${item['price']:.2f}"
    return ', '.join(f'{v} ${p:.2f}' for v, p in row)
def sellable():
    """Everything you can actually buy. Water is free, so it is not on it."""
    return [i for i in CATALOG if not is_donation(i)]


def menu_summary(max_items=6):
    """Short enough to speak. The full list is in global_data for the model.

    Water is left out: reading a menu that opens with the free thing sounds
    like a shop with nothing to sell.
    """
    names = [i['name'] for i in sellable()]
    if len(names) <= max_items:
        return ', '.join(names[:-1]) + (f', and {names[-1]}' if len(names) > 1 else names[0])
    head = ', '.join(names[:max_items])
    return f'{head}, and {len(names) - max_items} more'


def catalog_lines():
    """The full list for global_data. Water IS here, priced free, because the
    model should be able to answer "do you have water?" from the menu."""
    return [
        (f'{i["name"]} - free. {i["description"]}' if is_donation(i)
         else f'{i["name"]} - ${i["price"]:.2f}. {i["description"]}')
        for i in CATALOG
    ]
