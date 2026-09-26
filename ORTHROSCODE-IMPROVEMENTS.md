# OrthrosCode: improvements, ranked by expected gain

A plan for making OrthrosCode keep more good work, lose less of it, and prove
more of what it claims. Each proposal says why it should help (with the
evidence, from the system's own logs where there is any, and from published
work where there is not), what to build, where it goes in the code, and how to
tell whether it worked.

Written against `main` at `26aa9bb`. Module and function names refer to that
code.

## Status, 2026-09-26

Built, with tests; not yet measured on the real machine:

| # | What | Where |
|---|---|---|
| 0 | Round ledger; outcomes in field reports and on the page | `agent/ralph_ledger.py`, `orthros.py` |
| 1 | Test first, then code; the test kept only with code that passes it | `agent/ralph_testfirst.py` |
| 2 | Reviewer cites faults; the loop checks the citations | `supervisor_aider.py`, `ralph_scan.check_claims` |
| 3 | 12 held-out exercises; proof by score against the last and the best | `evals\`, `orthros.py` |
| 5 | Escalation ladder: whole files, architect mode, split | `agent/ralph_ladder.py` |
| 6 | Similar kept rounds shown as examples (BM25 over git history) | `agent/ralph_memory.py` |
| 7 | New items that repeat done, parked or listed work dropped (the deterministic part) | `ralph_tasks.drop_repeats` |
| 9 | Values at a failing test's failure, for the next round | `agent/ralph_explain.py` |
| 11 | Prompt-cache order: aider's file sets made stable (the draft model is a setting in LM Studio) | `ralph_session.py` |
| 17 | `--resume`; practice finishes not reported as early stops | `orthros.py` |

Left out for now, and why: **8** (mypy) -- the agents' code is built from
mixins, whose `self.x` from a sibling class mypy reports as missing, so it
would reject sound rounds; **12** (edit format per file) -- the ladder already
switches to whole files after a miss, and whole-file replies on larger files
run into the reply ceiling; **4, 10, 13, 14, 15, 16** are still to do.

---

## Contents

- [The starting point](#the-starting-point)
- [How this list is ordered](#how-this-list-is-ordered)
- [Summary table](#summary-table)
- [0. Measure every round (the prerequisite)](#0-measure-every-round-the-prerequisite)
- [1. Make "Done when" executable: test first, then code](#1-make-done-when-executable-test-first-then-code)
- [2. Reviewers who must cite what they object to](#2-reviewers-who-must-cite-what-they-object-to)
- [3. A real fitness function for self-improvement](#3-a-real-fitness-function-for-self-improvement)
- [4. Two candidates per round on one card](#4-two-candidates-per-round-on-one-card)
- [5. An escalation ladder for items that fail](#5-an-escalation-ladder-for-items-that-fail)
- [6. Learn from past rounds: retrieved examples](#6-learn-from-past-rounds-retrieved-examples)
- [7. An item linter, and duplicate detection](#7-an-item-linter-and-duplicate-detection)
- [8. Type checking as a free check](#8-type-checking-as-a-free-check)
- [9. Failures explained with values, not just messages](#9-failures-explained-with-values-not-just-messages)
- [10. Choose the model by measurement](#10-choose-the-model-by-measurement)
- [11. Faster tokens: draft models and prompt-cache order](#11-faster-tokens-draft-models-and-prompt-cache-order)
- [12. Edit format chosen per file](#12-edit-format-chosen-per-file)
- [13. Coverage- and mutation-guided work](#13-coverage--and-mutation-guided-work)
- [14. Find the change that broke it: automatic bisect](#14-find-the-change-that-broke-it-automatic-bisect)
- [15. Contain the code the agents run](#15-contain-the-code-the-agents-run)
- [16. Task mode: acceptance the operator owns](#16-task-mode-acceptance-the-operator-owns)
- [17. Smaller wins](#17-smaller-wins)
- [Considered and left out](#considered-and-left-out)
- [A suggested order of work](#a-suggested-order-of-work)
- [Sources](#sources)

---

## The starting point

The most recent day of self-improvement (2026-09-24, from the commit message
of `26aa9bb`) is the best evidence there is:

| | |
|---|---|
| rounds | 49 |
| changes kept | 7 (14%) |
| changes sent back | 23 |
| of those, judged sound on inspection | at least 9 (~40%) |
| turns ended early for sending work back | 2 |
| rejections for names defined outside the diff, or for work already done | 6 |

So the loop now runs, but it throws away as much good work as it keeps, and
most of what it keeps is not measured against anything outside itself. The
biggest gains are therefore in three places:

1. **Deciding correctly** whether a change is good: fewer false rejections,
   no false acceptances. Today that rests on one model's opinion of a diff.
   Execution is a far better judge than opinion, wherever it can be used.
2. **Producing more good candidates** per unit of time: the card is idle
   between requests and decoding is memory-bound, so more samples cost less
   than it seems.
3. **Measuring improvement** by something the agents cannot talk their way
   around: held-out tests, the same for every version.

## How this list is ordered

By expected gain in *useful work kept per hour* and in *measured coding
ability*, discounted for effort and risk. Items that only pay off once another
is in place say so. Proposals that were ultra-high effort for a small or
doubtful reward are listed at the end, with the reason, and not planned.

Effort is in rough developer-days for someone who knows this code: **S** is
under a day, **M** one to three days, **L** a week.

## Summary table

| # | Proposal | Gain | Effort | Depends on |
|---|---|---|---|---|
| 0 | Round ledger (SQLite) and trend view | enabler for everything below | S | -- |
| 1 | Executable "Done when": test first, then code | very high | M | -- |
| 2 | Reviewers that must cite; structured verdicts | very high | S--M | -- |
| 3 | Benchmark-gated proof and a version archive | very high (self mode) | M--L | 0 |
| 4 | Two candidates per round on one card | high | M | 0, measure first |
| 5 | Escalation ladder (warmer, architect, split) | high | S--M | -- |
| 6 | Retrieved examples from past rounds | high | M | 0 |
| 7 | Item linter and duplicate detection | medium--high | S | -- |
| 8 | Type checking as a free check | medium--high | S--M | -- |
| 9 | Failures explained with values | medium | S | -- |
| 10 | Model tournament on the practice suite | medium--high, one-off | M | 3 |
| 11 | Draft-model speculation, prompt-cache order | medium (speed) | S | measure first |
| 12 | Edit format per file | medium | S | 0 |
| 13 | Coverage- and mutation-guided items | medium | M | -- |
| 14 | Automatic bisect of regressions | medium (self mode) | M | 3 |
| 15 | Contain the code the agents run | safety, medium | M | -- |
| 16 | Task mode: operator-owned acceptance | high (task mode) | S--M | 1 |
| 17 | Smaller wins | small each | S | -- |

---

## 0. Measure every round (the prerequisite)

**Gain:** makes every other proposal measurable; on its own, finds where
rounds go. **Effort:** S.

### Why

Today the evidence is spread across `.localcoder-ralph.log`, the aider
transcript, `PROGRESS.md`, `FIELD_REPORT.md`, `LESSONS.md` and
`.orthros-state.json`, in prose. Every question in the starting point above
("how many rejections were sound?") had to be answered by reading logs by
hand. Proposals 2, 3, 4, 6 and 12 all need the same thing: one row per round,
queryable.

### What to build

A single SQLite file per agent pair, `ledger.sqlite` at the root, written by
the agent after every round (the agent already knows everything that goes in
it) and read by Orthros for the dashboard and the field report. `sqlite3` is
in the standard library, so this costs no dependency.

One table is enough to start:

```sql
CREATE TABLE IF NOT EXISTS rounds (
    id          INTEGER PRIMARY KEY,
    at          REAL,       -- time.time()
    agent       TEXT,       -- 'A' or 'B' (who ran)
    workspace   TEXT,       -- folder name: 'OrthrosCode B', 'tasks/x', 'practice/...'
    kind        TEXT,       -- 'self' | 'task' | 'practice' | 'refill'
    item        TEXT,
    attempt     INTEGER,
    temperature REAL,
    files_sent  INTEGER,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    seconds     REAL,
    symptom     TEXT,       -- '', 'context', 'enginedied', 'crashed'
    applied     INTEGER,    -- edits applied
    failed      INTEGER,    -- edits that did not match
    touched     INTEGER,    -- code changed
    broken      TEXT,       -- first check failure, '' if none
    caught      TEXT,       -- automatic-check rejection, '' if none
    verdict     TEXT,       -- 'accept' | 'reject' | '' | 'skipped'
    reason      TEXT,
    ticked      INTEGER,
    kept        INTEGER,    -- 1 if committed
    diff_sha    TEXT        -- sha1 of the diff, to find it again
);
```

### Where

A new module, `agent/ralph_ledger.py`, small enough for a round to read:

```python
"""One row per round, in SQLite: the evidence every decision here should rest on."""

