"""Step-by-step workflow guides shown by `mc guide`. Each step: (role, command or None, explanation)."""

GUIDES: dict[str, dict] = {
    "onboard": {
        "title": "Onboard a crew member",
        "summary": "Director adds them, they fill in their profile, a Director or Lead verifies their skills.",
        "steps": [
            (
                "Director",
                'mc member add sam@artemis.io --name "Sam Rivera" --role CREW --crew',
                "creates the account and crew profile; prompts for an initial password",
            ),
            ("Director", 'mc skill add "Robotics" --category Systems', "only if the skill doesn't exist yet"),
            ("Crew member", "mc profile skill set geology 4", "levels 1-5; recorded as UNVERIFIED"),
            (
                "Crew member",
                'mc profile unavailable add 2027-05-01 2027-05-15 --category LEAVE --note "Wedding"',
                "MEDICAL/OTHER show to Leads only as 'Unavailable'",
            ),
            ("Director or Lead", 'mc crew show "Sam Rivera"', "see what was claimed"),
            (
                "Director or Lead",
                'mc crew verify "Sam Rivera" geology',
                "only verified levels count for matching; nobody verifies their own skills",
            ),
            (
                "Director or Lead",
                'mc crew verify "Sam Rivera" eva --level 2 --cert-expires 2028-12-31',
                "adjust the level and set a certification expiry",
            ),
        ],
    },
    "plan": {
        "title": "Plan and staff a mission",
        "summary": "Lead creates the mission and its slots, runs the matcher, offers positions; crew accept.",
        "steps": [
            (
                "Mission Lead",
                'mc mission create "Shackleton Rim Traverse" --start 2027-03-02 --end 2027-03-20',
                "you become the owner; note the code it prints (e.g. ART-4)",
            ),
            ("Mission Lead", "mc mission slot add ART-4 --role Commander --skill piloting:4", None),
            ("Mission Lead", "mc mission slot add ART-4 --role Geologist --count 2 --skill geology:3", None),
            (
                "Mission Lead",
                'mc mission slot add ART-4 --role "EVA Specialist" --skill eva:3:cert',
                ":cert = a valid certification is required",
            ),
            ("Mission Lead", "mc match ART-4", "best crew for the whole mission, with reasons"),
            (
                "Mission Lead",
                "mc match ART-4 --explain Geologist",
                "score breakdown, alternatives, and why-not for gaps (closest first)",
            ),
            ("Mission Lead", "mc match ART-4 --apply", "offers the suggestions (or --only Commander)"),
            ("Crew member", "mc inbox", "see your offers"),
            ("Crew member", "mc assignment accept <id>", "short ids are fine"),
            ("Crew member", 'mc assignment decline <id> --reason "Family commitment"', "a reason is required"),
        ],
    },
    "approve": {
        "title": "Get a mission approved",
        "summary": "Lead submits once every position is accepted; a different Director approves or rejects.",
        "steps": [
            ("Mission Lead", "mc mission submit ART-4", "needs an accepted crew member in every position"),
            ("Director", "mc inbox", "missions awaiting your approval"),
            ("Director", "mc mission show ART-4", "review what you're approving"),
            ("Director", "mc mission approve ART-4", "never your own submission"),
            ("Director", 'mc mission reject ART-4 --reason "Need a backup EVA"', "returns it to DRAFT"),
            ("Director", "mc org settings --approvals 2", "optional: require two Directors"),
            ("Mission Lead", "mc mission start ART-4", "after approval; later: mc mission complete ART-4"),
            (None, None, "Any edit to dates, slots or crew sends a pending/approved mission back to DRAFT."),
        ],
    },
    "changes": {
        "title": "When plans change",
        "summary": "Withdrawing, releasing, stale offers and the audit trail.",
        "steps": [
            (
                "Crew member",
                'mc assignment withdraw <id> --reason "Knee injury"',
                "before launch; the lead is notified and the mission returns to DRAFT if needed",
            ),
            ("Mission Lead", "mc inbox", "see the withdrawal notification"),
            ("Mission Lead", "mc inbox dismiss <id>", None),
            ("Mission Lead", "mc assignment release <id>", "remove someone (also for emergencies once ACTIVE)"),
            ("Director", "mc org settings --stale-offer-days 5", "when unanswered offers get flagged"),
            ("Mission Lead", "mc mission history ART-4", "full audit trail"),
        ],
    },
}
