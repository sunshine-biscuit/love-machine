# quiz_data.py
# Edit/extend questions & category weights here.

QUESTIONS = [
    {
        "prompt": "What does love feel like?",
        "options": [
            ("A warm summer day", {"OPTIMIST": 2, "ROMANTIC": 1}),
            ("Butterflies",        {"ROMANTIC": 2, "CURIOUS": 1}),
            ("Torture",            {"CYNIC": 2, "REALIST": 1}),
        ],
    },
    {
        "prompt": "How risky is love?",
        "options": [
            ("Worth every risk", {"OPTIMIST": 2, "ROMANTIC": 1}),
            ("A calculated leap",{"REALIST": 2, "CURIOUS": 1}),
            ("A trap",           {"CYNIC": 2}),
        ],
    },
    {
        "prompt": "Pick a symbol:",
        "options": [
            ("Sunrise",  {"OPTIMIST": 2}),
            ("Key",      {"CURIOUS": 2, "REALIST": 1}),
            ("Mask",     {"CYNIC": 1, "ROMANTIC": 1}),
        ],
    },
]

CATEGORY_BLURBS = {
    "OPTIMIST": "You lean into hope. You believe love turns gears.",
    "ROMANTIC": "You chase the spark. You like the way it glows.",
    "CURIOUS":  "You examine the edges and step forward anyway.",
    "REALIST":  "You keep your feet on the ground and your heart online.",
    "CYNIC":    "You’ve met love before and kept the receipt.",
}