import hashlib
import os
import sqlite3
import time

SCHEMA = """CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY, at REAL, agent TEXT, workspace TEXT, kind TEXT,
    item TEXT, attempt INTEGER, temperature REAL, files_sent INTEGER,
    tokens_in INTEGER, tokens_out INTEGER, seconds REAL, symptom TEXT,
    applied INTEGER, failed INTEGER, touched INTEGER, broken TEXT, caught TEXT,
    verdict TEXT, reason TEXT, ticked INTEGER, kept INTEGER, diff_sha TEXT)"""


def ledger_path():
    # The root folder, one above the agent: both agents write the same file.
    here = os.path.dirname(os.path.abspath(__file__))
    return os.environ.get("ORTHROS_LEDGER") or os.path.join(os.path.dirname(here),
                                                            "ledger.sqlite")


def record(**row):
    """Write one round. Never raises: a ledger must not be what stops a run."""
    row.setdefault("at", time.time())
    if "diff" in row:
        row["diff_sha"] = hashlib.sha1(row.pop("diff").encode("utf-8", "replace")).hexdigest()
    try:
        with sqlite3.connect(ledger_path(), timeout=10) as db:
            db.execute(SCHEMA)
            keys = sorted(row)
            db.execute("INSERT INTO rounds (%s) VALUES (%s)"
                       % (", ".join(keys), ", ".join("?" * len(keys))),
                       [row[k] for k in keys])
    except sqlite3.Error:
        pass
```

Call it in `Session.after_round` in `ralph_session.py`, just after the round's
commit, where every value is in scope. Two small preparations: set
`verdict, why = "", ""` beside `rejected_now = False` (today they exist only
inside the review branch), and have `set_temperature` keep the value it set
as `self.temperature`.

```python
        record(agent=os.environ.get("ORTHROS_AGENT", ""), workspace=os.path.basename(ws),
               kind=os.environ.get("ORTHROS_KIND", "self"), item=self.current_task or "",
               attempt=self.rounds_on_task, temperature=getattr(self, "temperature", None),
               tokens_in=result.sent, tokens_out=result.got,
               seconds=self.pace[-1][0] if self.pace else 0, symptom=result.symptom,
               applied=result.applied, failed=result.failed, touched=int(touched),
               broken=(self.broken[0][1][:200] if self.broken else ""),
               caught=("; ".join(caught)[:300] if caught else ""),
               verdict=verdict if touched and not self.broken else "skipped",
               reason=(why or "")[:300], ticked=after_done - before_done,
               kept=int(bool(self.commit and touched and not self.broken)), diff=diff)
```

Orthros sets `ORTHROS_AGENT` and `ORTHROS_KIND` in `agent_env` (it already
sets `ORTHROS_SESSION`).

### What it makes possible straight away

Three queries answer questions that took hours of log reading:

```sql
-- Where do rounds go? (per kind of outcome)
SELECT CASE
         WHEN symptom != '' THEN 'lost: ' || symptom
         WHEN failed > 0 AND applied = 0 THEN 'edit did not apply'
         WHEN broken != '' THEN 'broke a check'
         WHEN caught != '' THEN 'caught by scan'
         WHEN verdict = 'reject' THEN 'rejected by reviewer'
         WHEN kept = 1 THEN 'kept'
         ELSE 'no change'
       END AS outcome, COUNT(*) AS n
FROM rounds WHERE at > strftime('%s','now','-1 day') GROUP BY outcome ORDER BY n DESC;

-- Does a warmer retry ever win?
SELECT attempt, ROUND(AVG(kept), 2) AS kept_rate, COUNT(*) FROM rounds
WHERE kind != 'refill' GROUP BY attempt;

-- Reviewer reasons that recur (candidates for a fix in the prompt)
SELECT substr(reason, 1, 60) AS r, COUNT(*) FROM rounds
WHERE verdict = 'reject' GROUP BY r ORDER BY 2 DESC LIMIT 15;
```

Add a *Rounds* panel to the dashboard (an `/api/rounds` endpoint that runs the
first query for the last 24 hours) and a line in each field report with the
same breakdown. The field report then tells the twin, in numbers, where its
changes are losing rounds.

**How to tell it worked:** after one day, every round has a row, and the
starting-point table can be produced by one query instead of by reading logs.

---

## 1. Make "Done when" executable: test first, then code

**Gain:** very high. It replaces opinion with execution for most items.
**Effort:** M.

### Why

Every item already ends with `Done when:` and a check "anyone can make". Today
that check is read by a model and judged by a model. Execution is the most
reliable judge available, and the literature is consistent on this:

- AlphaCodium's flow, built around running generated tests and repairing
  against them, raised pass@5 on CodeContests from 19% to 44% with the same
  model.
- CodeT and MBR-exec select among candidates by what they do when run, and
  beat selection by likelihood or by a judge.
- SWE-agent's ablations show guardrails that reject bad edits at edit time
  reduce compounding errors.

On 2026-09-24 about 40% of rejections were false. Most of them were the
reviewer failing to see context. A test that passes needs no context.

### What to build

Split each item into two rounds, automatically:

1. **Round T (test):** "Write a unittest that checks exactly this: `<Done
   when>`. It must fail on the code as it stands. Do not change any source
   file other than the test." The loop checks that the new test **fails**
   before any code change (a test that already passes is either redundant or
   wrong), and that no other test changed.
2. **Round C (code):** the usual round, with the new test named in the prompt.
   The loop requires the new test to **pass**, and all old tests too.

The reviewer is still asked, but its role changes: the test now decides *does
it work*; the reviewer only decides *is it acceptable* (scope, style, no
collateral damage). A reviewer "reject" on a change that makes a failing test
pass becomes a *warning* by default, unless it cites a real problem (see
proposal 2).

Some items cannot be tested this way (prose, prompts, docs, config). They are
recognised by what they touch: an item that names only `.md` files, or whose
`Done when:` does not mention a function, return value, output or test, skips
round T.

### Where

`ralph_tasks.py` gets the classifier; `ralph_session.py` gets the two-phase
state; `ralph_checks.py` gets the "fails now / passes later" checks.

```python
# ralph_tasks.py
DONE_WHEN = re.compile(r"Done when:\s*(.+)$", re.I)
NAMED = re.compile(r"`([^`]+)`")                    # what an item names in backticks
CHECKABLE = re.compile(r"\b(returns?|raises?|prints?|equals?|is|are|==|test|passes)\b", re.I)


def acceptance(task_text):
    """The item's `Done when:` check, if a test could state it. Else ''."""
    match = DONE_WHEN.search(task_text or "")
    if not match:
        return ""
    check = match.group(1).strip()
    names = NAMED.findall(task_text)
    if not names or not CHECKABLE.search(check):
        return ""
    if all(n.endswith(".md") for n in names):
        return ""
    return check
```

The test round's prompt, in `ralph_prompts.py`:

```python
TEST_FIRST = """# THIS ROUND: THE TEST ONLY

The item below will be done in the next round. This round writes the test that
proves it, and nothing else.

Item: {item}

Write one unittest in `{test_file}` (create it if needed) that checks exactly:

    {check}

- Import what it tests from the project; do not copy code into the test.
- It must FAIL on the code as it stands now -- that is how we know it tests
  something.
- Change no other file. Tick nothing.
"""
```

The session keeps the test's name between the two rounds:

```python
# ralph_session.py, in Session.__init__
        self.pending_test = {}        # item -> (test file, test id) written for it

