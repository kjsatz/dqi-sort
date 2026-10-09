"""Parse the 'Sorted Superconducting' sheet into clean abstracts + session tables."""
import csv, json, re, html
import ftfy

rows = list(csv.reader(open("sorted.csv", encoding="utf-8")))
hdr = next(i for i, r in enumerate(rows) if r[:2] == ["ID", "First Name"])

# Category table (rows 3..21)
cats = {}
for r in rows[3:hdr]:
    if re.match(r"^\d\d\.\d\d\.\d\d$", r[0].strip()):
        cats[r[0].strip()] = r[1].strip()

# Session table lives in columns 14..22 (abbr, n_oral, n_inv, time, title, chair, email, aff, status)
sessions = {}
for r in rows[2:]:
    if len(r) > 18 and r[14].strip() and r[14].strip() not in ("Session\nAbbreviation",) and r[18].strip():
        if r[14].strip().isupper() or re.match(r"^[A-Z0-9]+$", r[14].strip()):
            sessions[r[14].strip()] = {"title": r[18].strip(), "time": r[17].strip(),
                                       "n_oral": r[15], "n_inv": r[16], "chair": r[19].strip()}

def clean(s):
    s = ftfy.fix_text(s or "")
    s = html.unescape(s)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()

talks = []
for r in rows[hdr + 1:]:
    if not r or not r[0].strip().isdigit():
        continue
    r = r + [""] * 12
    talks.append({
        "id": r[0].strip(), "name": clean(f"{r[1]} {r[2]}"), "affiliation": clean(r[3]),
        "category": r[4].strip(), "type": r[5].strip(), "title": clean(r[6]),
        "body": clean(r[7]), "submitter_notes": clean(r[8]),
        "human_session": r[9].strip(), "human_order": r[10].strip(), "sorter_notes": clean(r[11]),
    })

json.dump({"categories": cats, "sessions": sessions}, open("meta.json", "w"), indent=1, ensure_ascii=False)
json.dump(talks, open("talks.json", "w"), indent=1, ensure_ascii=False)

print(len(talks), "talks;", len(sessions), "sessions;", len(cats), "categories")
from collections import Counter
print(Counter(t["type"] for t in talks))
print("missing session:", [t["id"] for t in talks if t["human_session"] not in sessions])
short = [t for t in talks if len(t["body"]) < 200]
print("short bodies:", len(short))
for t in short:
    print(" ", t["id"], t["type"], t["name"], "|", t["title"][:60], "|", t["body"][:90])
