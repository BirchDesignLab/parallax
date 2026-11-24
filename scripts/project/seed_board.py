"""Set up the Parallax project board on GitHub and fill it with the known work.

    python scripts/project/seed_board.py            (apply)
    python scripts/project/seed_board.py --dry-run  (print what would be done)

One-off, run 2026-11-24 against https://github.com/users/BirchDesignLab/projects/8, kept
here so the board can be rebuilt or extended the same way. It needs the `gh` CLI signed in
with the `project` scope. It is safe to run again: a field or an item that already exists
(matched by name or title) is left as it is.

What it does:
1. writes the board's short description and its README;
2. gives Status five options and adds four fields: Area, Kind, Horizon, Priority;
3. adds the merged pull requests as finished items;
4. opens an issue in the repository for each piece of open work and adds it to the board
   with its fields set (developer direction 2026-11-24: issues, not drafts). Every one comes from the
   design document's "After v0" list, its "Verified and not yet verified" section, or what
   the three recorded live runs turned up. Nothing here is invented roadmap.
"""
import json
import subprocess
import sys

OWNER = "BirchDesignLab"
REPO = "parallax"
NUMBER = 8
DOCS = f"https://github.com/{OWNER}/{REPO}/blob/main"
SPEC = f"{DOCS}/docs/superpowers/specs/2026-11-16-parallax-design.md"
DRY = "--dry-run" in sys.argv

SHORT = "Two models on every change: one builds, the other checks blind. What has shipped, what is next, and what is not verified yet."

README = f"""## Parallax

A Python conductor that pairs Claude Code and Codex on one task. One builds the change and a few deliberately broken copies of it. The other writes the checks from a frozen contract, without seeing the code. Where they disagree, a human gets one card. The change lands on `main` with a receipt.

Code and docs: [{OWNER}/{REPO}](https://github.com/{OWNER}/{REPO})

### How to read this board

| Field | Meaning |
|---|---|
| **Status** | Backlog, Ready, In progress, On hold, Done |
| **Horizon** | Now (v0 follow-ups), Next (before anything new), Later (the design document's "After v0" list) |
| **Kind** | Bug, Design question, Verification, Feature, Chore |
| **Area** | The part of the system the item touches |
| **Priority** | P1 changes what the project can claim; P2 improves it; P3 can wait |

### Ground rules

- Every item traces to the code, the [design document]({SPEC}) or a recorded run. Nothing here is a promise.
- "Verification" items are things that work on scripted stub seats and have not been run with real models. They stay open until a dated real run is recorded in the [field notes]({DOCS}/docs/field-notes.md).
- v0 runs on one Windows 11 machine. That is the only setup anything here is tested on.
"""

STATUS = [
    ("Backlog", "GRAY", "Known, not scheduled"),
    ("Ready", "BLUE", "Understood well enough to start"),
    ("In progress", "YELLOW", "Being worked on now"),
    ("On hold", "ORANGE", "Waiting on something outside this item"),
    ("Done", "GREEN", "Merged to main or recorded"),
]
FIELDS = {
    "Area": [
        ("Conductor", "BLUE", "The plain-Python process that runs a task"),
        ("Disputes and rulings", "PURPLE", "Readings, settlement, cards, precedents"),
        ("Seats", "ORANGE", "The Claude Code and Codex CLIs as driven by the conductor"),
        ("Receipts and ledger", "GREEN", "What a landing records, including token counts"),
        ("Tests and CI", "GRAY", "The test suite and the GitHub workflow"),
        ("Docs and site", "PINK", "README, docs, figures, the project page"),
    ],
    "Kind": [
        ("Bug", "RED", "The code does something it should not"),
        ("Design question", "PURPLE", "Needs a decision before any plan"),
        ("Verification", "YELLOW", "Works on stub seats, not yet run with real models"),
        ("Feature", "BLUE", "New behavior"),
        ("Chore", "GRAY", "Upkeep"),
    ],
    "Horizon": [
        ("Now", "GREEN", "Follow-ups to v0"),
        ("Next", "YELLOW", "Before anything new is built"),
        ("Later", "GRAY", "The design document's After v0 list"),
    ],
    "Priority": [
        ("P1", "RED", "Changes what the project can claim"),
        ("P2", "ORANGE", "Improves it"),
        ("P3", "GRAY", "Can wait"),
    ],
}

# The repository label each kind of item gets, where the label exists.
LABELS = {"Bug": ["bug"], "Feature": ["enhancement"], "Design question": ["question"]}

# Merged pull requests, shown as finished work: (number, area, kind).
PULLS = [
    (1, "Docs and site", "Chore"),
    (2, "Docs and site", "Chore"),
    (3, "Tests and CI", "Bug"),
    (4, "Tests and CI", "Chore"),
    (5, "Tests and CI", "Chore"),
]