# in work_round, before send_round
        check = acceptance(task) if TEST_FIRST_ON else ""
        phase = "code"
        if check and task not in self.pending_test:
            phase = "test"
```

and after the round, in `after_round`:

```python
        if phase == "test":
            new_tests = tests_added(ws, round_diff(ws, self.edit_files))
            if len(new_tests) != 1:
                return self.test_round_failed(task, "write exactly one new test")
            outcome, out = run_one_test(ws, new_tests[0])
            if outcome == "passed":
                return self.test_round_failed(task, "the new test passes before any change: "
                                                    "it does not test the item")
            if outcome == "error" and not MISSING_YET.search(out):
                return self.test_round_failed(task, "the new test does not run: "
                                              + out.strip().splitlines()[-1][:120])
            self.pending_test[task] = new_tests[0]
            self.commit("LocalCoder ralph: test for round %d" % self.rounds)
            return True
```

An *error* (rather than a failure) is still a good first result when the thing
under test does not exist yet: a test of a new function fails with an
`ImportError` or `AttributeError` until the code round writes it. Any other
error means the test itself is broken. Three helpers, all new, for
`ralph_checks.py`:

```python
MISSING_YET = re.compile(r"\b(ImportError|ModuleNotFoundError|AttributeError|NameError)\b")
TEST_DEF = re.compile(r"^\+\s*def (test_\w+)", re.M)
TEST_CLASS = re.compile(r"^[ +]?class (\w+)\(.*TestCase", re.M)


def run_one_test(workspace, test_id, seconds=120):
    """('passed' | 'failed' | 'error', output) for one unittest id,
    e.g. 'test_bank.TestBank.test_zero'."""
    try:
        proc = subprocess.run([find_project_python(workspace), "-m", "unittest", "-q", test_id],
                              cwd=workspace, capture_output=True, text=True,
                              timeout=seconds, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "error", "timed out after %ds" % seconds
    out = proc.stderr + proc.stdout
    if proc.returncode == 0:
        return "passed", out
    return ("failed" if "FAIL:" in out and "ERROR:" not in out else "error"), out


def tests_added(workspace, diff):
    """Unittest ids of the test methods this diff adds: ['test_x.TestX.test_y']."""
    ids = []
    for name, (added, _) in _files_in_diff(diff).items():       # from ralph_scan
        base = os.path.basename(name)
        if not (base.startswith("test_") and base.endswith(".py")):
            continue
        body = read_text(os.path.join(workspace, name))
        for method in TEST_DEF.findall("\n".join(added)):
            owner = None
            for line in body.splitlines():                     # the class above the method
                cls = re.match(r"class (\w+)\(", line)
                owner = cls.group(1) if cls else owner
                if re.match(r"\s+def %s\(" % method, line):
                    break
            if owner:
                ids.append("%s.%s.%s" % (base[:-3], owner, method))
    return ids
```

`test_round_failed(task, why)` writes `why` under the item (as
`remember_review` does for a rejection), rolls the round back and counts an
attempt, like any rejected round. In the snippet above, `tests_added` is
called as `tests_added(ws, round_diff(ws, self.edit_files))`.

In the code round, the new test is added to the round's prompt ("the item is
done when `test_x.Cls.test_y` passes"), and `after_round` treats "the pending
test now passes, and all other tests pass" as the primary acceptance signal.
A model reviewer that rejects such a change must cite a line (proposal 2) or
its verdict is logged and ignored.

### Risks and how to contain them

- **Tests that test the wrong thing.** The "must fail first" rule removes the
  worst case (a test that passes on anything). A second guard: the reviewer
  reads the test round's diff against the item's text and can reject it, with
  the ordinary review prompt.
- **Items that are not code.** The classifier keeps them on the old path.
- **Twice the rounds per item.** The test round is short and cheap (one small
  file), and time is not the constraint here; wrong verdicts are.

**How to tell it worked:** in the ledger, the share of rounds ending in a
kept change should rise, and the share of reviewer rejections later judged
sound (by inspection of a sample) should fall. Practice scores (hidden tests)
should rise, because the agents learn to write code against tests.

---

## 2. Reviewers who must cite what they object to

**Gain:** very high, cheap. **Effort:** S--M.

### Why

A reviewer that says "REJECT: it uses `foo` which is not defined" when `foo`
is imported twenty lines above the diff costs a good round. On 2026-09-24 six
rejections were of that kind. The upstream commit already shows the reviewer
more context (`review_context` in `ralph_send.py`), which helps. What makes
false objections cheap to catch is to make every objection **checkable**:

- the reviewer must quote the exact line it objects to, and name the kind of
  fault from a fixed list;
- the loop checks the quote exists in the diff or the named code, and checks
  the claim where it can (a name "not defined" that pyflakes says is defined
  is a false claim);
- a claim that fails its check is discarded, and the change is kept.

This is the "LLM-as-a-judge needs deterministic guardrails" point from the
2026 literature, applied at the smallest scale: make the judge produce
something a program can verify.

### Structured output makes the reply parseable every time

LM Studio accepts `response_format` with a JSON schema on
`/v1/chat/completions` and constrains decoding to it, so "no clear verdict"
can no longer happen. The reviewer's call in `supervisor_aider._chat` gains an
optional schema:

```python
VERDICT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["accept", "reject"]},
                "faults": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": [
                                "does-not-do-the-item", "cut-off", "undefined-name",
                                "wrong-arguments", "read-before-assigned",
                                "breaks-other-code", "out-of-scope", "logic-error"]},
                            "line": {"type": "string", "maxLength": 200},
                            "why": {"type": "string", "maxLength": 200},
                        },
                        "required": ["kind", "line", "why"],
                    },
                },
            },
            "required": ["verdict", "faults"],
        },
    },
}


