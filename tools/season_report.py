import os, json, csv, time

DATA_DIR = "data"
STATS = os.path.join(DATA_DIR, "stats_quiz.json")
OUT   = os.path.join(DATA_DIR, f"season_summary_{time.strftime('%Y%m%d_%H%M%S')}.csv")

def load_stats():
    try:
        with open(STATS, "r", encoding="utf-8") as f:
            d = json.load(f)
        total = int(d.get("total", 0))
        cats  = dict(d.get("categories", {}))
        return total, cats
    except Exception:
        return 0, {}

total, cats = load_stats()

print("\n=== LOVE MACHINE — POST‑SEASON QUIZ SUMMARY ===")
print(f"Total completed quizzes (participants): {total}")

if not cats:
    print("\n(No archetype breakdown found yet. Run some sessions, then retry.)\n")
    raise SystemExit

rows = []
for name, n in sorted(cats.items(), key=lambda kv: kv[1], reverse=True):
    pct = (n/total*100) if total else 0
    rows.append((name, n, round(pct)))
    print(f"  - {name}: {n}  ({pct:.0f}%)")

# Save CSV snapshot
os.makedirs(DATA_DIR, exist_ok=True)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["Archetype","Count","Percent"])
    w.writerows(rows)

print(f"\nSaved CSV snapshot: {OUT}\n")
