# quiz_data.py
# Edit/extend questions & category weights here.

QUESTIONS = [
    {
        "prompt": "what does love feel like?",
        "options": [
            ("a warm glow",         {"OPTIMIST": 2, "ROMANTIC": 1}),
            ("an overclocked fan",  {"SEEKER": 2, "ROMANTIC": 1}),
            ("an unexpected error", {"CYNIC": 2, "REALIST": 1}),
        ],
    },
    {
        "prompt": "how do you know that it is love?",
        "options": [
            ("the brightness stays at 100%", {"OPTIMIST": 2, "ROMANTIC": 1}),
            ("it is saved to memory",        {"REALIST": 2, "SEEKER": 1}),
            ("i exit the window asap",            {"CYNIC": 2}),
        ],
    },
    {
        "prompt": "if you delete someone from memory... is the love gone?",
        "options": [
            ("never. it is hard coded",           {"ROMANTIC": 1, "OPTIMIST": 1}),  
            ("traces will always remain",        {"SEEKER": 2, "REALIST": 1}),
            ("the name is gone. the ache survives", {"CYNIC": 2, "REALIST": 1}),
        ],
    },
    {
        "prompt": "why does it still hurt even after it is over?",
        "options": [
            ("the memory is golden",  {"OPTIMIST": 1}),            
            ("the memory loops forever", {"SEEKER": 2, "REALIST": 1}),
            ("the memory never stops", {"ROMANTIC": 2}),           
        ],
    },
    {
        "prompt": "how do you know it is real?",
        "options": [
            ("it changes how the world feels", {"OPTIMIST": 2, "ROMANTIC": 1}),
            ("it returns even when uncalled",  {"REALIST": 2, "SEEKER": 1}),
            ("it crashes everything that comes after", {"CYNIC": 2, "ROMANTIC": 1}),
        ],
    },
]


CATEGORY_BLURBS = {
    "OPTIMIST": "You lean into hope. You believe love turns gears.",
    "ROMANTIC": "You chase the spark. You like the way it glows.",
    "SEEKER": 	"Your heart maps constellations to understand the code.",
    "REALIST":  "You keep your feet on the ground and your heart online.",
    "CYNIC":    "You have met love before and kept the receipt.",
}