def _chat(prompt, max_tokens, timeout, temperature=0.1, schema=None):
    body = {"model": IDENTIFIER, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": temperature}
    if schema:
        body["response_format"] = schema
    ...
```

With a thinking model, check first that constrained output still leaves room
to think: if the model's reasoning goes into `reasoning_content` it is not
affected; if it goes into `content`, keep the free-text path for thinking and
add a second, short, constrained call that only extracts the verdict from the
first reply ("Here is a review. Fill in the form."). Both are cheap.

### Checking the claims

A new function beside `scan()` in `ralph_scan.py`:

```python
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def normalise(text):
    """Whitespace-insensitive form for "is this quote really there?\""""
    return " ".join((text or "").lstrip("+- ").split())


def defined_names(files):
    """Every name the project defines or imports at any level."""
    names = set()
    for path in files:
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(read_text(path))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                names.update((a.asname or a.name).split(".")[0] for a in node.names)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
    return names


def first_identifier(line, why):
    """The name a claim is about: the first backticked word in the reason, else
    the first identifier in the reason that also appears in the quoted line."""
    ticked = re.findall(r"`(\w+)`", why or "")
    if ticked:
        return ticked[0]
    in_line = set(IDENT.findall(line or ""))
    return next((w for w in IDENT.findall(why or "") if w in in_line), "")


def check_claims(faults, diff, context, files, lint_now):
    """Keep the faults a program can confirm or cannot refute; drop the rest.

    Returns (kept faults, dropped faults with the reason each was dropped).
    """
    shown = diff + "\n" + context
    kept, dropped = [], []
    defined = defined_names(files)                    # every def/class/import name
    for fault in faults:
        quote = normalise(fault["line"])
        if quote and quote not in normalise(shown):
            dropped.append((fault, "the quoted line is not in the change or the code"))
            continue
        if fault["kind"] == "undefined-name":
            name = first_identifier(fault["line"], fault["why"])
            if name and name in defined and not any(name in m and "undefined" in m
                                                    for m in lint_now):
                dropped.append((fault, "%s is defined, and pyflakes finds nothing undefined"
                                % name))
                continue
        if fault["kind"] == "wrong-arguments":
            if not call_mismatches(files):
                dropped.append((fault, "every call matches its function's signature"))
                continue
        kept.append(fault)
    return kept, dropped
```

and `review_change` becomes: *reject only if at least one fault survives
`check_claims`*. The dropped faults go into the ledger (`reason`) so the
prompt can be improved where it keeps producing the same false claim.

### Pairwise instead of absolute, when there are two candidates

When proposal 4 produces two candidates, ask "which of these two is better
for the item, and why" rather than "is this acceptable". Pairwise judgments
are consistently more reliable than absolute ones; run it both ways round (A
then B, B then A) and count only a winner that survives both orders, treating
a flip as a tie.

### Calibrating the reviewer

With the ledger (proposal 0) there is a cheap source of labels:

- a change the reviewer **accepted** that a later round or turn **reverted**
  (the rollback tags, `orthros/failed-N`) is a probable false acceptance;
- a change the reviewer **rejected** whose item was later done with a diff
  that is textually close (difflib ratio > 0.8) is a probable false rejection.

A weekly query lists both, and a small set of such cases (20 is enough) becomes
a regression set for the review prompt: `test_review_prompt.py` replays them
against the live model when run by hand, and reports agreement. Change the
review prompt only when agreement goes up.

**How to tell it worked:** "no clear verdict" drops to zero; the share of
rejections with a surviving cited fault is logged per day; false rejections
found by the weekly query go down.

---

## 3. A real fitness function for self-improvement

**Gain:** very high for *Improve itself*. It is what makes the mode an
optimiser instead of a random walk. **Effort:** M--L.

### Why

A version is "proven" today when it starts and does some work. That proves it
is not broken; it does not prove it is better. The two published systems that
did make self-modifying coding agents better both put a benchmark in the loop:

- **Darwin Gödel Machine** (Zhang, Hu, Lu, Lange, Clune, 2025): every agent
  version is evaluated on a coding benchmark; versions go into an *archive*;
  new versions are made from ones sampled from the archive, favouring good and
  under-explored ones. SWE-bench rose from 20% to 50%, Polyglot from 14% to
  31%.
- **SICA** (Robeyns et al., 2025): the agent edits its own code, and each
  version is scored on a benchmark suite; the best-scoring version becomes the
  next meta-agent. A subset of SWE-bench Verified rose from 17% to 53%.

OrthrosCode has the pieces: a practice suite with hidden tests
(`exercises/`), per-agent practice scores, and proven-version history. What
is missing is using the score to decide.

### What to build

1. **A bigger, fixed evaluation set.** Three exercises cannot tell two
   versions apart. Use 20--40 small Python exercises with hidden tests. The
   Python part of Aider's polyglot benchmark (Exercism problems, MIT-licensed,
   hidden tests included) is the obvious source; take the Python exercises
   only, since the loop is Python-first. Split them into a **dev** set the
   agents may see in practice, and a **held-out** set used only for proving.
2. **An evaluation run per candidate version**, between turns. For each
   exercise in the held-out set: a fresh copy, a short session (say 10
   minutes, or a fixed number of rounds so speed does not dominate), hidden
   tests, score. Twenty exercises at ten minutes each is three and a half
   hours: long, but the card would otherwise be idle overnight, and it runs
   only when a version is a candidate for proof.
3. **Proof by score.** A version is *proven* only if its held-out score is not
   worse than its parent's by more than noise (see below). Its changes are
   carried into the twin only then.
4. **An archive**, not a line. Keep every evaluated version (sha, parent,
   score, date). When an agent is rolled back, roll back to the best-scoring
   ancestor, not merely the last one that started. Occasionally (1 turn in 5)
   restart the twin from a high-scoring but under-explored archive entry
   instead of the latest, which is what let DGM escape local optima.

### Deciding "better" honestly

With 20 exercises, one exercise is five points of score; a single flaky run
moves it. Use a paired comparison: both versions run the *same* exercises, and
the count of exercises one solves and the other does not is compared. The sign
test is enough, and needs no library:

```python
from math import comb


def sign_test(wins, losses):
    """One-sided p-value that `wins` vs `losses` (ties dropped) is chance."""
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(comb(n, k) for k in range(wins, n + 1)) / 2 ** n


def better(child, parent, alpha=0.2):
    """child, parent: {exercise: passed_all}. True if the child is not worse."""
    wins = sum(1 for e in child if child[e] and not parent.get(e))
    losses = sum(1 for e in child if parent.get(e) and not child[e])
    # "Not worse" is the bar for proof; "better" is the bar for promotion.
    return losses <= wins or sign_test(losses, wins) > alpha
```

`alpha=0.2` is deliberately loose for *not worse*: the point is to stop real
regressions, not to demand significance from 20 samples.

### Where

- `orthros_work.py`: `evaluate(root, agent, exercises, minutes)` returning
  `{exercise: (passed, total)}`, reusing `start_practice`, `run_turn` with a
  work item of kind `"eval"`, and `score_practice`.
- `orthros.py`, in `judge`: instead of `self.prove(name, result["own"])` on a
  good turn, schedule an evaluation of `name` at that version when the
  version is new; prove on the evaluation's result.
- A new state entry `archive`: `[{sha, agent, parent, scores, at}]`, and a
  `retreat` that picks the best-scoring ancestor.
- The dashboard's mode panel shows the archive as a short table: version,
  held-out score, delta from parent.

```python
# orthros.py -- sketch of the new proof step
    def judge_by_score(self, name, sha):
        parent = self.agent(name)["good"]
        mine = self.evaluate(name, sha)             # runs the held-out set
        theirs = self.scores(name, parent)          # cached from the archive
        self.archive_add(name, sha, parent, mine)
        if better(mine, theirs):
            self.prove(name, sha)
            self.carry_over(name)
            self.event("%s proven by score: %d/%d held-out (parent %d/%d)"
                       % (name, solved(mine), len(mine), solved(theirs), len(theirs)), "good")
        else:
            self.rollback(name, "held-out score fell from %d to %d"
                          % (solved(theirs), solved(mine)))
```

### Guarding against gaming

The agents may edit anything in each other's folders, including the code that
runs practice. Keep all scoring in Orthros (it is already outside their
reach), keep hidden tests outside the agent folders (already so), and never
show held-out exercise names to the agents. Log a warning if an agent's code
ever mentions an exercise name from the held-out set.

**How to tell it worked:** a plot of held-out score by proven version, which
should rise over days; the number of rollbacks for "held-out score fell"
tells how often the loop would otherwise have kept a regression.

---

## 4. Two candidates per round on one card

**Gain:** high: more tries for about the same time. **Effort:** M. **Measure
first**: it depends on memory headroom.

### Why

Token generation on one GPU is limited by memory bandwidth, not arithmetic:
for each token the whole model is read once, whatever the batch size. Two
streams decoded together cost little more than one. llama.cpp's server does
continuous batching across parallel slots, and LM Studio exposes it as the
parallel setting (`LC_PARALLEL`). Repeated sampling with a verifier is the
cheapest reliable way to buy quality with time (Brown et al.: SWE-bench Lite
from 15.9% at one sample to 56% at 250 with the same model); two samples at
nearly the price of one is the first step of that curve.

The catch is memory: each slot needs its own KV cache. `config.cmd` already
warns that `LC_PARALLEL=4` crashed a load at 97%. With the K/V cache at Q8_0
there may be room for two slots at a smaller context, and
`agent/bench_parallel.py` exists to measure exactly this.

### Measure first

Run `bench_parallel.py` at `LC_CONTEXT=32768, LC_PARALLEL=2` with Flash
Attention and Q8_0 KV in LM Studio's model defaults. It reports VRAM left and
total tokens per second across both streams. Proceed only if VRAM left after
loading is at least 3 GB and combined throughput is at least 1.5 times one
stream's.

### What to build

In `Session.work_round`, when `PARALLEL >= 2`: run two aider rounds at once in
two **copies** of the workspace (git worktrees, so each has its own files),
with different temperatures (e.g. 0.2 and 0.6). Then:

1. check each candidate with the usual checks (`full_check`, `scan_round`);
2. drop any that fail;
3. if both survive and proposal 1's test exists, keep the one that passes it;
   if both pass, ask the pairwise reviewer (proposal 2) which is better;
4. apply the winner's diff to the real workspace and continue as today.

```python
# ralph_parallel.py -- the shape of it
import concurrent.futures as cf


def worktree(workspace, name):
    path = os.path.join(workspace, ".localcoder-wt", name)
    subprocess.run(["git", "-C", workspace, "worktree", "add", "-f", "--detach", path, "HEAD"],
                   capture_output=True)
    return path


def run_candidates(session, task, temps):
    folders = [worktree(session.workspace, "c%d" % i) for i in range(len(temps))]
    with cf.ThreadPoolExecutor(len(temps)) as pool:
        futures = [pool.submit(session.send_round_in, folder, task, t)
                   for folder, t in zip(folders, temps)]
        results = [f.result() for f in futures]
    return list(zip(folders, results))


def pick(session, task, candidates):
    alive = []
    for folder, result in candidates:
        files = session.files_in(folder)
        if full_check(folder, files, session.entry, session.run_seconds):
            continue
        diff = round_diff(folder, files)
        if not diff or any(k == "reject" for k, _ in session.scan_in(folder, diff)):
            continue
        alive.append((folder, diff))
    if len(alive) < 2:
        return alive[0] if alive else None
    return session.compare(task, alive[0], alive[1])       # pairwise, both orders
```

`send_round_in(folder, task, temperature)` is `send_round` with the workspace
and the model-settings file parameterised: aider takes
`--model-settings-file`, so each candidate gets its own file with its own
temperature.

Worktrees are cheap, share the object store, and are removed with
`git worktree remove --force` after the round.

### Risks

- **Memory.** Halving context per slot may push some rounds over the window.
  The guard already refuses those; the ledger will show whether it happens
  often.
- **Two aider processes writing the same `.aider*` caches.** Worktrees give
  each its own folder, so they do not collide.

**How to tell it worked:** ledger kept-rate per hour, before and after, over at
least a day each; practice scores.

---

## 5. An escalation ladder for items that fail

**Gain:** high for hard items, which are where the rounds go. **Effort:** S--M.

### Why

Today an item gets up to three tries, each warmer. Warmer is one way to get a
different answer; there are better ones for an item that has already failed,
and aider supports them:

- **Architect mode** (`--architect`): one pass reasons about the change in
  prose, a second turns it into edits. Aider's benchmarks show it raising
  scores for most models, and it separates "what to do" from "how to write
  the edit", which is exactly where small models fail.
- **Split** the item: an item that failed twice is usually too big. The loop
  can ask for a split instead of a third try.
- **Whole-file edits** for a file under ~300 lines: when the SEARCH blocks
  keep missing, whole-file output is the format that fails least on weaker
  models, at a token cost that small files make affordable.

### What to build

Replace the single budget in `step()` with a ladder, chosen by what went wrong
last time (the ledger has it):

| last failure | next attempt |
|---|---|
| none yet | normal round, cold |
| reviewer rejected with a surviving fault | normal round, the fault quoted in the prompt |
| edit did not apply | whole-file format for that file (if small) |
| broke a check / test failed | architect mode, the failure in the prompt |
| no change at all | architect mode, warmer |
| two failures of any kind | split the item (a refill-like round on this item only) |
| split item's children also failing | park |

```python
# ralph_session.py
LADDER = ("plain", "fixed", "architect", "split")


def next_rung(self, task):
    history = self.item_history.get(task, [])      # outcomes of earlier rounds on it
    if not history:
        return "plain"
    last = history[-1]
    if len(history) >= 2 and last not in ("kept",):
        return "split"
    if last in ("broke", "no-change"):
        return "architect"
    if last == "edit-missed":
        return "whole"
    return "fixed"
```

Architect mode for one round is a command-line change in
`build_round_command`: append `--architect` (and, if the settings allow,
`--editor-edit-format whole` for small files).

A **split round** is a variant of `refill_list` scoped to one item: the prompt
is "This item failed twice (reasons: ...). Replace it with 2--4 smaller items,
each one change to one function with its own `Done when:`." The item becomes a
heading, its children the new items.

**How to tell it worked:** ledger kept-rate by attempt number; the share of
items parked should fall.

---

## 6. Learn from past rounds: retrieved examples

**Gain:** high once there is history. **Effort:** M.

### Why

LESSONS.md holds one line per mistake. What a small model uses best is an
*example*: a similar item, and the diff that was kept for it. ExpeL stores
successful trajectories and retrieves the most similar ones as few-shot
examples at inference time; Agent Workflow Memory abstracts recurring routines
from them; both report steady gains without any training. OrthrosCode already
has every kept diff in git and every item's text in `DONE.md`.

### What to build

A small, standard-library retrieval index over past rounds:

- **what is indexed:** for every kept round, the item text, the files, and the
  diff (from git, via the commit the round made); for every rejected round, the
  item and the surviving fault;
- **how it is searched:** BM25 over item text plus backticked names. No
  embeddings model, no second model on the card; BM25 is thirty lines of
  Python and does well on short technical text with shared identifiers;
- **what goes in the prompt:** the one or two most similar *kept* examples
  (item and diff, trimmed to ~1,500 tokens together), and the most similar
  *rejected* attempt's fault, under a heading "How similar items went here".

```python
# ralph_memory.py -- BM25 over past items, standard library only
import math
import re
from collections import Counter

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def tokens(text):
    out = []
    for word in TOKEN.findall(text or ""):
        out.append(word.lower())
        out += [p.lower() for p in re.split(r"_|(?<=[a-z])(?=[A-Z])", word) if len(p) > 2]
    return out


class Index:
    def __init__(self, docs):                   # docs: [(key, text)]
        self.keys = [k for k, _ in docs]
        self.tf = [Counter(tokens(t)) for _, t in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter(w for c in self.tf for w in c)
        n = len(docs)
        self.idf = {w: math.log(1 + (n - d + 0.5) / (d + 0.5)) for w, d in df.items()}

    def search(self, query, k=2, k1=1.2, b=0.75):
        q = tokens(query)
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for w in q:
                if w in tf:
                    f = tf[w]
                    s += self.idf[w] * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / self.avg))
            scores.append((s, self.keys[i]))
        return [key for s, key in sorted(scores, reverse=True)[:k] if s > 0]
