"""What the model is told: the standing prompt, refill briefs, round headers."""

import os
import re
from ralph_common import (HEADING_LINE, PLAN_FILE, PROMPT_FILE, RESEARCH_FILE, ROUND_FILE,
    SEED_HEADINGS, TASK_DONE_LINE, TERSE, read_text, say, write_text)
from ralph_tools import recent_lessons
from ralph_tasks import (brief_path, next_milestone, open_tasks, progress_regressions,
    progress_summary)


DEFAULT_PROMPT = """# How to work

Do the NEXT unfinished item in the task list, and only that one.

1. Read the task list. Find the first item still marked `- [ ]`.
2. Make the code changes for that ONE item. Apply them yourself -- actually
   edit the files. Never end your turn by describing an edit you have not
   made, and never ask me to paste, run, or apply anything for you.
3. Check your own work: re-read what you changed and confirm it is complete,
   syntactically valid, and consistent with the rest of the file.
4. Only if it is good, edit the task list: change that item's `- [ ]` to
   `- [x]` and add a one-line `*Note*:` under it saying what you did.
5. Stop. Do not start the next item.

If the item is too big to finish properly in one go, split it in the task list
into smaller `- [ ]` items, tick nothing, and stop. The next round picks up the
first of them.

If you need information you do not have, add a line in exactly this form and
stop -- the answer will be in RESEARCH.md next round:

    RESEARCH: <what you need to know>

Never touch the global Python install. Use the project's own venv if it has one.
Keep the change small. Another round follows this one.

**Be brief.** Do not narrate your thinking, do not restate the plan, do not
show the file back to me. Output the edit and one line saying what it does.
Everything you write competes with the code for the same small context window,
and a long answer runs out of room and loses the whole round.

# What we are building

The top of the task list says what the project is and what good looks like.
Read it before the first item and hold every change to it.

Elegant and minimal: clear names, small functions, bounds checked, degrades
gracefully when something is missing. It must keep starting without errors --
a round that leaves it unable to start is a failed round, and is rolled back.
"""


# The rules an item has to obey to survive being handed to a round that knows
# nothing else. Shared by every refill, whatever the source of the ideas.
# Instructions in imperative short form. Worth having for two reasons, only
# one of which is tokens: at ~700 tokens against a ~13,000 token round the
# saving is about 3%, which is real but small. The other reason is that a
# small model follows five short orders better than four paragraphs of
# reasoning about why the orders are what they are. The prose versions were
# written to be read by a person; these are written to be obeyed.
TERSE_REFILL_RULES = """Add 5-10 `- [ ]` items under a heading `### %s`.

Each item:
- Names its function. ``In `Game.draw_hud`, ...``
- Is ONE change.
- Is specific enough to start with nothing left to decide.
- If too big for one round, is the first step of the big thing.

Vary them: a bug, a missing capability, robustness, speed, a shortcut paid
off. Five versions of one idea is a bad batch however good the idea.

Do not survey the code first. Write the first item, then the next.

Edit the task list. No code this round.
"""


REFILL_RULES = """Add between five and ten new `- [ ]` items to the task list, under a heading
`### %s`.

Every item must obey these rules, because each one becomes a single short round
of work with no memory of this one:

- Name the exact function it applies to, like ``In `Game.draw_hud`, ...``.
- Describe ONE change. If it needs two, write two items.
- Be specific enough to act on without deciding anything first. "Improve the
  visuals" is useless. "In `Player.render`, draw the barrel two pixels thicker"
  is an item.
- If the idea is too big for one round -- a whole mode, a whole subsystem --
  write the first concrete step of it, not the whole thing.

**Do not survey the code first.** Go straight to the first thing worth doing
and write it down, then the next. A brief like "check every aspect of the
software" is not asking for an inventory of every class before you begin -- it
is asking for the handful of items you would start with. Working through the
whole file before writing anything is how this round runs out of room and
returns nothing at all.

Write nothing but the task list edit. Do not touch the source this round.
"""


EXEMPLAR_NOTE = """
Items already on this list, as a guide to the size and spread that works here:

%s

Match that shape -- one function, one change, specific enough to start on --
and match that *spread*. Those examples are not all visual, or all bug fixes,
or all polish: there is robustness, a missing capability, something that changes
how it behaves, something that makes it faster, and something that pays off a
shortcut taken earlier. A batch that is five variations on one theme is a
worse batch than five different kinds of improvement, however good the theme.
"""


