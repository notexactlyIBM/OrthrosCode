# OrthrosCode for an AI working on it

A referee (`orthros.py`, stdlib only) runs two self-rewriting coding agents,
A and B, on one GPU through LM Studio. Read this first. Ask before breaking a
rule below. Most bugs here so far came from breaking one without noticing.

## The map

| Path | What it is |
|---|---|
| `orthros.py` | The referee: the loop, turns, judging, rollback, proof by score, the dashboard server (127.0.0.1:8770), chat, housekeeping, `--doctor`, `--fresh`, `--export`. |
| `orthros_work.py` | What a turn works on: tasks (`tasks\`), tools (`tools\`), practice and held-out exercises, running the model's code (`contained_run`, `check_env`), tasks on existing repos (git worktrees). |
| `orthros_service.py` | Serve mode: the LAN listener (8777, key required), the OpenAI `/v1` pass-through to LM Studio, MCP `/mcp`, tool builds, the request log and its labels. |
| `orthros_tune.py` | Fits context and timeouts to the machine (`hardware.json`). |
| `orthros_setup.py` | Used by `SETUP.bat`: the venv, and the agents built from `agent\`. |
| `orthros_gui.py` | The dashboard window (tkinter), opened by `orthros.py`. A client of the same local API as the page, run as its own process; change the two together. |
| `orthros.html` | The dashboard as a web page: one file, no build, re-read on every page load. |
| `agent\` | The **template** for an agent (`supervisor.py`, `ralph_*.py`). This is not the code that runs. |
| `OrthrosCode A\`, `B\` | The **running** agents. Each is its own git repo, rewritten by the other, and gitignored here. |
| `tests\` | Orthros's tests (unittest, no GPU). `agent\test_*.py` are the agents' own tests. |

State: `orthros.json` holds settings and the serve key. `.orthros-state.json` holds the mode, turns, events and chat. `ledger.sqlite` has one row per round. `logs\` has the turn logs, and `orthros.log` the events. Per agent: `config.cmd` (model and context), `orthros_tasks.md` (its list, worked by its twin), `FIELD_REPORT.md`, `LESSONS.md` and `ROLLBACK.md`. All of this is gitignored.

## Rules that fail silently when broken

1. **`agent\` reaches A and B only through `ORTHROS.bat --fresh`.** The user runs it and types FRESH. Orthros must be closed, and the repo clean and pushed. After changing `agent\`, say so. `agents_behind()` flags stale agents in Housekeeping and `--doctor`.
2. **A running Orthros keeps its Python code in memory.** After changing `orthros*.py`, the user must restart it. `orthros.html` needs only F5; `orthros_gui.py` needs its window closed and `ORTHROS.bat` run again.
3. **The model's code never sees the harness.** Every run of it drops `ORTHROS_*` and `LC_*` by prefix: `check_env` here, `ralph_contain.without_harness` in the agents. A leaked `ORTHROS_LEDGER` makes the agents' ledger tests write into the real ledger and fail every round.
4. **Orthros never imports the agents' code**, because they rewrite it. It reads their files, or runs them as subprocesses inside limits.
5. **One card holds one model at a time.** Serving and turns never overlap. Anything loaded is unloaded before a turn. LM Studio stays on 127.0.0.1. The agents load as `localcoder`, serving as `orthros-serve`.
6. **This repo is public.** Nothing machine-, person- or other-project-specific goes in code, docs or commit messages: no host names, IPs, keys, or names of the user's private projects.
7. **Tests never touch live things**: no real ports (use 0, or mock `port_in_use`), no real ledger or state, no firewall prompts (`serve_host=127.0.0.1`).
8. **Python 3.14 runs Orthros** (`py -3`). Escape backslashes in strings and docstrings (`agent\\`). An invalid escape prints a warning on every start.

## How to work here

- One blunt rule per class of failure, not a patch per incident. Delete before adding. Fix and polish before new features.
- Docstrings say why, in plain words, dated when an incident taught the lesson.
- Tests: `python -m unittest discover -s tests` takes about 4 minutes; `tests.test_service` alone takes about 70 s. While the user is busy setting something up, run only what the change touches.
- `ORTHROS.bat --doctor` is a read-only check of the machine and both agents. `--simulate` runs fake agents and a fake engine, with the dashboard on 8771 and serving on 8778.
- Dashboard design: controls you can press are solid and coloured; status is flat; the key state is the loudest thing; no glow. See `agent\DESIGN.md`.
- Commit messages and the README are plain sentences saying why. Push when asked, to `main`.

## Deeper

- `README.md`: what it does and how to use it.
- `agent\README.md`: the agent itself.
- `docs\WORK-STOPPAGE.md`: why work stops, and what was done about it.