```

The documents come from the ledger (proposal 0: item, diff_sha, kept) and git
(`git show <commit> -- <files>` for the diff). Build the index once per
session in `prepare()`; add to it as rounds are kept.

In `compose_round_prompt`, after the lessons:

```python
    FENCE = "`" * 3                  # a Markdown code fence around each diff
    examples = memory.similar(task, k=2)
    if examples:
        head += ["# How similar items were done here", ""]
        for ex in examples:
            head += ["Item: %s" % ex.item, "", FENCE + "diff", ex.diff[:3000], FENCE, ""]
```

Keep it bounded: two examples, 3,000 characters each at most, and none at all
when the prompt is already near the window (the guard's numbers are known at
this point).

### Across the two modes

Examples from task mode are the most valuable ones for self mode and vice
versa: an item done well on a user's project is exactly the "general coding"
the practice suite measures. Index all workspaces into the one ledger.

**How to tell it worked:** A/B within a day: alternate rounds with and without
examples on the same kinds of items (the ledger records which), compare
kept-rate.

---

## 7. An item linter, and duplicate detection

**Gain:** medium--high: bad items waste whole rounds. **Effort:** S.

### Why

Rounds start from the item. On 2026-09-24 some rejections were for "work an
earlier round had already done"; earlier logs showed a whole turn spent on an
item no round could act on. A deterministic check of every new item, at the
moment it is written, costs nothing.

### What to build

At the end of each refill (and after a split round), lint every new open item:

| rule | action |
|---|---|
| names at least one backticked symbol that exists, or a file that exists or is new and named | else: rewrite request |
| ends with `Done when:` | else: rewrite request |
| under ~60 words | else: split request |
| one verb phrase (no "and ... and", no list) | else: split request |
| not a near-duplicate (difflib ratio > 0.85) of an open or done item | drop it |
| does not name a held-out exercise | drop it (see proposal 3) |

"Rewrite request" is cheap: batch all failing items into one short prompt to
`ask_model`, "rewrite each of these items to follow the rules; one per line",
and replace them in the task list. If the rewrite still fails the rules, drop
the item and record why.

```python
# ralph_items.py
import difflib