def draft(title, status, horizon, kind, area, priority, why, done_when, source):
    body = f"**Why**\n\n{why}\n\n**Done when**\n\n{done_when}\n\n**Source**\n\n{source}\n"
    return {"title": title, "body": body,
            "fields": {"Status": status, "Horizon": horizon, "Kind": kind, "Area": area, "Priority": priority}}


AFTER_V0 = f'[Design document, "After v0"]({SPEC}#after-v0)'
NOT_VERIFIED = f'[Design document, "Verified and not yet verified"]({SPEC}#verified-and-not-yet-verified)'
FIELD_NOTES = f"[Field notes]({DOCS}/docs/field-notes.md)"

DRAFTS = [
    draft("Token totals are probably overcounted on resumed seat sessions",
          "Ready", "Now", "Bug", "Receipts and ledger", "P1",
          "A call that resumes a seat session appears to report the session's cumulative usage, and the conductor sums per call. "
          "If so, the token figures recorded for the real runs are too high, and so is any cost drawn from them.",
          "- `turn.completed` on a resumed Codex thread and the Claude `result` usage on `--resume` are each checked against a fresh call.\n"
          "- The accounting records the delta, or the docs state plainly what the number is.\n"
          "- The recorded figures are corrected or marked.",
          "Suspected while reviewing the live runs of 2026-11-23. Not confirmed, and not yet written up in the published notes."),
    draft("A narrow refusal costs the human a whole card",
          "Backlog", "Now", "Design question", "Disputes and rulings", "P1",
          "In the third real run the challenger refused the builder's proposal over one dropped guarantee. "
          "The card that reached the human asked for a full interface and policy covering ten provisions. "
          "One repair exchange between the seats before a refusal card might settle it without the human.",
          "- A decision is recorded: keep the refusal card as it is, or give the seats one repair exchange first.\n"
          "- If the design changes, the design document and `docs/rulings.md` change with it.",
          f"Run 3, 2026-11-23. {FIELD_NOTES}"),
    draft("Neither seat asked about a task written to contradict itself",
          "Backlog", "Next", "Design question", "Disputes and rulings", "P2",
          "Run 3 used a task that contradicts itself. Both seats silently picked the same reading, so nothing reached the human. "
          "Agreement between the seats is treated as evidence, and here it hid a defect in the task.",
          "- A decision on whether a seat should be able to flag a task as contradictory, and where that would surface.",
          f"Run 3, 2026-11-23. {FIELD_NOTES}"),
    draft("Run an A/B card with real seats",
          "Backlog", "Next", "Verification", "Disputes and rulings", "P1",
          "An A/B card has only been produced by scripted stub seats in the test suite. No real run has reached one.",
          "- A dated real run that produces an A/B card, is ruled, and lands, recorded in the field notes.",
          NOT_VERIFIED),
    draft("Run the direct settlement path with real seats",
          "Backlog", "Next", "Verification", "Disputes and rulings", "P1",
          "The direct path (no conflict flag and at most one objection, settled without the extra exchange) runs in the stub demo and the tests. It has not been seen with real models.",
          "- A dated real run that settles by the direct path, recorded in the field notes.",
          NOT_VERIFIED),
    draft("Kill a real run mid-step and resume it",
          "Backlog", "Next", "Verification", "Conductor", "P1",
          "Every step records its completion in the journal so a resumed run skips what is done, and an unfinished attempt is discarded and rerun. "
          "That is tested with stub seats. It has not been tested by killing a run that is driving real CLIs.",
          "- A real run killed during a seat call resumes to the same contract and lands once, recorded in the field notes.",
          NOT_VERIFIED),
    draft("Project page in the Birch Design Lab",
          "On hold", "Next", "Feature", "Docs and site", "P2",
          "A single interactive page that shows what the README cannot: the two sight lines, the dispute card you can rule on, the receipt. "
          "The design is settled and a working page exists locally. It waits on other work in the Lab.",
          "- The page is live at one URL, with self-hosted fonts and a link preview image.\n"
          "- Checked in Chrome, Safari and Firefox, on a phone, and with reduced motion.\n"
          "- The repository's About link and the README point at it.",
          "Design exploration of 2026-11-24. The figures in the README already use its visual language."),
    draft("Check the README figures on GitHub's light theme, Safari and a phone",
          "Ready", "Now", "Verification", "Docs and site", "P3",
          "The redrawn figures were checked in Chrome on GitHub's dark theme and locally at phone width. "
          "They use filters and blend modes that other browsers can render differently.",
          "- Each of the seven figures looked at on the light theme, in Safari and Firefox, and on a real phone, with any fix made in `scripts/docs/build_assets.py`.",
          f"[Pull request 2](https://github.com/{OWNER}/{REPO}/pull/2), \"Not verified\"."),
    draft("Make the slowest conductor tests faster",
          "Backlog", "Next", "Chore", "Tests and CI", "P3",
          "The suite is about 33 minutes of test time; CI runs it in four shards of about 9 minutes. "
          "Twelve conductor test modules hold about 94 percent of that time, and the slowest single test takes over a minute.",
          "- The slowest tests are profiled and the common cost (most likely repeated repository setup) is cut.\n"
          "- Shard timings in `scripts/ci/run_tests.py` are refreshed.",
          f"Timings from CI run 45432827961, 2026-11-24. [Pull request 5](https://github.com/{OWNER}/{REPO}/pull/5)."),
    draft("Rerun the seat probes after each CLI update",
          "Backlog", "Now", "Chore", "Seats", "P2",
          "The conductor depends on how the two CLIs behave: sandboxing, event streams, session resume. An update to either can change that without notice.",
          "- After either CLI updates: `python scripts/probes/seat_smoke.py` exits zero and `python scripts/probes/job_object_seats.py` passes.\n"
          "- Recurring: this item stays open.",
          f"[Project rules]({DOCS}/CLAUDE.md), \"Working rules\"."),
    draft("Two or more tasks in flight",
          "Backlog", "Later", "Feature", "Conductor", "P2",
          "v0 runs one task at a time per project. Running several needs crossed roles, path leases, and separate ports, temp directories and test databases per task.",
          "- A design for leases and isolation, then two tasks landing from one project without touching each other's files.",
          AFTER_V0),
    draft("Experiments as a dispute step",
          "Backlog", "Later", "Feature", "Disputes and rulings", "P3",
          "Today a dispute needs a witness: one concrete call on which the answers differ. Some disagreements are better settled by running something than by a human ruling.",
          "- A design for when a dispute may be settled by an experiment, and what counts as its evidence.",
          AFTER_V0),
    draft("Assumptions as first-class claims",
          "Backlog", "Later", "Feature", "Disputes and rulings", "P2",
          "A ruling rests on assumptions. When one flips, the probes should be amended, every crossing rerun, and whatever fails reopened.",
          "- An assumption can be recorded, flipped, and the affected tasks found and rerun.",
          AFTER_V0),
    draft("A scoreboard of which seat should build what",
          "Backlog", "Later", "Feature", "Receipts and ledger", "P3",
          "Roles alternate by task today. The ledger already records who built, who challenged and the verdict, which is the data a scoreboard would need.",
          "- A report from the ledger, and a decision on whether it should influence who builds.",
          AFTER_V0),
    draft("A live view of a running task",
          "Backlog", "Later", "Feature", "Conductor", "P3",
          "The conductor prints progress lines and exits. There is no view of a task while its seats are working.",
          "- A read-only view of the current step, both seats' state, and open cards.",
          AFTER_V0),
    draft("More than two seats",
          "Backlog", "Later", "Feature", "Seats", "P3",
          "v0 pairs exactly two CLIs. The design names builder and challenger; a third seat would need a role and a way to keep it blind.",
          "- A design for what a third seat does and how the blind holds with it.",
          AFTER_V0),
]


