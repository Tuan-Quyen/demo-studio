#!/usr/bin/env python3
"""Build the visual key-art style picker page from the key-art catalogue. Stdlib only, Python 3.9+.

The director shows this page before the style question so the user sees what the codes look like.
Data comes only from skills/key-art/references/styles.md (codes, groups, recipe per code) and the
page from skills/key-art/assets/style-picker.html (preview tokens of the 12 core recipes).

  style_picker.py --out PATH [--lang en|vi] [--title TEXT] [--subline TEXT] [--source TEXT]
                  [--recommend "CODES | reason" ...] [--current CODES]
      Writes one self-contained HTML page (no network) to PATH, replacing it when it exists
      (the update of a re-pick). CODES = 1-3 catalogue codes joined by +, commas or spaces, at
      most one per group (styles.md Answer grammar). Prints JSON {out, updated, codes, recipes,
      recommend, current}.

Exit codes: 0 ok, 2 usage, an invalid combo, or an unreadable or inconsistent catalogue/template.
"""
import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
STYLES = os.path.join(PLUGIN, "skills", "key-art", "references", "styles.md")
TEMPLATE = os.path.join(PLUGIN, "skills", "key-art", "assets", "style-picker.html")
PLACEHOLDER = "/*__PICKER_DATA__*/null"
GROUPS = "ABCDEFG"
CODE_RE = re.compile(r"^[A-G]\d+$")


class PickerError(Exception):
    pass


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _section(lines, heading):
    level = len(heading) - len(heading.lstrip("#"))
    out, on = [], False
    for line in lines:
        m = re.match(r"^(#+) ", line)
        if on and m and len(m.group(1)) <= level:
            break
        if on:
            out.append(line)
        elif line.strip().startswith(heading):
            on = True
    return out


def load_catalogue(path=STYLES):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise PickerError("cannot read the catalogue %s: %s" % (path, e))
    recipes = []
    for line in _section(lines, "## Core recipes"):
        if line.startswith("### "):
            break
        if line.startswith("|"):
            first = _cells(line)[0]
            if first != "id" and not set(first) <= set("-: "):
                recipes.append(first)
    if not recipes:
        raise PickerError("no core recipes found in %s" % path)
    groups, cur = [], None
    for line in _section(lines, "## Keyword taxonomy"):
        m = re.match(r"^### ([A-G]) · (.+)$", line)
        if m:
            cur = {"letter": m.group(1), "title": m.group(2).strip(), "codes": [], "unavailable": []}
            groups.append(cur)
            continue
        if not cur or not line.startswith("|"):
            continue
        c = _cells(line)
        if len(c) < 5 or c[0] == "Code" or set(c[0]) <= set("-: "):
            continue
        if c[0] == "–":
            m2 = re.search(r"nearest ([A-G]\d+)", c[4])
            cur["unavailable"].append({"keyword": c[1], "nearest": m2.group(1) if m2 else None})
            continue
        recipe = None
        if "→" in c[4]:
            tail = c[4].split("→", 1)[1]
            hits = [(tail.find(r), r) for r in recipes if re.search(r"(?<![\w-])%s(?![\w-])" % re.escape(r), tail)]
            if hits:
                recipe = min(hits)[1]
        cur["codes"].append({"code": c[0], "keyword": c[1], "meaning": c[2], "v1": c[3], "recipe": recipe})
    if [g["letter"] for g in groups] != list(GROUPS):
        raise PickerError("catalogue groups are not A-G in order")
    return {"recipes": recipes, "groups": groups}


def parse_codes(text, catalogue):
    known = {c["code"]: g["letter"] for g in catalogue["groups"] for c in g["codes"]}
    codes = [t.upper() for t in re.split(r"[+,\s]+", text.strip()) if t]
    if not 1 <= len(codes) <= 3:
        raise PickerError("%r: pick 1-3 codes" % text)
    seen = set()
    for c in codes:
        if not CODE_RE.match(c) or c not in known:
            raise PickerError("%r: %s is not a catalogue code" % (text, c))
        if known[c] in seen:
            raise PickerError("%r: two codes from group %s" % (text, known[c]))
        seen.add(known[c])
    return sorted(codes, key=lambda c: (GROUPS.index(known[c]), int(c[1:])))


def build(args):
    catalogue = load_catalogue()
    try:
        with open(TEMPLATE, encoding="utf-8") as f:
            page = f.read()
    except OSError as e:
        raise PickerError("cannot read the template %s: %s" % (TEMPLATE, e))
    if page.count(PLACEHOLDER) != 1:
        raise PickerError("template has no single %s placeholder" % PLACEHOLDER)
    m = re.search(r"/\*RECIPES-START\*/(.*?)/\*RECIPES-END\*/", page, re.S)
    try:
        tokens = json.loads(m.group(1)) if m else None
    except ValueError:
        tokens = None
    if not tokens or sorted(tokens) != sorted(catalogue["recipes"]):
        raise PickerError("template RECIPES do not match the catalogue's core recipes")
    recommend = []
    for i, item in enumerate(args.recommend or [], 1):
        codes_txt, _, reason = item.partition("|")
        recommend.append({"label": "R%d" % i, "codes": parse_codes(codes_txt, catalogue), "reason": reason.strip()})
    if len(recommend) > 3:
        raise PickerError("at most 3 --recommend combos")
    current = parse_codes(args.current, catalogue) if args.current else []
    data = {"lang": args.lang, "title": args.title, "subline": args.subline, "source": args.source,
            "generated": datetime.date.today().isoformat(), "recipes": catalogue["recipes"],
            "groups": catalogue["groups"], "recommend": recommend, "current": current}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = page.replace(PLACEHOLDER, blob)
    out = os.path.abspath(args.out)
    updated = os.path.exists(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html)
    os.replace(tmp, out)
    print(json.dumps({"out": out, "updated": updated,
                      "codes": sum(len(g["codes"]) for g in catalogue["groups"]),
                      "recipes": len(catalogue["recipes"]),
                      "recommend": [r["codes"] for r in recommend], "current": current}, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="style_picker.py", description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--lang", default="en", choices=["en", "vi"])
    ap.add_argument("--title", default="Your product")
    ap.add_argument("--subline", default="key art preview")
    ap.add_argument("--source", default="source doc")
    ap.add_argument("--recommend", action="append")
    ap.add_argument("--current", default="")
    args = ap.parse_args(argv)
    try:
        return build(args)
    except PickerError as e:
        sys.stderr.write("style_picker: %s\n" % e)
        return 2
    except OSError as e:
        sys.stderr.write("style_picker: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
