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

    RESEARCH: <question>   web search and fetch            -> RESEARCH.md
    FIND: <text>           every matching line in the code  -> FOUND.md
    DOCS: <module>         an installed library's own docs  -> FOUND.md

## How a session works

One round is one aider process: read the task list, do the first unticked
item, check it, tick it, exit. The task list in the working folder is the
memory; the model starts every round with an empty head.

After each round the change is parsed, linted, imported and tested, and read
by a second, independent request that keeps or rejects it. A round that breaks start-up or
is rejected is rolled back, and the reason is written under the item. Kept
rounds are committed. When the list runs dry it plans milestones, breaks them
into items, and checks earlier work -- until the clock runs out.

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
| `ralph_scan.py` | after each round, checks that cost no tokens: project-wide lint and call signatures, placeholders, conflict markers, lost tests |
| `ralph_digest.py` | `DIGEST:` reads a file too big for a round in parts (after Chain-of-Agents) |
| `ralph_prompts.py` | everything the model is told |
| `ralph_tasks.py` | task list, plan (`PLAN.md`), progress ledger (`PROGRESS.md`) |
| `ralph_checks.py` | parse, import, start, and keep files small enough for a round |
| `ralph_inventions.py` | attributes the code reads that nothing creates |
| `ralph_tools.py` | `RESEARCH:`, `FIND:` and `DOCS:` requests; `LESSONS.md` |
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