def tests_note(notes_path):
    """A nudge to write tests, for a project that has none. Else ''.

    LocalCoder runs a project's tests after every edit and feeds failures back
    inside the same round -- but only once there are tests to run, and nothing
    makes them appear. So when there are none, planning is told to make them a
    milestone. Once they exist the check switches itself on.
    """
    folder = os.path.dirname(notes_path)
    try:
        names = os.listdir(folder)
    except OSError:
        return ""
    if any(n.startswith("test_") and n.endswith(".py") for n in names) \
            or os.path.isdir(os.path.join(folder, "tests")):
        return ""
    return ("\n---\n\nThis project has no automated tests. Make one milestone a "
            "small set of pytest tests, in files named test_*.py, for the core "
            "logic -- the functions that compute things rather than the ones "
            "that draw them. Once they exist they run after every edit and "
            "catch breakage inside the round that caused it.\n")


def history_note(notes_path):
    """Where this project has come from, for the rounds that decide direction.

    Every round starts with an empty head and sees only the code as it stands,
    which says nothing about whether the last twenty hours improved it. A
    planner without that reaches for whatever the source suggests today and
    proposes the same kind of thing it proposed last week. This is the only
    continuity the loop has.
    """
    trend = progress_summary(notes_path)
    slipped = progress_regressions(notes_path)
    if not trend and not slipped:
        return ""
    out = ["", "---", "", "How this project has been going:", "", trend or ""]
    if slipped:
        out += ["",
                "And something has gone backwards, which matters more than "
                "anything new:"]
        out += ["    - %s" % s for s in slipped]
        out += ["", "Give that a milestone of its own, first."]
    return "\n".join(out) + "\n"


def exemplars(notes_path, want=5):
    """A few existing items, to show the generator what good looks like here.

    Cheaper and more honest than describing the house style in the abstract:
    the list already contains the answer, written by whoever cared enough to
    write it, and the model is about to be asked for more of the same.
    """
    pool = open_tasks(notes_path) or TASK_DONE_LINE.findall(read_text(notes_path))
    if not pool:
        return ""
    # From the end: the newest items are the ones written since the last time
    # anyone thought about what these should look like.
    picked = pool[-want:]
    return EXEMPLAR_NOTE % "\n".join("- %s" % p[:150] for p in picked)


# Used when the task list has no standing instructions of its own to work from.
REVIEW_SOURCE = ("Found by review", """**Start by doubting the work already done.** Read the ticked `- [x]` items and
check each one against the source. Some will have been ticked by someone who
read the code, decided it looked right, and moved on without changing anything.
Some will have been done badly. Some will have broken something else. Where you
find one, add a new `- [ ]` item saying exactly what is still wrong -- do not
untick the old one, and do not trust its note.

Then read the source for what is missing or wrong on its own terms: crashes
waiting to happen, values that are never used, things drawn in the wrong order,
feedback the player never gets, rules that do not fire.""")


REFILL_HEAD = """The task list has no unfinished items left, and there is still
time on the clock. Your job this round is to find the next work and write it
down. Do not change any code.

"""


CHECKBOX_LINE = re.compile(r"^\s*[-*]\s*\[[ xX!]\].*$", re.MULTILINE)


MAX_SEED_CHARS = 2400


def seed_sections(notes_path):
    """The prose sections saying what to do when the list runs dry.

    A task list that has been worked through for a week ends up with a tail of
    headings like `## features` and `## Bug Hunt` holding sentences, not
    checkboxes -- the operator writing down where the next batch of work should
    come from. Nothing was reading them, so a refill round invented its own
    direction every time and the standing instructions sat there unused.

    Read from BRIEF.md once these sections have been moved out of the task
    list, and from the task list itself until then.

    Returns [(heading, body)] in file order, prose only.
    """
    body = read_text(brief_path(notes_path)) or read_text(notes_path)
    if not body:
        return []
    marks = list(HEADING_LINE.finditer(body))
    found = []
    for index, match in enumerate(marks):
        title = match.group(2)
        # A refill writes its items under `### Found under: <that section>`,
        # which matches the section it came from and would be read back as a
        # standing instruction next time -- shifting the rotation and feeding
        # the model its own output as a brief. Seen on the first live run:
        # refill 2 drew "When out of tasks" again instead of moving on to
        # "features". Headings starting with "Found" are output, not input.
        if title.lower().startswith("found"):
            continue
        if not any(word in title.lower() for word in SEED_HEADINGS):
            continue
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        # Checkboxes in one of these sections are real work, already counted by
        # the loop. What we want is the prose around them.
        text = CHECKBOX_LINE.sub("", body[match.end():end])
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 40:
            found.append((title, text[:MAX_SEED_CHARS]))
    return found


