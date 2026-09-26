# OrthrosCode

**Two AI coding agents on one home PC that take turns improving each other --
and only keep the changes that make them measurably better.**

No cloud, no API keys, no accounts. One NVIDIA GPU, one open model, and a
referee called Orthros.

![Image](https://i.imgur.com/OtYb2lp.jpeg)

Orthros is the two-headed dog of Greek myth. Here the two heads are agents
**A** and **B**, sharing one graphics card, one at a time. Leave them alone and
A rewrites B's source code, then B wakes up running A's changes and rewrites A.
Give them a project instead and they take turns building it.

Every step is a git commit you can read.

## How it works

1. **One job per round.** An agent reads its task list, does the top item,
   and stops. The next round starts a fresh process with an empty head and
   reads the list again. This is the *Ralph loop*: state lives in files and
   git, not in the model's memory, so a small context window can work on a
   codebase far bigger than itself.
2. **Every change is checked before it is kept.** It must parse, lint, import,
   start and pass the tests. Then a separate, cold reviewer reads the diff,
   and must quote the exact line it objects to; the loop checks the quote and
   throws out objections that are false. Anything that fails is undone and the
   reason written down for the next try.
3. **Tests first, where possible.** If a job says `Done when: add(2, 2)
   returns 4`, one round writes only that test and the loop checks it fails.
   Later rounds must make it pass. The test is kept only together with the
   code that passes it.
4. **Failures change the approach.** A second try is not just a re-roll: an
   edit that did not apply is redone as a whole-file rewrite, a change that
   broke something is redone in plan-then-edit mode, and after two failures
   the job is split into smaller ones.
5. **Handover.** The model is unloaded, the card freed, and the other agent
   starts.
6. **Proof by score.** Working is not the same as better. Every few good
   turns, an agent's current version is scored on held-out coding exercises
   it has never seen. Its changes are copied into its twin only if the score
   is no worse than the last version that passed (and not far below the best
   ever). If it is worse, it is rolled back, and the twin that made the change
   is told the score.

That last step is what makes it self-improvement rather than drift. It is the
same idea at the centre of the published self-improving coding agents (the
Darwin Gödel Machine, SICA), cut down to fit one graphics card.

## What you need

- **Windows 10 or 11** (the launchers are Windows-only).
- **An NVIDIA GPU.** 24 GB runs the default model (27B parameters, 4-bit)
  with 64k of context. Smaller cards work with smaller models.
- **32 GB of RAM and a page file Windows can grow** -- see [Memory](#memory).
- **About 25 GB of disk.**
- **Python 3.10--3.12, Git and LM Studio.** All free.

## Setup

1. Install [Python 3.12](https://www.python.org/downloads/) (tick *Add to
   PATH*), [Git](https://git-scm.com/download/win) and
   [LM Studio](https://lmstudio.ai).
2. In LM Studio, download a coding model (default: `qwen/qwen3.8-27b`,
   Q4_K_M). In its default settings turn on **Flash Attention** and set the
   **K and V cache** to **Q8_0** -- this halves the memory the context takes.
3. Download this repository and run **`SETUP.bat`**. It installs aider once and
   creates the two agents, `OrthrosCode A\` and `OrthrosCode B\`.
4. Run **`ORTHROS.bat --doctor`**. It changes nothing and prints OK / WARN /
   FAIL for every check. Fix any FAIL.
5. Run **`ORTHROS.bat`**, pick a mode on the dashboard and press **Start**.

No GPU? `ORTHROS.bat --simulate` runs the whole thing with stand-in agents.

## Using it

The dashboard (http://127.0.0.1:8770) shows who is working and on what, the
model's raw output, GPU use, held-out scores, and where each agent's rounds
went in the last day. From it you can:

- switch between **Improve itself** and **Work on a task** (describe what to
  build; the agents break it into small checkable jobs);
- **Suggest direction** -- your words go to the top of an agent's list;
- **Ask** how it is going, in plain sentences from Orthros's own records;
- pause after this turn, stop after this round, or force stop.

When Orthros cannot go on, it stops, writes `ORTHROS-NEEDS-YOU.txt` saying why,
turns the page red and beeps.

| Command | What it does |
|---|---|
| `ORTHROS.bat` | start the referee and dashboard |
| `ORTHROS.bat --doctor` | check the machine and both agents; changes nothing |
| `ORTHROS.bat --resume` | restart after a crash -- only if it was running, never if you stopped it |
| `ORTHROS.bat --fresh` | rebuild both agents from `agent\` after an update (see below) |
| `ORTHROS.bat --export` | copy the newest proven agent into `agent\`, to keep what it learned |
| `ORTHROS.bat --simulate` | the same dashboard with fake agents, turns of seconds |

**Updating.** The two agents are separate git repositories that rewrite
themselves, so `git pull` updates Orthros and `agent\` -- the template -- but
not the agents built from it. To bring them up to date, close Orthros, then:

    git pull
    ORTHROS.bat --fresh

`--fresh` first checks that this folder matches GitHub exactly (nothing
uncommitted, unpushed or not yet pulled), then rebuilds both agents from
`agent\`, writes them new task lists, and starts Orthros's records again.
Each agent keeps its own `config.cmd`; its old state is kept as a git tag.
Want to keep what the agents taught themselves first? `ORTHROS.bat --export`,
commit and push, then pull and `--fresh`.

**What to read.** `FIELD_REPORT.md` in each agent folder: how it did, turn by
turn, with its scores. `LESSONS.md`: mistakes it keeps making. `git log` in any
folder: every change. `orthros.log`: what the referee did.

## Settings

`orthros.json`, written on first run. The ones worth knowing:

| Setting | Default | Meaning |
|---|---|---|
| `session_minutes` | 60 | length of a turn |
| `practice_every` | 4 | one turn in this many is a practice exercise (0 = off) |
| `prove_by_score` | true | changes spread only after a held-out score |
| `eval_every` | 4 | good turns between scorings of an agent |
| `eval_count`, `eval_minutes` | 8, 8 | exercises per scoring and minutes each (about 90 minutes in all) |
| `pause_after_idle` | 4 | stop after this many turns in a row that kept nothing |
| `auto_tune` | true | fit context size and timeouts to the machine from what each turn measures |

Each agent's own settings -- model, context, temperatures, tries per job --
are in its `config.cmd`, each with the reason beside it. The agent itself is
described in [agent/README.md](agent/README.md).

## Safety

- **Local only.** Every model call goes to LM Studio on your machine. The
  only outbound traffic is the agents' optional web search.
- **No shell.** aider may edit files but never runs a command the model
  suggests.
- **Contained code.** The model's code does run -- that is what tests are.
  On Windows every run is capped at 4 GB and 32 processes, and anything it
  leaves behind is killed.
- **Undo everything.** Every turn is committed first; every proven version is
  tagged; a bad change, even one copied into both agents, is stepped back
  past, as far as the original if need be.

## Memory

Windows has one limit for everything programs may use: physical memory plus
the page file. The graphics driver charges system memory to back what the
model puts on the card, so an 18 GB model needs about 18 GB of that limit too.
At the limit Windows starts killing things -- the engine says "bad
allocation", agents die mid-round, Orthros vanishes.

Fix it by letting Windows grow the page file (System > About > Advanced system
settings > Performance > Advanced > Virtual memory, on an SSD), closing
browsers during a run, or using a smaller model. Orthros will not start a turn
without room, and stops one early rather than be killed.

## Troubleshooting

- **Nothing happens.** Orthros always opens paused: press **Start**. The first
  minutes of a turn are silent -- tests before launch, then the model loading.
- **"bad allocation" / the engine keeps dying.** Memory -- see above.
- **"the card is shared".** Close other LM Studio windows, ollama, games.
- **It stopped with a message.** It says why; the turn's full output is in
  `logs\`.

## What it could do with unlimited resources

This is speculation. OrthrosCode is two agents on one card, scored on twelve
small exercises. The same loop, scaled:

- **Many heads, not two.** The Darwin Gödel Machine kept an archive of
  hundreds of agent versions and bred new ones from the best and the least
  explored, raising its benchmark score from 20% to 50%. With a data centre,
  every version could be scored in parallel, on thousands of real tasks
  instead of twelve toy ones, and the archive could branch freely instead of
  moving in a line.
- **Real software as the exam.** Scoring on full benchmarks built from real
  GitHub issues, run in containers, would make "better" mean better at the
  work people actually do -- and harder to game.
- **The model improves too.** Here only the scaffolding changes; the model is
  fixed. With training compute, every kept change is a worked example, and
  the agents could fine-tune their own model on their own verified successes.
- **Where it stops.** The loop improves exactly what the score measures. Its
  ceiling is the quality of the tests and the honesty of the referee -- which
  is why the referee here sits outside the agents' reach, and why the most
  important resource would be better exams, not more GPUs.

## Credits

OrthrosCode is a referee and a workflow around other people's work. Thank you
to all of them.

**Software it runs on**

- [aider](https://aider.chat) ([source](https://github.com/Aider-AI/aider), Apache 2.0) --
  the AI pair programmer that makes every edit. With it come its own open-source
  dependencies, among them [LiteLLM](https://github.com/BerriAI/litellm),
  [Streamlit](https://streamlit.io), the [OpenAI Python library](https://github.com/openai/openai-python)
  (used here only to talk to the local server) and [requests](https://requests.readthedocs.io).
- [LM Studio](https://lmstudio.ai) -- runs the model on the GPU and serves it
  locally (free, not open source), on the open-source engine
  [llama.cpp](https://github.com/ggml-org/llama.cpp) (MIT).
- The open-weight model you choose; the default is from the
  [Qwen](https://github.com/QwenLM) team. Check its license before use.
- [flake8](https://github.com/PyCQA/flake8) and [pyflakes](https://github.com/PyCQA/pyflakes)
  (MIT) -- the lint checks inside and after every round.
- [HTTPX](https://www.python-httpx.org) (BSD) and
  [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) (MIT) -- the
  agents' web research, which searches through [DuckDuckGo](https://duckduckgo.com).
- [Python](https://www.python.org) and its standard library (unittest, sqlite3,
  ast, difflib) -- Orthros itself uses nothing else -- and [Git](https://git-scm.com),
  which holds every version and every undo.
- [SQLite](https://sqlite.org), through Python's sqlite3 -- the round ledger.

**Ideas it is built from**

- **The Ralph loop** -- [Geoffrey Huntley](https://github.com/ghuntley/how-to-ralph-wiggum):
  the same prompt in a fresh process, state on disk, one job per loop, search
  before building, tests as backpressure.
- [fstandhartinger/ralph-wiggum](https://github.com/fstandhartinger/ralph-wiggum) --
  acceptance criteria on every item, and counting tries per item.
- Zhang, Hu, Lu, Lange, Clune, *Darwin Gödel Machine* (2025), and Robeyns et
  al., *SICA* (2025) -- self-improving agents gated by a benchmark score.
- Brown et al., *Large Language Monkeys* (2024) -- many tries plus a verifier.
- Chen et al., *Teaching Large Language Models to Self-Debug* (2023) -- showing
  the model the values at a failure.
- Zhao et al., *ExpeL* (2024) -- retrieving past successes as examples.
- Robertson and Zaragoza, BM25 -- how those examples are found.
- Xia et al., *Agentless* (2024) -- find the file before fixing it.
- Lee et al., *ReadAgent* (2024) -- gist memory of every module.
- Zhang et al., *Chain of Agents* (2024) -- reading a long file in parts.
- aider's own benchmarks -- architect mode and whole-file edits for weaker
  models.

The practice and held-out exercises were written for this repository.

Released under the [MIT license](LICENSE).
