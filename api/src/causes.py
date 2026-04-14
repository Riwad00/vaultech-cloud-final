"""Cause table — maps each segment to its probable root causes (§1.1)."""

SEGMENT_ORDER = [
    "furnace_to_2nd_strike",
    "2nd_to_3rd_strike",
    "3rd_to_4th_strike",
    "4th_strike_to_aux_press",
    "aux_press_to_bath",
]

CAUSES = {
    "furnace_to_2nd_strike": [
        "Billet pick",
        "gripper close",
        "grip retries",
        "trajectory",
        "permissions",
        "queues",
    ],
    "2nd_to_3rd_strike": [
        "Retraction",
        "gripper",
        "press/PLC handshake",
        "wait points",
        "regrip",
    ],
    "3rd_to_4th_strike": [
        "Retraction",
        "conservative trajectory",
        "synchronization",
        "positioning",
        "confirmations",
    ],
    "4th_strike_to_aux_press": [
        "Pick micro-corrections",
        "transfer",
        "queue at Auxiliary Press entry",
        "interlocks",
    ],
    "aux_press_to_bath": [
        "Retraction",
        "transport",
        "bath queues",
        "permissions",
        "bath deposit",
    ],
}