def lint_item(item, files, known_items):
    problems = []
    names = SYMBOL.findall(item)
    exists = defined_names(files) | {os.path.basename(f) for f in files}
    if not any(n.split(".")[0] in exists or n.endswith(".py") for n in names):
        problems.append("names nothing that exists")
    if "Done when:" not in item:
        problems.append("no Done when")
    if len(item.split()) > 60:
        problems.append("too long")
    for other in known_items:
        if difflib.SequenceMatcher(None, item.lower(), other.lower()).ratio() > 0.85:
            return ["duplicate of: %s" % other[:80]]
    return problems
```

**How to tell it worked:** ledger share of rounds on items that end parked
should fall; "already done" rejections should go to zero.

---

## 8. Type checking as a free check

**Gain:** medium--high. **Effort:** S--M.

### Why

pyflakes catches undefined names; it cannot see `result.refused` on an object
that has no such attribute, a `None` passed where a string is needed, or a
method called on the wrong class. These are the errors small models make when
they edit one function without seeing the class. A type checker catches many
of them without running anything, and the loop can treat it like the lint
check: only what the round *added* counts.

### What to build

Add `mypy` to `requirements.txt` (it runs offline, pure Python wheels exist
for Windows), and in `ralph_scan.py`:

```python
MYPY_ARGS = ["--ignore-missing-imports", "--no-error-summary", "--hide-error-context",
             "--follow-imports=silent", "--check-untyped-defs", "--no-color-output",
             "--cache-dir", ".localcoder-mypy"]
SERIOUS_TYPE = ('has no attribute', 'Too many arguments', 'Missing positional argument',
                'Unexpected keyword argument', 'is not callable', 'Name "')


