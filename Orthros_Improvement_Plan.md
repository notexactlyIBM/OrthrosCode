# Orthros improvement plan

Reviewed 2026-10-27: `orthros.py`, `orthros_work.py`, `orthros_service.py`,
`orthros_tune.py`, `orthros_setup.py`, the guard, the window's polling, the
bear's timing, the tests, and the agent template's edges (its contract with
Orthros: the status file, the loop log, `config.cmd`, `requirements.txt`).

Read `CLAUDE.md` before taking an item. The rules there that bite here:
changes to `orthros*.py` need Orthros restarted; changes to `agent\` reach A
and B only through `ORTHROS.bat --fresh`; tests never touch live ports or the
real ledger; nothing machine- or person-specific goes into code, docs or
commit messages. Run only the test modules an item touches while the operator
is using the machine (`tests.test_orthros` is about two minutes, the whole
suite about four).

## Done in this review (needs an Orthros restart to take effect)

- **GPU readings in-process.** `gpu_reading` now asks NVML through `ctypes`
  (`nvml.dll`, installed by the driver) and falls back to `nvidia-smi` only
  when the library will not load or answer. Before, the page's GPU view
  started a process every two seconds for as long as Orthros ran.
- **The field report no longer counts the model's words.** When the loop had
  written no log for a turn, `field_report` fell back to counting its phrases
  in the turn's whole output, which is exactly the bug rule 10 in `CLAUDE.md`
  records. Now it counts nothing and says the loop wrote no log. Test added.
- **The page's version numbers cost no git processes.** `view()` ran
  `git rev-parse` twice per poll, and the window and the page each poll every
  two seconds. `Orthros.version()` asks git only when `.git/HEAD` or
  `.git/logs/HEAD` has changed.
- **A calmer bear.** It hides after ten quiet minutes, not two; fidgets every
  45 to 120 seconds, not every 12 to 25; and a salmon comes about once a day,
  not every few minutes. The body rule the model is given and the README say
  the same. The nose, the back and reacting to activity are items below.
- `tests.test_orthros`, `tests.test_bear`, `tests.test_tune`: 97 tests, all pass.

## The earlier six items, assessed

1. *Keep the model loaded (vLLM, LoRA adapters).* **Dropped.** LM Studio is
   the engine by design (`README.md`, rule 5). A and B are the same weights
   with different code, so there is nothing to hot-swap. A turn unloads once
   at handover, a few times an hour; in serve mode the model stays loaded.
   The one real cost is a tool build in serve mode (two loads per build turn),
   which is rare and accepted.
2. *NVML instead of spawning nvidia-smi.* **Done** (above). The probe in
   `orthros_tune.gpu()` still shells out once per look; see S7.
3. *Structured output instead of regex.* **Mostly not applicable.** The
   unittest lines parsed (`Ran N tests`, `FAILED (...)`) have been stable
   for a decade. The phrases matched in the loop's log and aider's output are
   the only interface an unmodified aider offers, and the guard
   (`orthros_guard\`) is already the structured hook. What is missing is a
   test that the phrases still exist: S1.
4. *State in SQLite, not Markdown.* **Dropped.** The task list is the prompt;
   files and git are what let a small window work a big codebase (the Ralph
   loop, `README.md`). The agents already keep the list short (`DONE.md`,
   `LESSONS.summary.md`), and rule 4 forbids Orthros depending on their code.
5. *Drop aider and the sitecustomize guard.* **Dropped.** The guard is
   deliberate and documented at the top of `orthros_guard\sitecustomize.py`,
   lives outside the agents so they cannot edit it away, and is wrapped so
   aider runs unguarded if its shape changes. Replacing aider is a rewrite of
   the agent, which is the thing under evolution, not a fix to Orthros.
6. *Autonomy for PAM.* **Not Orthros's.** PAM is a client of serve mode on
   another machine; Orthros's turn-taking is for A and B. Nothing to do here.

## Operator notes, and what the records say

- *"In serve mode the GPU is steady and low despite calls."* `orthros.log`
  shows two callers that hung up before an answer (after 9 s and 48 s) on
  2026-10-26 and otherwise long quiet stretches. The page records tokens and
  seconds per request but not the model's speed or how long each request
  waited, so it cannot tell "few short requests" from "slow answers". O1
  gives it those numbers. On the caller's side, a 31B model needs a timeout
  of minutes, not seconds.
- *Bear: hollow nose from the side; back flat and low on all fours; too much
  salmon and walking in and out; not reacting to activity.* Timing fixed
  above; the mesh is O3 and reacting to activity is O2.

## For Opus (design work, each one change with a test)

### O1. Serve mode shows the model's speed and the queue, per request
- **Where:** `orthros_service.py` (`forward`, `note`, `view`), `orthros.html`
  and `orthros_gui.py` (the recent-requests list; change both together,
  rule in `CLAUDE.md`'s map), `tests/test_service.py`.
- **Do:** in `forward`, read `usage.prompt_tokens` and `completion_tokens`
  from a whole answer; for a stream, count `data:` chunks with content as an
  estimate. Record per request: wait before its turn (`take_turn` to `go`),
  seconds answering, completion tokens per second. In `view`, add a
  "busy share" for the last hour: seconds a request was in flight over
  elapsed seconds. Show speed and wait in the request list and the share
  beside the counters.
- **Done when:** a request through `fake_engine` is listed with tokens,
  seconds and tok/s; a second request that waited behind it shows its wait;
  `tests.test_service` passes (about 70 s).

### O2. The bear reacts to Orthros, not to itself
- **Where:** `orthros_gui.py` (`render`), `orthros_bear.py` (a new
  `noticed(kind)` with a cooldown), `tests/test_bear.py`.
- **Do:** the window already receives `events` each poll. On a new event:
  kind `start` (a turn or serving begins) one `greet`; `good` (a turn kept
  work, a tool is ready, a carry-over) mood `proud`; `bad` mood `sad` or
  `surprised`; `handover` a `sniff`. One move per event, at most one a
  minute, none while the operator is typing or Orthros is answering, and the
  idle fidgets stay as calm as they are now. Nothing when the event is older
  than the last poll (restarts replay the list).
- **Done when:** a test feeds two polls whose events differ by one `good`
  event and sees one `proud` clip start, and a third poll with the same
  events starts nothing.

### O3. The bear's nose and back
- **Where:** `orthros_bear_mesh.py` (the snout's faces), `orthros_bear.py`
  (`build_skin`, the all-fours pose in `step`/`gait`), `tests/test_bear.py`.
- **Do:** close the snout: seen from the side it shows a hollow, so faces
  are missing between the muzzle's side edge and the nose. On all fours the
  spine sits level with or below the shoulders while the neck ruff stays
  wide, which reads as a mane; raise and arch the back (the `spine` and
  `chest` targets while walking) so the hump sits above the shoulder line,
  and narrow the ruff in the walking pose.
- **Done when:** the window's side view (double-click the GPU picture) shows
  a closed snout and a hump; `tests.test_bear` passes. Keep rule
  `agent\DESIGN.md` in mind: no glow, nothing touching an edge.

### O4. Skip the pre-launch test run when the code has not changed
- **Where:** `orthros.py` (`preflight`, `cleared_for_launch`, state),
  `tests/test_orthros.py` (`TestPreflight`).
- **Why:** `check_agent` runs an agent's whole suite before every turn,
  minutes each time, even when the agent is on a version that passed the same
  check an hour ago and nothing was carried in since.
- **Do:** after a passing check, remember the tree it passed on (the HEAD it
  was at plus a clean tree, notes excluded as `same_code` does). Skip the run
  when the tree is the same and the venv's `python.exe` mtime is unchanged;
  always run after a rollback, a carry-over, a `--fresh`, or on the first
  turn after Orthros starts. The import check stays every time (seconds).
  The agent must still be unable to switch the check off from inside its own
  code.
- **Done when:** a test runs `cleared_for_launch` twice on an unchanged agent
  and sees `check_agent` called once; a change to `agent.py` makes it run
  again.

### O5. One cheap `view()`
- **Where:** `orthros.py` (`view`), `orthros_service.py` (`tools`,
  `catalog`, `view`), `orthros_work.py` (`list_tasks`).
- **Why:** every poll (two clients, every two seconds) reads every task's
  and tool's `TASK.md`, `orthros_tasks.md` and `DONE.md`, the tools twice
  (`view` and `catalog`), `ralph_tools.py`, `config.cmd`, and lists the
  exercise folders.
- **Do:** one cache keyed on the folders' and files' mtimes, as `version()`
  now does for git, so an unchanged folder costs a few `stat` calls; call
  `tools()` once per view. Measure with a counter of file opens per poll
  before and after and put the two numbers in the commit message.
- **Done when:** the counter shows under ten file opens for a poll on an
  unchanged tree; `tests.test_orthros` and `tests.test_service` pass.

## For Sonnet (mechanical, one commit each)

### S1. A test that the phrases Orthros counts still exist in the agent
- **Where:** new `tests/test_phrases.py`.
- **Do:** for each `("loop", ...)` entry in `FIELD_SIGNS` and each phrase in
  `NORMAL_ENDS` and `ENV_SIGNS` that comes from the agent, assert the phrase
  occurs in some `agent\*.py` (not `test_*.py`). Skip the aider and LM Studio
  phrases. A rewording in `agent\` then fails a test here instead of silently
  zeroing a count in the field report.

### S2. One `find_lms`
- **Where:** `orthros.py` (`Orthros.find_lms`, `doctor`),
  `orthros_setup.py` (`find_lms`), `orthros_work.py`.
- **Do:** one function `find_lms(configured="")` in `orthros_work.py`
  (stdlib, imported by all three), with the full candidate list from
  `Orthros.find_lms`. `doctor` currently looks in only two places, so it can
  say "not found" for an lms that every turn finds.
- **Done when:** three call sites, one function; `tests.test_orthros`
  (`TestDoctor`) passes.

### S3. One copy of the small helpers
- **Where:** `orthros_tune.py` has its own `read_json`, `write_json` and a
  second `MEMORYSTATUSEX` in `ram_mb`; `orthros_work.git` and `orthros.git`
  differ only in timeout and return shape.
- **Do:** `orthros_tune` imports `read_json`/`write_json` from `orthros_work`
  (move them there) and reads total RAM through one `memory_status()` that
  `orthros.memory` also uses. Leave the two `git` functions unless one shape
  serves both callers cleanly.

### S4. `--doctor` names settings Orthros does not read
- **Where:** `orthros.py` (`doctor`), `tests/test_orthros.py` (`TestDoctor`).
- **Do:** WARN for every key in `orthros.json` that is not in `DEFAULTS`
  (this machine has two leftovers, `serve_queue` and
  `install_requirements`, that nothing reads). Also add the missing rows to
  the README's settings table: `evolve_lift_model`, `agaric_lift_evolve`,
  `tool_turns`, `tool_seconds`, `keep_logs`, `min_free_mb`,
  `critical_free_mb`.

### S5. State that cannot be saved is said once
- **Where:** `orthros.py` (`write_json`, `save`).
- **Do:** `write_json` returns False on `OSError`; `save` logs one event the
  first time it fails and one when it works again. A full disk today loses
  the judgement of a turn without a word.

### S6. Chat replies do not share instance attributes
- **Where:** `orthros.py` (`chat`, the `/api/chat` handler), `orthros_gui.py`
  if it reads `mood`/`acts` from the reply (it reads the JSON, so no change).
- **Do:** `chat()` returns `(reply, mood, acts)`; the handler sends them.
  Two chats at once (the window and a browser tab) currently cross each
  other's mood through `self.mood`.

### S7. The hardware probe uses the same reading
- **Where:** `orthros_tune.py` (`gpu`).
- **Do:** take `(name, total MiB)` from `orthros.nvml_reading()` when it
  answers, else `nvidia-smi` as now. Keep `orthros_tune` free of an import
  cycle: pass the reading in from `maybe_look`, which already has `self.gpu`.

### S8. One place that finds the newest turn log
- **Where:** `orthros.py` (`tail_log`, the `/api/log` handler).
- **Do:** the handler repeats `tail_log`'s search for the newest
  `*-<agent>.log`; give `tail_log` a helper `latest_log(agent)` and use it in
  both.

### S9. `start()` does not hold the lock through git
- **Where:** `orthros.py` (`start`).
- **Do:** `prepare_folders()` commits both agents' trees; while it runs under
  `self.lock`, every `view()` from the page waits. Call it before taking the
  lock (it is idempotent and `loop()` is not running while paused).

### S10. Drop what the agent does not import
- **Where:** `agent\requirements.txt`, `orthros_setup.py` (`make_agent`'s
  import check).
- **Do:** `streamlit`, `openai` and `requests` are not imported by any
  non-test file in `agent\` (grep on 2026-10-27). Remove them unless aider
  needs them transitively (it brings its own `openai`); keep `httpx`,
  `beautifulsoup4`, `flake8`, `aider-chat`. Shared-venv shrinks by a few
  hundred MB and SETUP gets faster. Deploy note: this only changes what
  SETUP installs; existing venvs keep working.

### S11. Serve mode's turn count follows `LC_PARALLEL`
- **Where:** `orthros_service.py` (`turn`, `engine_up`).
- **Do:** size the semaphore from `engine()["parallel"]` when the model is
  loaded (its comment already says "as many at once as it has slots"; it is
  hardcoded to one). Low value while `config.cmd` keeps `LC_PARALLEL=1`, so
  last.
