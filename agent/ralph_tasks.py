"""The task list, the plan and the progress ledger: the loop's memory on disk."""

import os
import re
import time
from ralph_common import (ARCHIVE_FILE, BRIEF_FILE, CONVENTIONS_FILE, HEADING_LINE,
    MILESTONE, PLAN_FILE, PROGRESS_FILE, PROMPT_FILE, RESEARCH_FILE,
    ROUNDS_IF_BIG, ROUNDS_IF_SMALL, SEED_HEADINGS, TASK_DONE,
    TASK_OPEN, TASK_PARKED, read_text, say, write_text)


PROGRESS_HEADER = """# Progress

One row per session, written when it ends. Nothing here is a target -- they
are measurements, and the useful ones are the trends, not any single figure.

| when | rounds | ticked | open | lines | tokens | state | kept/rejected |
|---|---|---|---|---|---|---|---|
"""


PLAN_HEADER = """# Plan

Milestones, coarsest first. LocalCoder breaks one at a time into the task list
as the list empties, and writes a fresh set of milestones when they run out.

`## [ ]` means not yet broken into items. `## [x]` means it has been -- which
is not the same as finished. The task list carries what is done.

Yours to edit. Reorder them, rewrite them, add your own; the next milestone
taken is simply the first one still marked `[ ]`.

"""


def milestones(plan_path):
    """[(title, body, decomposed)] in file order."""
    body = read_text(plan_path)
    if not body:
        return []
    marks = list(MILESTONE.finditer(body))
    out = []
    for index, match in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        out.append((match.group(2), body[match.end():end].strip(),
                    match.group(1).lower() == "x"))
    return out


def next_milestone(plan_path):
    """The first milestone not yet broken into items, or None."""
    for title, body, decomposed in milestones(plan_path):
        if not decomposed:
            return title, body
    return None


def mark_decomposed(plan_path, title):
    """Tick a milestone as broken down.

    Done here rather than by the model. Asking it to edit a second file in the
    same round is another chance for a diff that will not apply, and this is
    bookkeeping we can do exactly.
    """
    body = read_text(plan_path)
    pattern = re.compile(r"^(##\s*)\[ \](\s*%s\s*)$" % re.escape(title), re.MULTILINE)
    if not pattern.search(body):
        return False
    return write_text(plan_path, pattern.sub(r"\1[x]\2", body, count=1))


def find_notes_file(workspace, configured=""):
    """The file holding the checkboxes. Configured, or the obvious candidate."""
    if configured:
        path = configured if os.path.isabs(configured) else os.path.join(workspace, configured)
        return path if os.path.isfile(path) else ""
    try:
        names = os.listdir(workspace)
    except OSError:
        return ""
    # Our own files are markdown too, and one of them is literally PLAN.md,
    # which the "plan" spelling below would happily adopt as the task list.
    ours = {f.lower() for f in
            (PLAN_FILE, ARCHIVE_FILE, BRIEF_FILE, CONVENTIONS_FILE,
             RESEARCH_FILE, PROMPT_FILE)}
    markdown = [n for n in names
                if n.lower().endswith(".md") and n.lower() not in ours]
    for pick in ("notes", "task", "todo", "plan"):
        for name in markdown:
            if pick in name.lower():
                return os.path.join(workspace, name)
    return ""


def open_tasks(notes_path):
    """The unticked items, in file order."""
    return [m.strip() for m in TASK_OPEN.findall(read_text(notes_path))]


def archive_path(notes_path):
    return os.path.join(os.path.dirname(notes_path), ARCHIVE_FILE)


def brief_path(notes_path):
    return os.path.join(os.path.dirname(notes_path), BRIEF_FILE)


def done_count(notes_path):
    """Everything ever ticked, whether it is still in the list or archived.

    This is the loop's only measure of progress -- it compares the count
    before and after a round to decide whether anything happened, and a
    checkpoint stops the run when it has not moved. Counting only what is
    still in the file means the moment items are archived out the total falls,
    real work reads as a stall, and an unattended run kills itself three hours
    in for having succeeded.
    """
    return (len(TASK_DONE.findall(read_text(notes_path)))
            + len(TASK_DONE.findall(read_text(archive_path(notes_path)))))


def parked_count(notes_path):
    return len(TASK_PARKED.findall(read_text(notes_path)))


PROGRESS_ROW = re.compile(r"^\|\s*([\d-]+ [\d:]+)\s*\|(.+)\|\s*$", re.MULTILINE)


def progress_path(notes_path):
    return os.path.join(os.path.dirname(notes_path), PROGRESS_FILE)