PLAN_PROMPT = """The task list is empty and there is still time. Do not write task
items this round and do not touch any code. Write the *plan* they will come
from.

Read the source and the brief below, then fill in `%s` with the
milestones this project still needs -- between six and twelve of them, in the
order you would tackle them.

A milestone is a heading in exactly this form:

    ## [ ] Short name of the milestone

    Two or three lines on what "done" means for it, and why it matters. Name
    the parts of the code it will touch.

The `[ ]` marks it as not yet broken down. Leave every one of them unticked;
something else fills them in later, one at a time.

What makes a good milestone here:

- It is a *capability*, not an edit. "Weapons other than the bazooka" is a
  milestone. "Add a dict to `Game.__init__`" is one step inside one.
- It is worth five to ten rounds of work. Smaller than that belongs inside
  another milestone; much bigger and it needs splitting in two.
- It leaves a gap you can see how to fill. If you cannot picture the first
  concrete step, say so in the milestone body -- the next round will start
  by working that out.
- Keep already-finished ground out of it. Read what the code does now before
  proposing to build something it already has.

If you need to know something you do not -- how a mechanic is normally done,
what a library supports -- write one line anywhere in the file:

    RESEARCH: <the question>

The answer will be in %s before it is needed.

---
%s
---

Write nothing but %s.
"""


DECOMPOSE_PROMPT = """The task list is empty and there is still time. This round turns
ONE milestone from the plan into the next batch of work. Do not touch any code.

The milestone:

---
## %s

%s
---

Read the source and work out what this milestone actually requires,
given what the code already does. Then write the steps into the task list.
"""


VERIFY_PROMPT = """The task list is empty and there is still time. Before taking on
more, check that what is already ticked off is really true. Do not touch any
code this round.

Take the finished `- [x]` items still in the task list and read each one
against the source. You are looking for:

- items ticked by someone who read the code, decided it looked right, and
  moved on without changing anything
- changes that were made but do not do what the item asked
- changes that work but broke or contradicted something else
- items whose note claims more than the code supports

Do not untick anything and do not trust the notes. Where you find a gap, write
a new `- [ ]` item saying exactly what is still wrong.

If everything holds up, say so by writing three items for the most obvious
weaknesses you noticed in the code while checking.
"""


# What the loop asks for when the list runs dry, in order, repeating. Mostly
# decomposition -- that is the engine that keeps work coming -- with the
# operator's own briefs and a verification pass woven in, because a plan
# followed without ever looking back builds on its own unchecked claims.
REFILL_CYCLE = ("decompose", "decompose", "brief", "decompose", "verify")


def rules(heading):
    """The item rules, long or short, depending on how they read better."""
    return (TERSE_REFILL_RULES if TERSE else REFILL_RULES) % heading


