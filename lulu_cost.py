#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# written by Claude
"""
What Lulu charges to print one copy of a book.

    print cost = base price + page count x per-page price

Every number below is transcribed from Lulu's published spec sheet:

    https://assets.lulu.com/media/specs/lulu-print-api-spec-sheet.xlsx

That sheet lists a base and per-page price for each of 3277 SKUs. Those
3277 rows are not 3277 independent prices -- they collapse to the tables
here without losing a single value:

  - Cover finish never changes the price. Neither do linen or foil colour.
  - Base price depends only on binding and whether the trim is one of the
    five small ones. Paper and ink do not affect it.
  - Per-page price depends only on interior colour, coating, and that same
    small/large split. Binding does not affect it, and neither does the
    colour of the stock -- cream and white cost the same.

So the sheet is ten base prices, sixteen per-page prices, and the limits.

Lulu reprices annually, so these numbers go stale. `--check` asks their
server whether the sheet has changed since this file was written.

Usage:
    uv run lulu_cost.py --pages 242 --size A5
    uv run lulu_cost.py --pages 242 --size A5 --binding "Hardcover Case Wrap"
    uv run lulu_cost.py --check
"""

import argparse
import sys

SPEC_SHEET_URL = "https://assets.lulu.com/media/specs/lulu-print-api-spec-sheet.xlsx"
# What the server said about the sheet these numbers came from.
SPEC_SHEET_ETAG = '"522a8d984d60a9e8da7c8b9aeb65c4fe"'
SPEC_SHEET_MODIFIED = "Tue, 21 Jul 2026 18:11:15 GMT"

# Trim sizes, in mm, as Lulu lists them. A PDF's mediabox gives you these
# directly, which is why they are the key rather than the names.
TRIM_SIZES = {
    "Pocket Book": (108, 175),
    "Novella": (127, 203),
    "Digest": (140, 216),
    "A5": (148, 210),
    "US Trade": (152, 229),
    "Royal": (156, 234),
    "Executive": (178, 254),
    "Crown Quarto": (189, 246),
    "Small Square": (190, 190),
    "A4": (210, 297),
    "Square": (216, 216),
    "US Letter": (216, 279),
    "Small Landscape": (229, 178),
    "US Letter Landscape": (279, 216),
    "A4 Landscape": (297, 210),
}

# Trim size enters pricing only through this split: these five are cheaper
# to print than the other ten.
SMALL, LARGE = "small", "large"
SMALL_TRIMS = frozenset({"Pocket Book", "Novella", "Digest", "A5", "US Trade"})

# (binding, trim class) -> base price in USD
BASE_PRICE = {
    ("Paperback Perfect Bound", SMALL): 1.99,
    ("Paperback Perfect Bound", LARGE): 2.16,
    ("Paperback Saddle Stitch", SMALL): 3.78,
    ("Paperback Saddle Stitch", LARGE): 4.37,
    ("Paperback Coil Bound", SMALL): 6.36,
    ("Paperback Coil Bound", LARGE): 6.95,
    ("Hardcover Case Wrap", SMALL): 10.68,
    ("Hardcover Case Wrap", LARGE): 10.98,
    ("Hardcover Linen Wrap", SMALL): 14.99,
    ("Hardcover Linen Wrap", LARGE): 15.28,
}
BINDINGS = tuple(dict.fromkeys(b for b, _ in BASE_PRICE))

# Only the coating changes the per-page price: 60# cream and 60# white cost
# the same as each other, everywhere.
UNCOATED, COATED = "uncoated", "coated"
PAPER_TYPES = {
    "60# Uncoated Cream": UNCOATED,
    "60# Uncoated White": UNCOATED,
    "80# Coated White": COATED,
}