def record_progress(notes_path, row):
    """Append one session's numbers. Returns True if written.

    A ledger from before the columns changed is set aside as PROGRESS.old.md
    rather than mixed with rows it cannot be compared with.
    """
    path = progress_path(notes_path)
    body = read_text(path)
    if body and PROGRESS_HEADER.splitlines()[5] not in body:
        write_text(path[:-3] + ".old.md", body)
        body = ""
    body = body or PROGRESS_HEADER
    line = "| %s | %s |\n" % (time.strftime("%Y-%m-%d %H:%M"),
                              " | ".join(str(c) for c in row))
    return write_text(path, body.rstrip("\n") + "\n" + line)


def progress_rows(notes_path, last=8):
    """The most recent sessions as lists of cells, oldest first.

    [when, rounds, ticked, open, lines, tokens, state, kept/rejected]
    """
    out = []
    for stamp, rest in PROGRESS_ROW.findall(read_text(progress_path(notes_path))):
        cells = [c.strip() for c in rest.split("|")]
        if cells and cells[0].isdigit():          # skip the |---|---| divider
            out.append([stamp] + cells)
    return out[-last:]


def _num(cell):
    try:
        return float(str(cell).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _rate(row):
    """Items finished per round in one session, or None if too few rounds to say."""
    rounds, ticked = _num(row[1]), _num(row[2])
    if not rounds or rounds < 5 or ticked is None:
        return None
    return ticked / rounds


def _kept_share(row):
    """Share of reviewed changes the reviewer kept, or None."""
    try:
        kept, sent_back = (int(x) for x in row[7].split("/"))
    except (IndexError, ValueError):
        return None
    return kept / (kept + sent_back) if kept + sent_back >= 4 else None


def progress_summary(notes_path):
    """A few lines on where this project has got to. '' if too little history.

    This is the continuity the loop otherwise has none of. Each round starts
    with an empty head and can see the code as it is now, which tells it
    nothing about whether the last twenty hours of work made anything better
    -- so it optimises the only thing it can see, which is the next item.
    """
    rows = progress_rows(notes_path)
    if len(rows) < 2:
        return ""
    first, last = rows[0], rows[-1]
    moved = []
    was, now = _num(first[4]), _num(last[4])
    if was is not None and now is not None:
        moved.append("code %s lines -> %s" % ("{:,}".format(int(was)), "{:,}".format(int(now))))
    rates = [r for r in (_rate(row) for row in rows) if r is not None]
    if rates:
        moved.append("%.2f items per round lately" % rates[-1])
    ticked = sum(_num(r[2]) or 0 for r in rows)
    return ("Across the last %d sessions (%s to %s): %d items finished, %s."
            % (len(rows), first[0][:10], last[0][:10], ticked, "; ".join(moved) or "no trend yet"))


def progress_regressions(notes_path):
    """Where the numbers are worse than the best this project has managed.

    Ticking items is not the same as improving anything, and nothing else
    here would notice a run that got steadily worse at its job. Compared with
    the best ever seen rather than the previous session, because a slow
    decline never trips a step-change test.
    """
    rows = progress_rows(notes_path, last=40)
    if len(rows) < 3:
        return []
    out = []
    for label, measure, floor in (("items finished per round", _rate, 0.5),
                                  ("share of changes the reviewer kept", _kept_share, 0.6)):
        values = [measure(r) for r in rows]
        if values[-1] is None:
            continue
        earlier = [v for v in values[:-1] if v is not None]
        if len(earlier) < 2:
            continue
        best = max(earlier)
        if best and values[-1] < best * floor:
            out.append("%s is %.2f, down from a best of %.2f" % (label, values[-1], best))
    return out


def add_items(notes_path, heading, items):
    """Append items to the task list ourselves.

    Where the loop has found real work by measurement rather than by asking,
    it should write it down directly. Handing the model a prompt that says
    "now add an item about X" is a round spent, a diff that can fail to apply,
    and a chance for it to write down something other than X.
    """
    body = read_text(notes_path)
    if not body:
        return 0
    fresh = [i for i in items if i not in body]
    if not fresh:
        return 0
    block = "\n\n### %s\n\n" % heading + "\n".join("- [ ] %s" % i for i in fresh) + "\n"
    write_text(notes_path, body.rstrip() + "\n" + block)
    return len(fresh)


def remember_review(notes_path, task_text, reason):
    """Put the reviewer's reason under the item, so the next try has it.

    This is how the two agents compare notes: the reviewer writes on the item,
    and the worker reads the item. Only the latest reason is kept -- a stack
    of old verdicts would crowd out the one that matters.
    """
    body = read_text(notes_path)
    pattern = re.compile(r"^([ \t]*[-*][ \t]*\[ \][ \t]*%s[ \t]*)\n(?:[ \t]+- \*Review\*:[^\n]*\n)?"
                         % re.escape(task_text), re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return False
    note = "  - *Review*: rejected last try -- %s\n" % reason.strip()[:200]
    return write_text(notes_path, body[:match.start()] + match.group(1) + "\n" + note
                      + body[match.end():])


def park_task(notes_path, task_text, reason):
    """Set an item aside as `- [!]` so the loop stops butting against it.

    It is not done and not forgotten -- it is flagged for a human, and the run
    moves on to work that can still be finished.
    """
    body = read_text(notes_path)
    pattern = re.compile(
        r"^([ \t]*[-*][ \t]*)\[ \]([ \t]*%s[ \t]*)$" % re.escape(task_text),
        re.MULTILINE,
    )
    match = pattern.search(body)
    if not match:
        return False
    replacement = "%s[!]%s\n  - *Parked*: %s" % (match.group(1), match.group(2), reason)
    write_text(notes_path, body[:match.start()] + replacement + body[match.end():])
    return True


JOINERS = re.compile(r"\s&\s|\s+and\s+|,|/|\+", re.I)


CODE_SPAN = re.compile(r"`[^`]*`")


# "In `Game.run`, ..." and "In the HUD, ..." locate the work; they do not add to it.
WHERE_FIRST = re.compile(r"^\s*(in|under|inside|within|at)\b[^,]{0,60},\s*", re.I)


def triage(task_text):
    """How many rounds this item gets. Returns (budget, word).

    This used to ask the model. It was measured doing worse than counting: it
    spent 500-700 tokens and 3-5 seconds per item, all of it reasoning, and on
    the hardest item it filled its whole budget thinking and returned nothing
    at all. Splitting on the words people use to join two jobs together agreed
    with every verdict the model did manage, instantly and for free.

    An item that names one thing gets a short leash; one that names several
    gets a longer one, because it will most likely be split before it is done.
    """
    # Commas inside `code` are punctuation in an argument list, and a leading
    # "In <function>," only says where to work. Counting either as a second job
    # marked every well-written item as big, which is every item on a list that
    # names the function it is about.
    text = CODE_SPAN.sub(" ", task_text)
    text = WHERE_FIRST.sub("", text)
    parts = [p for p in JOINERS.split(text) if p.strip()]
    if len(parts) > 1:
        return ROUNDS_IF_BIG, "names %d things" % len(parts)
    if len(text.split()) > 14:
        return ROUNDS_IF_BIG, "long"
    return ROUNDS_IF_SMALL, "one thing"


NOTE_LINE = re.compile(r"^(\s*)\*?Note:?\*?:?\s*(.+)$", re.MULTILINE | re.IGNORECASE)


MAX_NOTE = 90


def _lift_sections(notes_path, wanted, out_path, title, blurb):
    """Move whole sections out of the task list into a file of their own.

    Returns the number of characters moved. The task list keeps a one-line
    pointer, so a person reading it can still find where the material went.
    """
    body = read_text(notes_path)
    if not body:
        return 0
    marks = list(HEADING_LINE.finditer(body))
    spans = []
    for index, match in enumerate(marks):
        name = match.group(2).lower()
        if name.startswith("found"):
            continue                      # a refill's own output, not a brief
        if not any(word in name for word in wanted):
            continue
        # Stop at the next heading of ANY depth, not just a shallower one.
        # Taking subsections too meant `## Not now` swallowed every `###`
        # after it -- including the refill's own output, and with it four
        # unfinished items. A brief section is flat prose; anything nested
        # under it is somebody else's.
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        # And whatever the headings say, never move live work. This is the
        # guard that matters: everything else here is an optimisation, and
        # losing an open item is not a trade worth making for any of it.
        if TASK_OPEN.search(body[match.start():end]):
            continue
        spans.append((match.start(), end))
    if not spans:
        return 0

    moved = "\n\n".join(body[start:end].strip() for start, end in spans)
    # Back to front, so removing one span does not shift the next.
    for start, end in reversed(spans):
        body = body[:start] + body[end:]
    body = re.sub(r"\n{3,}", "\n\n", body).rstrip() + "\n"

    existing = read_text(out_path)
    if not existing:
        existing = "# %s\n\n%s\n\n" % (title, blurb)
    write_text(out_path, existing.rstrip() + "\n\n" + moved + "\n")
    write_text(notes_path, body + "\n*(%s -- see %s)*\n"
               % (title, os.path.basename(out_path)))
    return len(moved)


def ensure_conventions(workspace, notes_path):
    """Move the standing coding rules into their own read-only file.

    aider's own guidance: keep conventions in a file loaded with `--read`, so
    it is marked read-only and gets cached, instead of retyping the rules into
    every prompt. Ours were living inside the task list, which is editable and
    resent in full every round -- so the model could quietly rewrite its own
    standards, and we paid for them twice.

    We were still paying twice. This wrote the rules out and then left them in
    the task list, and because it returned early once the file existed the
    duplicate was never cleaned up -- so the standards went in every round as
    read-only *and* again as editable text.
    """
    path = os.path.join(workspace, CONVENTIONS_FILE)
    marker = "## Coding standards"
    body = read_text(notes_path)
    if not os.path.isfile(path) and marker in body:
        rules = body.split(marker, 1)[1].strip()
        write_text(path, "# Coding standards\n\n%s\n" % rules)
        say("    wrote %s (read-only, cached each round)" % CONVENTIONS_FILE)
    if os.path.isfile(path) and marker in body:
        moved = _lift_sections(notes_path, ("coding standard",), path,
                               "Coding standards", "")
        if moved:
            say("    took %d bytes of duplicated standards out of the task list"
                % moved)
    return path if os.path.isfile(path) else ""


# What a refill round needs and a working round does not: where the next batch
# of work comes from, and the background reading behind it.
BRIEF_WANTED = SEED_HEADINGS + ("reference", "background", "blueprint", "not now")


BRIEF_BLURB = ("Standing instructions and background, kept out of the task list so "
               "they are not\nresent on every round. Read-only, and only when the "
               "list runs dry and\nLocalCoder goes looking for the next batch of work.")


ARCHIVE_BLURB = ("Finished work, moved out of the task list once it stopped being "
                 "recent.\nStill counted as done, still readable when the loop "
                 "reviews what it has\nclaimed -- just not resent on every round.")


def extract_brief(workspace, notes_path):
    """Lift the standing sections and reference material into BRIEF.md."""
    return _lift_sections(notes_path, BRIEF_WANTED, brief_path(notes_path),
                          "Brief", BRIEF_BLURB)


# The `- [x]` line plus the indented `*Note:*` lines hanging off it.
DONE_BLOCK = re.compile(r"^[ \t]*[-*][ \t]*\[[xX]\][^\n]*(?:\n[ \t]+[^\n]*)*",
                        re.MULTILINE)


def archive_done(notes_path, keep=8):
    """Move all but the most recent finished items into DONE.md.

    The done pile is what kills this file in the end. Trimming the notes on
    each item slows it; nothing stopped it. 57 items measured here at 3,522
    tokens, on every round, to tell the model about work it is not doing.

    A few are kept in place on purpose. They are the only thing telling a
    round with no memory what the last few rounds already did, which is what
    stops it doing one of them again.

    Returns the number of items moved.
    """
    body = read_text(notes_path)
    if not body:
        return 0
    blocks = list(DONE_BLOCK.finditer(body))
    if len(blocks) <= keep:
        return 0
    going = blocks[:-keep] if keep else blocks

    moved = "\n".join(m.group(0).rstrip() for m in going)
    for match in reversed(going):
        body = body[:match.start()] + body[match.end():]
    body = re.sub(r"\n{3,}", "\n\n", body)

    out = archive_path(notes_path)
    existing = read_text(out) or "# Done\n\n%s\n\n" % ARCHIVE_BLURB
    write_text(out, existing.rstrip() + "\n\n" + moved + "\n")
    write_text(notes_path, body)
    return len(going)


def trim_notes(notes_path, limit=MAX_NOTE):
    """Keep the task list from eating the context it is meant to leave room for.

    Every finished item grows a `*Note:*` line, and the whole file is sent on
    every round. Left alone it had doubled to ~3,100 tokens of explanations of
    work that was already done -- context spent describing the past instead of
    holding the code.
    """
    body = read_text(notes_path)
    if not body:
        return 0

    def shorten(match):
        indent, text = match.group(1), match.group(2).strip()
        if len(text) <= limit:
            return match.group(0)
        return "%s*Note:* %s..." % (indent, text[:limit].rsplit(" ", 1)[0])

    trimmed = NOTE_LINE.sub(shorten, body)
    if trimmed == body:
        return 0
    saved = len(body) - len(trimmed)
    write_text(notes_path, trimmed)
    return saved