def compose_refill_prompt(notes_path, refills):
    """One refill round's prompt. Returns (text, label, mode, milestone).

    Four ways of finding the next work, cycled rather than chosen, so a long
    unattended run keeps making progress on a plan without either grinding one
    seam forever or drifting off what the operator asked for.
    """
    plan_path = os.path.join(os.path.dirname(notes_path), PLAN_FILE)
    mode = REFILL_CYCLE[(max(1, refills) - 1) % len(REFILL_CYCLE)]
    pending = next_milestone(plan_path)

    # Nothing left to break down means it is time to look up and plan again,
    # whatever the cycle says. This is what makes the loop self-sustaining:
    # the end of the plan is the trigger for the next one, not the end of the
    # session.
    if mode == "decompose" and not pending:
        mode = "plan"

    if mode == "plan":
        seeds = seed_sections(notes_path)
        brief = "\n\n".join("## %s\n%s" % (t, b) for t, b in seeds[:3]) or \
            "No standing brief. Plan from the code and what the project needs."
        return (PLAN_PROMPT % (PLAN_FILE, RESEARCH_FILE, brief, PLAN_FILE)
                + history_note(notes_path) + tests_note(notes_path),
                "planning the next milestones", mode, None)

    if mode == "verify":
        return (VERIFY_PROMPT + "\n" + rules("Found by checking the work")
                + exemplars(notes_path) + history_note(notes_path),
                "checking what is already ticked", mode, None)

    if mode == "brief":
        sources = seed_sections(notes_path) or [REVIEW_SOURCE]
        title, guidance = sources[(max(1, refills) - 1) % len(sources)]
        heading = (title if title.lower().startswith("found")
                   else "Found under: %s" % title)
        text = REFILL_HEAD
        text += ("The task list carries standing instructions under `%s`. That is\n"
                 "this round's brief -- read it as the operator telling you where the\n"
                 "next batch of work comes from, and turn it into items.\n\n"
                 "---\n%s\n---\n\n" % (title, guidance))
        return (text + rules(heading) + exemplars(notes_path),
                title, mode, None)

    title, body = pending
    return (DECOMPOSE_PROMPT % (title, body)
            + "\n" + rules(title) + exemplars(notes_path),
            "milestone: %s" % title, mode, title)


def ensure_prompt(workspace):
    """The prompt that gets re-fed every round. Yours to edit."""
    path = os.path.join(workspace, PROMPT_FILE)
    if not os.path.isfile(path):
        write_text(path, DEFAULT_PROMPT)
        say("    wrote %s -- what to build and how to work, both editable" % PROMPT_FILE)
    return path


def compose_round_prompt(workspace, prompt_path, broken, cut_off=False, task=None):
    """The standing prompt, plus whatever the last round's output actually did.

    This is the only feedback the model gets about its own work -- every round
    starts with an empty head, so if the picture is wrong and nobody says so,
    it will tick the box and move on.

    `task` is the current item's text; when given, lessons are ranked by
    relevance to it rather than simply by recency.
    """
    body = read_text(prompt_path)
    head = []
    if cut_off:
        # A round that ran out of room stops mid-sentence, and the next one
        # arrives knowing nothing about it. Two things go wrong from there:
        # it starts the item again from scratch, throwing away whatever did
        # land, or -- worse and more common -- it opens by describing what it
        # was going to do instead of doing it. Both cost the round.
        head += ["# THE LAST ROUND WAS CUT OFF PART-WAY", "",
                 "It ran out of room mid-answer on this same item. Some of its",
                 "work may already be in the file and some certainly is not.",
                 "",
                 "Read what is actually there before you write anything. Then",
                 "finish only the part that is missing -- do not start the item",
                 "again from the beginning, and do not open by summarising what",
                 "you are about to do. Go straight to the edit.",
                 ""]
    if broken:
        head += ["# FIRST, AND ONLY THIS", "",
                 "The last round left the program unable to run. Fix it now.",
                 "Tick nothing off and start no new work until it runs.", ""]
        for path, err in broken:
            head.append("    %s: %s" % (os.path.basename(path), err))
        head += [""]
    lessons = recent_lessons(workspace, task=task)
    if lessons:
        head += ["# Lessons from earlier rounds -- do not repeat these", ""] + lessons + [""]
    if head:
        body = "\n".join(head + ["---", ""]) + body
    round_path = os.path.join(workspace, ROUND_FILE)
    write_text(round_path, body)
    return round_path


DESIGN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DESIGN.md")


VISUAL = re.compile(
    r"\b(render|draw|display|hud|ui|colou?r|font|text|layout|screen|visual|"
    r"sprite|animat\w*|style|css|theme|icon|button|menu|panel|look|pixel|"
    r"shadow|outline|gradient|palette|background|overlay|design)\b", re.I)


def design_guide(*texts):
    """DESIGN.md, if anything here is about what a person sees. Else ''.

    Short rules on readability, hierarchy and colour, kept with LocalCoder
    rather than any one project because they hold for every screen: text
    must not overlap, pale on pale disappears, one thing matters most. The
    frame check can say *that* the HUD is unreadable; this is what tells the
    model how to make it readable. Only attached when the work is visual, so
    rounds about physics or file handling do not pay for it.
    """
    if not os.path.isfile(DESIGN_FILE):
        return ""
    return DESIGN_FILE if any(t and VISUAL.search(t) for t in texts) else ""