# (interior colour, coating, trim class) -> per-page price in USD
PER_PAGE_PRICE = {
    ("Standard Black & White", UNCOATED, SMALL): 0.025,
    ("Standard Black & White", UNCOATED, LARGE): 0.0385,
    ("Standard Black & White", COATED, SMALL): 0.0312,
    ("Standard Black & White", COATED, LARGE): 0.0442,
    ("Premium Black & White", UNCOATED, SMALL): 0.037,
    ("Premium Black & White", UNCOATED, LARGE): 0.0505,
    ("Premium Black & White", COATED, SMALL): 0.0442,
    ("Premium Black & White", COATED, LARGE): 0.0562,
    ("Standard Color", UNCOATED, SMALL): 0.0442,
    ("Standard Color", UNCOATED, LARGE): 0.0562,
    ("Standard Color", COATED, SMALL): 0.0505,
    ("Standard Color", COATED, LARGE): 0.0635,
    ("Premium Color", UNCOATED, SMALL): 0.1259,
    ("Premium Color", UNCOATED, LARGE): 0.2008,
    ("Premium Color", COATED, SMALL): 0.1389,
    ("Premium Color", COATED, LARGE): 0.2148,
}
INTERIOR_COLORS = tuple(dict.fromkeys(c for c, _, _ in PER_PAGE_PRICE))

# Colour is not printed on cream stock; that is the only gap.
NO_COLOR_PAPERS = frozenset({"60# Uncoated Cream"})

COVER_FINISHES = ("Glossy", "Matte")

# binding -> (min pages, max pages)
PAGE_LIMITS = {
    "Paperback Perfect Bound": (32, 800),
    "Paperback Saddle Stitch": (4, 48),
    "Paperback Coil Bound": (2, 470),
    "Hardcover Case Wrap": (24, 800),
    "Hardcover Linen Wrap": (24, 800),
}

# These three explain both of the exceptions below.
LANDSCAPE_TRIMS = frozenset({"Small Landscape", "US Letter Landscape", "A4 Landscape"})

# Perfect bound tops out early in landscape, and saddle stitch is not
# offered there at all. Linen wrap is only made in six trims.
PERFECT_BOUND_LANDSCAPE_MAX = 250
LINEN_WRAP_TRIMS = frozenset({"Digest", "A5", "US Trade", "Royal", "A4", "US Letter"})


def is_available(trim, binding):
    """Whether Lulu makes this binding in this trim."""
    if binding == "Paperback Saddle Stitch":
        return trim not in LANDSCAPE_TRIMS
    if binding == "Hardcover Linen Wrap":
        return trim in LINEN_WRAP_TRIMS
    return True


def trim_class(trim):
    """Which of the two pricing tiers a trim size falls into."""
    return SMALL if trim in SMALL_TRIMS else LARGE


def trim_name(width_mm, height_mm):
    """Name of the Lulu trim size with these dimensions, to the nearest mm."""
    want = (round(width_mm), round(height_mm))
    for name, size in TRIM_SIZES.items():
        if size == want:
            return name
    raise ValueError(
        f"{want[0]}mm x {want[1]}mm is not a Lulu trim size. Available: "
        + ", ".join(f"{n} ({w}x{h}mm)" for n, (w, h) in TRIM_SIZES.items()))


def page_limits(trim, binding):
    """Page counts Lulu will accept for this trim and binding."""
    low, high = PAGE_LIMITS[binding]
    if binding == "Paperback Perfect Bound" and trim in LANDSCAPE_TRIMS:
        high = PERFECT_BOUND_LANDSCAPE_MAX
    return low, high


