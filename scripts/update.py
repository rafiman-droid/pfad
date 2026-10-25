#!/usr/bin/env python3
"""
מושך את מחיר ה-PFAD היומי מ-agropost ומוסיף אותו ל-data.csv.

מקור: https://agropost.wordpress.com/
נלקחת השורה "Palm Fatty Acid Distillates" בטבלת
PHYSICAL MARKET PRICES FOR REFINED OILS & FATS, ערך Selling:
העמודה הראשונה = החודש הקרוב, השנייה = החודש העוקב.

מעדיף את דוח הסגירה (at Closing). אם ליום מסוים פורסם רק דוח אמצע היום
(at Midday) הוא נלקח כזמני, ובריצה הבאה מוחלף במחיר הסגירה כשהוא מתפרסם.
ללא תלויות חיצוניות - ספריית התקן של פייתון בלבד.
"""

import html
import os
import re
import sys
import time
import urllib.request

HOME = "https://agropost.wordpress.com/"
CSV = os.path.join(os.path.dirname(__file__), "..", "data.csv")
UA = "Mozilla/5.0 (compatible; pfad-tracker/1.0; +https://github.com/)"

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace(" ", " ")
    return " ".join(s.split())


def parse_title_date(title):
    """'8 Sep 2026 - Palm Oil Prices at Closing' -> ('2026-09-08', 'closing')"""
    m = re.match(r"\s*(\d{1,2})\s*([A-Za-z]{3,9})\.?\s*(\d{4})", title)
    if not m:
        return None, None
    mon = MONTHS.get(m.group(2)[:3].lower())
    if not mon:
        return None, None
    iso = "%s-%02d-%02d" % (m.group(3), mon, int(m.group(1)))
    kind = "closing" if re.search(r"closing", title, re.I) else "midday"
    return iso, kind


def list_posts(limit=30):
    """[(iso_date, kind, url)] מהעמוד הראשי, החדש ביותר קודם."""
    page = fetch(HOME + "?nc=" + str(int(os.times()[4] * 1000)))
    out = []
    for m in re.finditer(
        r'<h2[^>]*class="[^"]*entry-title[^"]*"[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        page, re.S | re.I,
    ):
        url, title = m.group(1), strip_tags(m.group(2))
        if not re.search(r"Palm Oil (Prices|Market) at (Closing|Midday)", title, re.I):
            continue
        iso, kind = parse_title_date(title)
        if iso:
            out.append((iso, kind, url))
        if len(out) >= limit:
            break
    return out


def pfad_from_post(url):
    """(near_month, next_month) כמחרוזות; next_month יכול להיות ''. None אם אין שורה."""
    page = fetch(url)
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        if not re.search(r"fatty\s*acid", tr, re.I):
            continue
        cells = [strip_tags(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        try:
            i = next(k for k, c in enumerate(cells) if c.strip().lower() == "selling")
        except StopIteration:
            continue
        nums = []
        for c in cells[i + 1:]:
            c = c.replace(",", "").strip()
            nums.append(c if re.fullmatch(r"\d+(\.\d+)?", c) else "")
        if not nums or not nums[0]:
            return None
        return nums[0], (nums[1] if len(nums) > 1 else "")
    return None


def read_csv():
    rows = {}
    if os.path.exists(CSV):
        for line in open(CSV, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            p = line.split(",")
            if len(p) >= 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p[0]):
                rows[p[0]] = (p[1], p[2] if len(p) > 2 else "")
    return rows


def write_csv(rows):
    with open(CSV, "w", encoding="utf-8") as f:
        for d in sorted(rows):
            m1, m2 = rows[d]
            f.write("%s,%s,%s\n" % (d, m1, m2))


def main():
    rows = read_csv()
    if not rows:
        print("data.csv ריק או חסר - עוצר כדי לא לדרוס היסטוריה", file=sys.stderr)
        return 1
    last = max(rows)
    print("התאריך האחרון בקובץ:", last)

    posts = list_posts()
    if not posts:
        print("לא נמצאו פוסטים בעמוד הראשי - ייתכן שמבנה האתר השתנה", file=sys.stderr)
        return 1

    # התאריך האחרון נבדק גם הוא, כדי להחליף מחיר אמצע-יום במחיר סגירה
    best = {}  # iso -> (kind, url); closing גובר על midday
    for iso, kind, url in posts:
        if iso < last:
            continue
        if iso in best and best[iso][0] == "closing":
            continue
        if iso not in best or kind == "closing":
            best[iso] = (kind, url)

    changed = []
    for iso in sorted(best):
        kind, url = best[iso]
        if iso == last and kind != "closing":
            continue  # אין מה לשפר
        vals = pfad_from_post(url)
        if not vals:
            print("אין שורת PFAD ב-%s (%s)" % (iso, url))
            continue
        if rows.get(iso) == vals:
            continue
        action = "עודכן" if iso in rows else "נוסף"
        rows[iso] = vals
        changed.append("%s %s: %s / %s" % (action, iso, vals[0], vals[1] or "-"))

    if not changed:
        print("אין ציטוט חדש")
        return 0

    write_csv(rows)
    for c in changed:
        print(c)
    summary = " · ".join(changed)
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write("summary=%s\n" % summary)
            f.write("changed=yes\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
