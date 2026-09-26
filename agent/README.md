# OrthrosCode agent

A local, autonomous coding agent: [aider](https://aider.chat) driven by an
unattended loop, on a model served by LM Studio. All inference is local.

This folder is one of a pair. Under Orthros (`..\ORTHROS.bat`) each agent works on
the other's source in turns, so this code is written by its twin and proven by
running. It also works on its own, pointed at any project.

## Running it

| | |
|---|---|
| `SETUP.bat` | builds `venv\` -- a thin layer over `..\shared-venv` when that exists, so installs here stay here |
| `LAUNCH.bat` | menu: chat, one item, work the list for N minutes, dashboard |
| `GUI.bat` | this agent's own dashboard (Orthros has its own at the root) |
| `STOP.bat` | unloads the model and stops LM Studio's server |
| `SELFTEST.bat` | checks the chain end to end without opening anything |
| `LIST_MODELS.bat` | model keys for `config.cmd` |

Every setting lives in `config.cmd`, with the reasons next to it.
`LC_WORKSPACE` is the folder it works on -- the other agent, under Orthros.

## Asking for things mid-task

A round cannot call tools while it answers, so it writes a request into the
task list and stops; the loop answers before the next round:

    RESEARCH: <question>   web search and fetch                  -> RESEARCH.md
    FIND: <text>           every matching line in the code        -> FOUND.md
    CALLERS: <function>    every line that calls it               -> FOUND.md
    DEF: <name>            where a function or class is defined   -> FOUND.md
    OUTLINE: <file>        every class and def line in it         -> FOUND.md
    DOCS: <module>         an installed library's own docs        -> FOUND.md
    DIGEST: <file> -- <question>   a file too big to send, in parts -> FOUND.md
    TESTS: <test_file>     one test file run on its own           -> FOUND.md

The list is `REQUESTS` in `ralph_tools.py`; each round's prompt gets every
request on it that `RALPH_PROMPT.md` does not already mention.

## How a session works

One round is one aider process: read the task list, do the first unticked
item, check it, tick it, exit. The task list in the working folder is the
memory; the model starts every round with an empty head.

After each round the change is parsed, linted, imported and tested, and read
by a second, independent request that keeps or rejects it -- shown the diff,
what the checks have already settled, and the code the item names as it now
stands. A round that breaks start-up or
is rejected is rolled back, and the reason is written under the item. Kept
rounds are committed. When the list runs dry it plans milestones, breaks them
into items, and checks earlier work -- until the clock runs out.

Every ten minutes a checkpoint looks up. Changes sent back and items parked
are the loop working through a hard list, and it carries on; only rounds
that produce nothing at all stop it early.

## The code

| file | what it does |
|---|---|
| `supervisor.py` | entry point: start-up order, shutdown, `main()` |
| `supervisor_env.py` | settings from `config.cmd`, console helpers |
| `supervisor_win.py` | the Windows job object; finding and running `lms.exe` |
| `supervisor_engine.py` | LM Studio's engine: load, probe, revive, watch the card |
| `supervisor_git.py` | the working folder's git history -- the undo button |
| `supervisor_aider.py` | aider's settings and command line, linter, tests, reviewer |
| `ralph.py` | the loop's entry point and what other modules import |
| `ralph_session.py` | the loop itself, with `ralph_setup`, `ralph_refill`, `ralph_outcome`, `ralph_report` |
| `ralph_rounds.py` | one aider round, research, the diff the reviewer sees |
| `ralph_send.py` | what one round is sent: its files, its reading, the numbers it came back with |
| `ralph_locate.py` | asks which files an item needs when it names none (after Agentless) |
| `ralph_gists.py` | GISTS.md: every module in a few lines, for planning (after ReadAgent) |
| `ralph_scan.py` | after each round, checks that cost no tokens: project-wide lint and call signatures, placeholders, conflict markers, lost tests; a test file's `if __name__ == "__main__":` block put back at its end |
| `ralph_testfirst.py` | test first, then code: an item whose `Done when:` a test could check gets a round that writes only that test, which must fail; code rounds then make it pass, and the test enters the history only with them. Off with `set "LC_RALPH_TEST_FIRST=0"` |
| `ralph_memory.py` | how similar items were done here: BM25 over past kept rounds (each commit names its item), the closest one or two shown with their diffs. Off with `set "LC_RALPH_EXAMPLES=0"` |
| `ralph_ladder.py` | each try at a failing item made differently: whole-file edits after a miss, architect mode after a break or no change, a split after two failures. Off with `set "LC_RALPH_LADDER=0"` |
| `ralph_explain.py` | a failing test run again alone, with the values at the failure, for the next round |
| `ralph_ledger.py` | one row per round in SQLite -- item, tokens, checks, verdict, kept -- so "where do rounds go?" is a query, not an afternoon of reading logs |
| `ralph_digest.py` | `DIGEST:` reads a file too big for a round in parts (after Chain-of-Agents) |
| `ralph_prompts.py` | everything the model is told |
| `ralph_tasks.py` | task list, plan (`PLAN.md`), progress ledger (`PROGRESS.md`) |
| `ralph_checks.py` | parse, import, start, and keep files small enough for a round |
| `ralph_inventions.py` | attributes the code reads that nothing creates |
| `ralph_tools.py` | the requests a round can make (`REQUESTS`); `LESSONS.md` |
| `research.py` | web search and page fetch, answers `RESEARCH:` lines |
| `split.py` | mechanical refactoring: moves a class or method into its own module |
| `status.py` | the status file the dashboards read |
| `gui.py`, `gui.html` | this agent's dashboard |
| `bench_parallel.py` | measures whether two workers on one card beat one |
| `test_*.py` | the unittest suite: run after every edit, every round, and before launch |
| `test_stop_paths.py` | reads the loop's source: every way a session can end must say why |
| `SKILLS.md` | how common changes are done here; sent with every round |
| `orthros_shared.pth` | layers this agent's venv over `..\shared-venv` |

Every file is kept small enough for one round of the model to read whole
(about 9,000 tokens). New work goes in new modules.

## Files it writes in the folder it works on

`RALPH_PROMPT.md` (the standing prompt), the task list, `PLAN.md`,
`PROGRESS.md`, `DONE.md`, `BRIEF.md`, `LESSONS.md`, `RESEARCH.md`, `FOUND.md`
-- all belonging to the agent doing the work. Orthros adds `FIELD_REPORT.md`. Runtime files (`.localcoder-*`, `.aider*`) are ignored
by git: `.localcoder-ralph.log` is the session summary and
`.localcoder-aider.log` is aider's output, verbatim.