def types(files, python=None):
    """{'file: message'} from mypy, without line numbers. None if mypy is missing."""
    py = [f for f in files if f.endswith(".py") and os.path.isfile(f)]
    if not py:
        return set()
    try:
        proc = subprocess.run([python or sys.executable, "-m", "mypy"] + MYPY_ARGS + py,
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "No module named mypy" in proc.stderr:
        return None
    found = set()
    for line in proc.stdout.splitlines():
        m = re.match(r"(.+?):\d+: (error|note): (.+)$", line)
        if m and m.group(2) == "error":
            found.add("%s: %s" % (os.path.basename(m.group(1)), m.group(3)))
    return found
```

In `baseline()` add `"types": types(files)`, and in `scan()` compare as for
lint: a new message containing one of `SERIOUS_TYPE` rejects, other new ones
warn.

`--check-untyped-defs` matters: without type hints mypy checks almost nothing;
with it, attribute and call errors inside unannotated functions are reported.
The project has few annotations, so expect little noise from the baseline, and
the baseline subtracts what noise there is.

**Cost:** mypy's first run on 30 modules takes several seconds; its cache
(`.localcoder-mypy`, gitignored) makes later runs fast.

**How to tell it worked:** ledger count of rounds caught by "types:" findings;
and fewer "LocalCoder hit an unexpected error: AttributeError" lines in field
reports.

---

## 9. Failures explained with values, not just messages

**Gain:** medium. **Effort:** S.

### Why

When a round breaks the tests, the next round is told "tests fail:
test_x ... AssertionError". Self-Debugging (Chen et al., 2023) showed that
models fix code far better when they are shown what the code *did*: a trace,
or the values involved, not only the error. The data is free: the test runner
can print the local variables at the failing frame.

### What to build

Run the failing test once more, alone, under a tiny runner that prints the
frame's locals at the point of failure, trimmed, and put that in the "FIRST,
AND ONLY THIS" block of the next round's prompt.

`traceback.TracebackException(..., capture_locals=True)` formats the `repr`
of every local in every frame. A test result class that keeps that text for
the first failure, and a runner around it, is all it takes:

```python
# ralph_explain.py -- run as: python -m ralph_explain test_mod.Class.test_name
"""Run one failing test and print the values at the point it failed."""

import sys
import traceback
import unittest


class LocalsResult(unittest.TestResult):
    explained = ""

    def _explain(self, err):
        if not self.explained:
            tbe = traceback.TracebackException(*err, capture_locals=True, limit=-3)
            self.explained = "".join(tbe.format())[-2500:]

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._explain(err)

    def addError(self, test, err):
        super().addError(test, err)
        self._explain(err)


def main(test_id):
    result = LocalsResult()
    unittest.defaultTestLoader.loadTestsFromName(test_id).run(result)
    print(result.explained or "passed")
    return 1 if result.explained else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
```

`limit=-3` keeps the three innermost frames, which is where the values that
matter are; `[-2500:]` keeps it under a thousand tokens.

Use it in two places: when `full_check` reports a failing test (the repair
round gets the values), and in aider's in-round test feedback, by pointing
`--test-cmd` at a wrapper that prints the explained failure after unittest's
own output.

**How to tell it worked:** ledger: rounds after a broken round that end with
the code running again, before and after.

---

## 10. Choose the model by measurement

**Gain:** medium--high, once; then whenever a new model appears. **Effort:** M.
**Depends on:** 3 (the held-out suite).

### Why

The model is the single biggest factor in every number above, and the choice
was made by hand. For a 24 GB card in 2026 the commonly recommended coding
models include Qwen 3.x 27B, Devstral Small 2 (24B, built for agentic
multi-file work), and Qwen2.5-Coder 32B, and new ones appear monthly. Which is
best *in this loop, with these prompts* is a question the practice suite can
answer.

### What to build

`orthros.py --tournament <model key> <model key> ...` (keys as `lms ls` prints them):
for each model key (all already downloaded in LM Studio), run the held-out
suite with the *current proven agent*, the same turn length and the same
settings, and print a table: solved, rounds, kept-rate, tokens per second,
false-rejection rate (from the ledger). Takes a night for three models.

The same machinery measures settings: the same model with the reviewer on and
off, with two review passes and one, with Q8 and F16 KV cache. Every "should
we?" in `config.cmd` becomes a number.

**How to tell it worked:** it is itself the measurement. Change the default
model only on a clear win.

---

## 11. Faster tokens: draft models and prompt-cache order

**Gain:** medium (speed; roughly 1.3--2x on generation). **Effort:** S.
**Measure first.**

### Speculative decoding with a draft model

A small model from the same family proposes several tokens; the large model
checks them in one pass and keeps the ones it agrees with. The output is
unchanged by construction; only speed changes. LM Studio supports draft models
for its llama.cpp engine. Published measurements on coding tasks, with a
Qwen2.5-14B target, show up to 2.5x with a 0.5B draft and up to 1.63x with a
1.5B draft; code is predictable, which is why it gains most. A 27B target
should gain at least as much, since each of its passes costs more. The agent's `load_model_now` already handles an MTP
head (`LC_SPECULATIVE`); a separate draft model is the other kind.

Plan:

1. In LM Studio, set the draft model in the main model's defaults (same family,
   0.5--1.5B) and check it loads alongside with VRAM to spare.
2. Run `bench_parallel.py` (one slot) with and without it; compare tokens per
   second on a real round prompt.
3. Keep it if faster by more than 15% and the ledger shows no rise in lost
   rounds (memory pressure).

### Prompt-cache order

llama.cpp keeps the KV cache of the last request and reuses the longest common
**prefix**. Every round re-sends the same system prompt, repo map, read-only
files and, mostly, the same task list; if these come first and in the same
order, only the tail is recomputed. If something that changes each round
(lessons, "the last round was cut off", the reviewer's note) comes *early*,
everything after it is recomputed: seconds of prompt processing on a 20k-token
prompt.

aider's own order is fixed (system, repo map, read-only files, chat files,
messages); what OrthrosCode controls is what goes into each:

- keep **SKILLS.md, CONVENTIONS.md, DESIGN.md** in the read-only set, in a
  fixed order, every round (stable prefix);
- move **lessons and warnings** from the top of the round prompt into the user
  message (the round-prompt file already goes last), which it already is --
  check that `compose_round_prompt` does not also write them into a read-only
  file;
- sort `--read` and `--file` arguments deterministically (they are built from
  lists whose order can vary with filesystem listing).

**How to tell it worked:** the LM Studio server log prints prompt-processing
time per request; the ledger's seconds-per-round should fall at equal tokens.

---

## 12. Edit format chosen per file

**Gain:** medium (fewer rounds lost to edits that do not apply). **Effort:** S.
**Depends on:** 0.

### Why

The loop switches the whole session to whole-file edits after two misses
(`maybe_switch_to_whole_files`). But misses depend on the *file*: SEARCH/REPLACE
blocks fail more on long files with repeated patterns, and whole-file output
costs little on short ones. Aider's own benchmarks found whole-file the most
reliable format for weaker models and diff the most efficient for strong ones.

### What to build

Per round, choose by the files being sent:

- all files under ~250 lines: `--edit-format whole`;
- any file over that: `--edit-format diff`;
- a file where the ledger shows two misses this week: whole if under 600 lines,
  else ask for a split of that file (the mechanical splitter, `split.py`,
  already exists).

```python
def edit_format_for(files, misses):
    sizes = [read_text(f).count("\n") for f in files if f.endswith(".py")]
    if sizes and max(sizes) <= 250:
        return "whole"
    if any(misses.get(os.path.basename(f), 0) >= 2 and read_text(f).count("\n") <= 600
           for f in files):
        return "whole"
    return "diff"
```

Pass it per round through `build_round_command` (replace the value after
`--edit-format`).

**How to tell it worked:** ledger share of rounds with `failed > 0 and applied
= 0`.

---

## 13. Coverage- and mutation-guided work

**Gain:** medium: better tests, which every other check relies on.
**Effort:** M.

### Why

The tests are the gate for everything, so weak tests let bad changes through.
Coverage shows code no test runs; mutation testing shows code whose tests would
not notice a change (Meta's mutation-guided test generation had engineers
accept 73% of the generated tests). Both turn "write better tests" into
specific, checkable items.

### What to build

1. **Coverage, weekly or per refill.** `coverage` is a small pure-Python
   package; run the suite under it and list functions with zero coverage.
   Each becomes an item: "In `test_<module>.py`, add a test that calls
   `<function>` ... Done when: coverage shows `<function>` run."
2. **Mutation, sampled.** Running mutmut on everything is slow; running it on
   the functions changed in the last day is not. For each surviving mutant,
   an item: "The tests pass when `<line>` is changed to `<mutant>`. Add a test
   that fails for that change."

```python
# orthros_work.py -- untested functions, standard library + coverage
def untested(folder, python):
    subprocess.run([python, "-m", "coverage", "run", "--branch", "-m", "unittest",
                    "discover", "-s", ".", "-p", "test_*.py"], cwd=folder,
                   capture_output=True, timeout=900)
    report = os.path.join(folder, ".localcoder-coverage.json")
    subprocess.run([python, "-m", "coverage", "json", "-o", report], cwd=folder,
                   capture_output=True, timeout=120)
    data = read_json(report, {})
    missing = []
    for path, info in (data.get("files") or {}).items():
        for name, fn in (info.get("functions") or {}).items():
            if fn["summary"]["covered_lines"] == 0 and name:
                missing.append((os.path.basename(path), name))
    return missing
```

(Per-function data needs coverage 7.5+; otherwise map missing line numbers to
functions with `ast`.)

Put the items into the task list with `add_items(..., "Found by measuring the
tests")`, a handful at a time, only in self mode or when a task has a test
suite.

**How to tell it worked:** coverage percentage over time; mutation score on
the sampled functions.

---

## 14. Find the change that broke it: automatic bisect

**Gain:** medium, in self mode. **Effort:** M. **Depends on:** 3.

### Why

When a proven agent's practice score drops, or its field report shows a new
kind of error, the cause is one of the change sets carried into it since the
last good score. Today the whole turn's changes are rolled back, good ones
with the bad. `git bisect` finds the one commit, and time is free.

### What to build

When a held-out evaluation (proposal 3) fails the "not worse" test, run a
bisect over the commits between the parent and the child, using a *short*
evaluation (the three exercises that flipped from pass to fail) as the test at
each step. Revert only the commit it finds; re-evaluate; prove if the score is
back.

```python
def bisect(folder, good, bad, test):
    """The first bad commit between good and bad, using test(sha) -> bool (True = good)."""
    shas = git_lines(folder, "rev-list", "--reverse", "%s..%s" % (good, bad))
    lo, hi = 0, len(shas) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if test(shas[mid]):
            lo = mid + 1
        else:
            hi = mid
    return shas[lo]
```

`test(sha)` checks out `sha` into a worktree of the agent (never its live
folder), runs the flipped exercises with it, and returns whether they pass.

**How to tell it worked:** rollbacks become reverts of single commits; the
amount of good work kept after a regression rises.

---

## 15. Contain the code the agents run

**Gain:** safety and resilience, medium. **Effort:** M.

### Why

The loop never runs a command the *model* suggests (aider's shell commands are
off), but it does run the code the model *writes*: every test run, every
import check and every smoke run executes it, with the operator's user
account, full file access and network. A mistaken `shutil.rmtree` in a test's
tear-down, or a loop that allocates without end, runs with the same power as
anything else on the machine. The README's statement that the loop never runs
model-written code should be narrowed to "never runs commands the model
suggests" until this is done.

### What to build, in increasing strength

1. **A Job Object per check run** (Windows): the agent's supervisor already
   creates one for itself (`install_job_object`). Give test and smoke runs their
   own, with a memory limit (e.g. 4 GB), a process-count limit, and
   kill-on-close, so a runaway test cannot take the machine's memory, which is
   exactly the resource this setup is short of.

   ```python
   # supervisor_win.py
   JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
   JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
   JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


   def limited_job(memory_mb=4096, processes=16):
       job = kernel32.CreateJobObjectW(None, None)
       info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
       info.BasicLimitInformation.LimitFlags = (JOB_OBJECT_LIMIT_PROCESS_MEMORY
                                                | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                                                | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
       info.BasicLimitInformation.ActiveProcessLimit = processes
       info.ProcessMemoryLimit = memory_mb * 1024 * 1024
       kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
       return job
   ```

   and in `ralph_checks.smoke_run`/`test_check`, start the child suspended,
   assign it to the job, resume it (or, simpler, start it and assign it
   immediately; Python's `subprocess` on Windows gives the handle as
   `proc._handle`).

2. **No network for check runs.** A Windows Firewall outbound block rule for a
   *copy* of the interpreter used only for checks
   (`venv\Scripts\python-checks.exe`): aider and research keep network access,
   code under test does not. One `netsh advfirewall firewall add rule` at
   setup, run once by the operator as administrator.

3. **A throwaway copy for checks**: run tests in a git worktree of the
   workspace, so a test that deletes files deletes them in the copy.

**How to tell it worked:** a deliberately bad test (allocate 20 GB; delete the
parent folder; open a socket) is contained in each case.

---

## 16. Task mode: acceptance the operator owns

**Gain:** high for task mode. **Effort:** S--M. **Depends on:** 1 (same
machinery).

### Why

In task mode the only definition of done is the operator's description, read
by the agents. Two small additions give it teeth:

1. **Acceptance tests from the operator.** A folder `tasks\<name>\acceptance\`
   the agents cannot see (keep it outside the task folder: `tasks\<name>.accept\`),
   holding the operator's own tests, run after every turn exactly like practice's
   hidden tests. The dashboard shows "acceptance: 7 of 12" for the task.
2. **Acceptance examples in the description.** The *New task* form gets a
   second box, "Examples of it working" (input, expected output). Orthros turns
   each into a test file in the hidden folder with a tiny template, and into
   one visible `Done when:` item, so the agents build to them and the operator
   has an objective score.

```python
EXAMPLE_TEST = '''import subprocess, sys, unittest


class TestExample{n}(unittest.TestCase):
    def test_example(self):
        proc = subprocess.run([sys.executable, {entry!r}] + {args!r}, input={stdin!r},
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.stdout.strip(), {expected!r})
'''
```

The task's field report line becomes "acceptance 7/12 (+2 this turn)", and a
task is *finished* when acceptance is complete and the agents' own list is
empty: Orthros then pauses with a clear message instead of letting the agents
invent more work.

**How to tell it worked:** it is the measurement for task mode.

---

## 17. Smaller wins

Each is small; together they matter.

- **Orthros restart on crash (opt-in).** Windows can kill Orthros under memory
  pressure. A scheduled task that runs `ORTHROS.bat --resume` at log-on, and a
  `--resume` flag that starts without pressing Start only if the last state
  was running, would let an overnight run survive. Keep it off by default: an
  unattended restart is a decision for the operator.
- **Clock-based turn end on empty work.** When a turn's list is empty and two
  refills in a row add nothing, end the turn and hand over, rather than idle
  until the clock. The twin gets the card sooner.
- **Session summary for the next session** (a planned milestone in the
  templates): three lines -- done, failed, next -- written at the end of a
  session and read first by the next planning round.
- **`FOUND.md` answers indexed by request.** Keep each request's answer under
  its own heading across rounds (instead of rewriting the file each time),
  capped by age, so an answer asked for in round 3 is still there in round 5.
- **Reviewer's reasons into the next attempt verbatim.** Already written under
  the item; also put the *surviving cited fault* (proposal 2) as the first line
  of the next round's prompt.
- **Deterministic `--read` order** (proposal 11) also stabilises what the
  model sees, which makes the ledger's comparisons fairer.
- **Stale branches of thought.** `PLAN.md` milestones that have been
  decomposed three times without an item ticked should be parked the way items
  are.
- **Tokens per kept change** on the dashboard: the one number that combines
  speed and quality.
- **A `--doctor` command**: checks Python versions, `lms`, LM Studio's model
  defaults (context, Flash Attention, KV type) through `lms ls --json` where it
  reports them, page-file size, free disk, and the venv layering, and prints
  what to fix. Most of the setup trouble so far (the Python 3.14 venv, the
  page file) would have been one line of its output.

---

## Considered and left out

These were weighed and not planned: the effort is very high and the payoff
small or doubtful on one 24 GB card.

| Idea | Why not |
|---|---|
| Fine-tuning the model on its own kept diffs (LoRA) | Training a 27B model's adapters needs far more memory than inference; a smaller model trained locally would likely lose more than it learned. Retrieval (proposal 6) gets much of the benefit with no training. |
| Full Darwin Gödel Machine-style open-ended archive search with many agents in parallel | Published runs took about two weeks of API compute per experiment. Proposal 3 keeps the part that fits one card: the benchmark gate and a small archive. |
| Recursive Language Models (model writes code over its input, in a REPL) | Runs model-written code as the core mechanism; `DIGEST:` covers the long-input case without it. |
| Embedding-based retrieval with a second model | A second model on the card competes for memory with the main one; BM25 over short technical text is close enough (proposal 6). |
| Running SWE-bench locally as the fitness function | Needs Docker images per repository and hours per instance on local hardware; small held-out exercises measure the same abilities at a fraction of the cost. |
| Switching the engine to vLLM | Faster batching, but no native Windows support; LM Studio's llama.cpp engine with parallel slots (proposal 4) captures most of the gain here. |
| Porting to Linux | Worth doing for others, but no gain on this machine. |
| A web-based multi-user dashboard | One operator, one machine. |

---

## A suggested order of work

A sequence that gets the measured gains first, and makes each later step
measurable by an earlier one:

1. **Week 1:** proposal 0 (ledger), proposal 2 (cited, structured verdicts),
   proposal 7 (item linter), proposal 9 (values in failures). All S, all
   immediately measurable, and together they should remove most of the false
   rejections.
2. **Week 2:** proposal 1 (test first). The biggest single change in how work
   is judged. Proposal 5 (escalation ladder) alongside it.
3. **Week 3:** proposal 3 (held-out suite, proof by score, archive). From here
   *Improve itself* optimises something real. Proposal 16 (task acceptance)
   reuses its machinery.
4. **Then, by measurement:** proposal 4 (two candidates) if the benchmark says
   memory allows; proposal 11 (draft model); proposal 10 (tournament) when a
   promising new model appears; proposals 6, 8, 12, 13, 14, 15 in whatever
   order the ledger says rounds are being lost.

Each of these can be given to the agents themselves as items: the proposals
are written to that grain. But proposals 0--3 change how the agents are
*judged*, and belong outside their reach, in Orthros.

---

## Sources

Research:

- Zhang, Hu, Lu, Lange, Clune. *Darwin Gödel Machine: Open-Ended Evolution of
  Self-Improving Agents* (2025). <https://arxiv.org/abs/2505.22954>,
  <https://sakana.ai/dgm/>, <https://github.com/jennyzzt/dgm>
- Robeyns et al. *A Self-Improving Coding Agent* (2025).
  <https://arxiv.org/abs/2504.15228>,
  <https://github.com/MaximeRobeyns/self_improving_coding_agent>
- Brown et al. *Large Language Monkeys: Scaling Inference Compute with Repeated
  Sampling* (2024). <https://arxiv.org/abs/2407.21787>
- Ridnik et al. *Code Generation with AlphaCodium: From Prompt Engineering to
  Flow Engineering* (2024). <https://arxiv.org/abs/2401.08500>
- Chen et al. *CodeT: Code Generation with Generated Tests* (2022).
  <https://www.semanticscholar.org/paper/CodeT%3A-Code-Generation-with-Generated-Tests-Chen-Zhang/876eb375cb7b365475040046df669c039ad54202>
- Shi et al. *Natural Language to Code Translation with Execution* (MBR-exec,
  2022). <https://arxiv.org/pdf/2204.11454>
- Chen, Lin, Schärli, Zhou. *Teaching Large Language Models to Self-Debug*
  (2023). <https://arxiv.org/abs/2304.05128>
- Yang et al. *SWE-agent: Agent-Computer Interfaces Enable Automated Software
  Engineering* (2024). <https://arxiv.org/abs/2405.15793>
- Xia et al. *Agentless: Demystifying LLM-based Software Engineering Agents*
  (2024). <https://github.com/openautocoder/agentless>
- Zhao et al. *ExpeL* and Wang et al. *Agent Workflow Memory*, surveyed in
  <https://arxiv.org/html/2604.27003v1> and
  <https://medium.com/@techsachin/agent-workflow-memory-using-workflows-to-guide-llm-agent-generations-aad75fe2f78a>
- *LLM-as-a-Judge Is Not an Oracle: Why Self-Improving Agents Need
  Deterministic Guardrails* (2026). <https://arxiv.org/pdf/2609.02246>
- Pairwise versus absolute judging:
  <https://www.langchain.com/resources/llm-as-a-judge>,
  <https://dev.to/loopandretry/your-llm-as-judge-is-lying-to-you-gg9>
- Mutation-guided test generation at Meta.
  <https://engineering.fb.com/2025/09/30/security/llms-are-the-key-to-mutation-testing-and-better-compliance/>

Tools and engines:

- Aider edit formats and benchmarks. <https://aider.chat/docs/more/edit-formats.html>,
  <https://aider.chat/docs/benchmarks.html>
- Aider architect/editor mode. <https://aider.chat/2024/09/26/architect.html>
- Aider polyglot benchmark (Exercism exercises).
  <https://github.com/Aider-AI/polyglot-benchmark>,
  <https://aider.chat/2024/12/21/polyglot.html>
- LM Studio structured output. <https://lmstudio.ai/docs/developer/openai-compat/structured-output>
- LM Studio speculative decoding. <https://lmstudio.ai/docs/app/advanced/speculative-decoding>,
  <https://lmstudio.ai/blog/lmstudio-v0.3.10>
- llama.cpp server: parallel slots, continuous batching, prompt cache.
  <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>,
  <https://github.com/ggml-org/llama.cpp/discussions/4130>,
  <https://github.com/ggml-org/llama.cpp/discussions/8947>
- Local coding models on 24 GB.
  <https://localllm.in/blog/best-local-llms-24gb-vram>,
  <https://www.kunalganglani.com/blog/best-local-model-agentic-coding>
- Windows Job Objects for sandboxing.
  <https://learn.microsoft.com/en-us/archive/blogs/david_leblanc/practical-windows-sandboxing-part-2>