def gql(query: str, **variables):
    if DRY and "mutation" in query:
        print("  would run:", query.split("(")[0].strip(), json.dumps(variables)[:110])
        return {}
    done = subprocess.run(["gh", "api", "graphql", "--input", "-"], capture_output=True, text=True, encoding="utf-8",
                          input=json.dumps({"query": query, "variables": variables}))
    reply = json.loads(done.stdout) if done.stdout.strip() else {}
    if done.returncode != 0 or reply.get("errors"):
        raise Refused(str([e.get("message") for e in reply.get("errors") or []] or done.stderr.strip()))
    return reply["data"]


class Refused(Exception):
    """GitHub would not run a query, most often because the account may not change that part of the board."""


def attempt(what: str, query: str, **variables):
    """Run a change the account may not be allowed to make. Says so and carries on when it is refused."""
    try:
        return gql(query, **variables)
    except Refused as refused:
        print(f"  refused: {what}: {refused}")
        return {}


def options(rows):
    return [{"name": name, "color": color, "description": text} for name, color, text in rows]


def main() -> None:
    project = gql("""query($owner: String!, $number: Int!) { user(login: $owner) { projectV2(number: $number) { id
        fields(first: 50) { nodes { ... on ProjectV2FieldCommon { id name } ... on ProjectV2SingleSelectField { options { id name } } } }
        items(first: 100) { nodes { id content { ... on DraftIssue { title } ... on PullRequest { number } ... on Issue { title } } } } } } }""",
                  owner=OWNER, number=NUMBER)["user"]["projectV2"]
    pid = project["id"]

    print("board text")
    attempt("board description and README", "mutation($id: ID!, $short: String!, $readme: String!) { updateProjectV2(input: {projectId: $id, shortDescription: $short, readme: $readme}) { projectV2 { id } } }",
        id=pid, short=SHORT, readme=README)

    fields = {node["name"]: node for node in project["fields"]["nodes"] if node}
    print("fields")
    wanted = [name for name, _, _ in STATUS]
    if [o["name"] for o in fields["Status"].get("options", [])] != wanted:
        reply = attempt("Status options", "mutation($id: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]) { updateProjectV2Field(input: {fieldId: $id, singleSelectOptions: $options}) "
                    "{ projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } } } }", id=fields["Status"]["id"], options=options(STATUS))
        if reply:
            fields["Status"] = reply["updateProjectV2Field"]["projectV2Field"]
    for name, rows in FIELDS.items():
        if name in fields:
            continue
        reply = attempt(f"field {name}", "mutation($id: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]) { createProjectV2Field(input: {projectId: $id, dataType: SINGLE_SELECT, name: $name, singleSelectOptions: $options}) "
                    "{ projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } } } }", id=pid, name=name, options=options(rows))
        if reply:
            fields[name] = reply["createProjectV2Field"]["projectV2Field"]

    missing: set[str] = set()

    def set_fields(item: str, values: dict) -> None:
        for name, value in values.items():
            field = fields.get(name)
            option = next((o["id"] for o in (field or {}).get("options", []) if o["name"] == value), None)
            if option is None:
                missing.add(f"{name}={value}")  # the field or the option could not be created
                continue
            gql("mutation($p: ID!, $i: ID!, $f: ID!, $o: String!) { updateProjectV2ItemFieldValue(input: {projectId: $p, itemId: $i, fieldId: $f, value: {singleSelectOptionId: $o}}) { projectV2Item { id } } }",
                p=pid, i=item, f=field["id"], o=option)

    have_pulls = {n["content"].get("number") for n in project["items"]["nodes"] if n.get("content")}
    have_titles = {n["content"].get("title") for n in project["items"]["nodes"] if n.get("content")}

    print("pull requests")
    for number, area, kind in PULLS:
        if number in have_pulls:
            continue
        node = gql("query($owner: String!, $repo: String!, $number: Int!) { repository(owner: $owner, name: $repo) { pullRequest(number: $number) { id title } } }",
                   owner=OWNER, repo=REPO, number=number)["repository"]["pullRequest"]
        reply = gql("mutation($p: ID!, $c: ID!) { addProjectV2ItemById(input: {projectId: $p, contentId: $c}) { item { id } } }", p=pid, c=node["id"])
        print(f"  #{number} {node['title']}")
        if reply:
            set_fields(reply["addProjectV2ItemById"]["item"]["id"], {"Status": "Done", "Horizon": "Now", "Kind": kind, "Area": area})

    print("open work, as issues")
    repo = gql("query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { id labels(first: 50) { nodes { id name } } "
               "issues(first: 100, states: [OPEN, CLOSED]) { nodes { id title number } } } }", owner=OWNER, repo=REPO)["repository"]
    labels = {node["name"]: node["id"] for node in repo["labels"]["nodes"]}
    issues = {node["title"]: node for node in repo["issues"]["nodes"]}
    for item in DRAFTS:
        if item["title"] in have_titles:
            continue
        issue = issues.get(item["title"])
        if issue is None:
            wanted = [labels[name] for name in LABELS.get(item["fields"]["Kind"], []) if name in labels]
            if item["fields"]["Area"] == "Docs and site" and "documentation" in labels:
                wanted.append(labels["documentation"])
            reply = gql("mutation($r: ID!, $t: String!, $b: String!, $l: [ID!]) { createIssue(input: {repositoryId: $r, title: $t, body: $b, labelIds: $l}) { issue { id number } } }",
                        r=repo["id"], t=item["title"], b=item["body"], l=sorted(set(wanted)))
            issue = reply["createIssue"]["issue"] if reply else {"id": "", "number": "?"}
        print(f"  #{issue['number']} {item['title']}")
        reply = gql("mutation($p: ID!, $c: ID!) { addProjectV2ItemById(input: {projectId: $p, contentId: $c}) { item { id } } }", p=pid, c=issue["id"])
        if reply:
            set_fields(reply["addProjectV2ItemById"]["item"]["id"], item["fields"])
    if missing and not DRY:
        print("not set, because the field or option does not exist:", ", ".join(sorted(missing)))
    print("done" if not DRY else "dry run: nothing changed")


if __name__ == "__main__":
    main()