def print_cost(trim, page_count, color, paper, binding, finish="Glossy"):
    """
    Cost in USD to print one copy.

    Args:
        trim: a name from TRIM_SIZES, or a (width_mm, height_mm) pair
        page_count: interior page count
        color: one of INTERIOR_COLORS, e.g. "Standard Black & White"
        paper: a key from PAPER_TYPES, e.g. "60# Uncoated White"
        binding: one of BINDINGS, e.g. "Paperback Perfect Bound"
        finish: "Glossy" or "Matte" -- validated, but never affects the price

    Raises ValueError for any combination Lulu does not offer.
    """
    if not isinstance(trim, str):
        trim = trim_name(*trim)
    if trim not in TRIM_SIZES:
        raise ValueError(f"{trim!r} is not a trim size. Try: {', '.join(TRIM_SIZES)}")
    if binding not in BINDINGS:
        raise ValueError(f"{binding!r} is not a binding. Try: {', '.join(BINDINGS)}")
    if finish not in COVER_FINISHES:
        raise ValueError(f"{finish!r} is not a cover finish. Try: {', '.join(COVER_FINISHES)}")
    if paper not in PAPER_TYPES:
        raise ValueError(f"{paper!r} is not a paper type. Try: {', '.join(PAPER_TYPES)}")
    if color not in INTERIOR_COLORS:
        raise ValueError(f"{color!r} is not an interior colour. Try: {', '.join(INTERIOR_COLORS)}")
    if "Color" in color and paper in NO_COLOR_PAPERS:
        raise ValueError(f"Lulu does not print {color} on {paper}")
    if not is_available(trim, binding):
        raise ValueError(f"{binding} is not offered in {trim}")

    low, high = page_limits(trim, binding)
    if not low <= page_count <= high:
        raise ValueError(
            f"{binding} in {trim} takes {low}-{high} pages, not {page_count}")

    size = trim_class(trim)
    base = BASE_PRICE[(binding, size)]
    per_page = PER_PAGE_PRICE[(color, PAPER_TYPES[paper], size)]
    return round(base + per_page * page_count, 2)


def check_spec_sheet_current(timeout=10):
    """
    Ask Lulu whether the spec sheet changed since these numbers were taken.

    Returns True if unchanged, False if changed, None if we could not tell
    (no network, or the server stopped sending an ETag).
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(SPEC_SHEET_URL, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            etag = response.headers.get("ETag")
            modified = response.headers.get("Last-Modified")
    except (urllib.error.URLError, OSError) as e:
        print(f"⚠️  Could not reach {SPEC_SHEET_URL}: {e}", file=sys.stderr)
        return None

    if etag is None:
        return None
    if etag == SPEC_SHEET_ETAG:
        return True

    print("⚠️  Lulu's spec sheet has changed, so these prices may be stale.",
          file=sys.stderr)
    print(f"    was {SPEC_SHEET_MODIFIED} / {SPEC_SHEET_ETAG}", file=sys.stderr)
    print(f"    now {modified} / {etag}", file=sys.stderr)
    print(f"    {SPEC_SHEET_URL}", file=sys.stderr)
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="What Lulu charges to print one copy of a book.")
    parser.add_argument("--pages", type=int, help="Interior page count")
    parser.add_argument("--size", default="A5", choices=sorted(TRIM_SIZES),
                        metavar="TRIM", help="Trim size (default: A5)")
    parser.add_argument("--color", default="Standard Black & White",
                        choices=sorted(INTERIOR_COLORS),
                        metavar="COLOR", help="Interior colour")
    parser.add_argument("--paper", default="60# Uncoated White",
                        choices=sorted(PAPER_TYPES),
                        metavar="PAPER", help="Paper type")
    parser.add_argument("--binding", default="Paperback Perfect Bound",
                        choices=sorted(BINDINGS), metavar="BINDING")
    parser.add_argument("--finish", default="Glossy", choices=COVER_FINISHES,
                        help="Cover finish (never affects the price)")
    parser.add_argument("--check", action="store_true",
                        help="Ask Lulu whether the spec sheet has changed")
    args = parser.parse_args()

    if args.check and not check_spec_sheet_current():
        sys.exit(1)
    if args.pages is None:
        if args.check:
            print(f"✓ Prices are current as of {SPEC_SHEET_MODIFIED}")
            sys.exit(0)
        parser.error("--pages is required")

    try:
        cost = print_cost(args.size, args.pages, args.color, args.paper,
                          args.binding, args.finish)
    except ValueError as e:
        sys.exit(f"❌ {e}")

    print(f"{args.size} {args.binding}, {args.pages} pages")
    print(f"{args.color} on {args.paper}, {args.finish} cover")
    print(f"${cost:.2f}")
