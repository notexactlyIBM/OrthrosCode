# Orthros improvement plan

What is open, what was decided against (so it is not proposed again), and what
was done, briefly. The code and git history hold the detail.

Read `CLAUDE.md` before taking an item. The rules there that bite here:
changes to `orthros*.py` need Orthros restarted; changes to `agent\` reach A
and B only through `ORTHROS.bat --fresh`; tests never touch live ports or the
real ledger; nothing machine- or person-specific goes into code, docs or
commit messages. Run only the test modules an item touches while the operator
is using the machine (`tests.test_bear` and `tests.test_orthros` take a few
minutes each, the whole suite about six).

## Open

### The loop throws out test rounds whose test passes before any change
- **Where:** `agent\ralph_testfirst.py` (and so `--fresh`).
- **Why:** the ledger (912 rounds to 2026-11-07) showed 110 of 180 "rejected"
  rounds were test rounds the loop itself sent back because the new test
  passed on the unchanged code: a test of nothing. The field report now names
  them (below), so the twin can see the loss; the fix is in the agent.
- **Do:** when a test round's test passes before the change, have the loop
  say so to the model once and ask for a test that fails first, instead of
  ending the round; or skip straight to the change with the test kept as a
  guard. Measure with the ledger: the share of test rounds sent back.
- **Done when:** that share falls over a day of self mode, and
  `agent\test_ralph_testfirst.py` covers the new path.

### Judge the bear's walk in the window
- 2026-11-07 gave it a hump (`FOURS` in `orthros_bear.py`) and a neck thinner
  than its shoulders (`WALL["neck"]`), set from renders, not from the window.
  Walk it in and out a few times (come to the chat card, leave it ten
  minutes) and adjust those numbers if the hump is too much or the head sits
  wrong. No test can judge this.

### S11. Serve mode's turn count follows `LC_PARALLEL`
- `orthros_service.py` (`turn`, `engine_up`): size the semaphore from
  `engine()["parallel"]` when the model is loaded; hardcoded to one. Worth
  nothing until `config.cmd` sets `LC_PARALLEL` above 1, so last.

## Decided against

- *Keep the model loaded (vLLM, LoRA adapters).* LM Studio is the engine by
  design (rule 5); A and B are the same weights with different code.
- *State in SQLite instead of Markdown lists.* The task list is the prompt;
  files and git are what let a small window work a big codebase, and rule 4
  forbids Orthros depending on the agents' code.
- *Drop aider and the sitecustomize guard.* The guard is the structured hook,
  lives outside the agents so they cannot edit it away, and replacing aider is
  a rewrite of the thing under evolution, not a fix to Orthros.
- *Structured output instead of regex on the loop's log.* The unittest lines
  have been stable for a decade and the guard already reports replies.
- *A test that the phrases Orthros counts still exist in the agent (S1).* The
  loop builds them from format strings ("%s rejected it: %s"), so a substring
  test over `agent\*.py` fails on phrases that do exist.
- *Autonomy for PAM.* A client of serve mode on another machine; not Orthros's.
- *More dance moves.* Eight dances and a backflip were added 2026-11-03; enough.

## Done

**2026-11-07, second pass** (needs an Orthros restart; `agent\requirements.txt`
changed, so the next `--fresh` or SETUP picks that up)
- The bear acts out Orthros's events while it is out: a wave at a start,
  proud at good, sad or surprised at bad, a sniff at a handover; once a minute
  at most, never while you type, nothing for the replayed history (O2).
- The walk pose arches the back into a hump behind the shoulders and the neck
  is thinner than the shoulders. The snout was measured closed (every face
  painted against what is drawn: no holes side-on); the "hollow" was a face
  turned from the light, drawn 3% off the den's colour. Lighting has a floor
  now, and a test that no face is drawn in the den's colour (O3).
- One `view()` costs one file open on an unchanged tree, from 28 with two
  tasks and two tools: task and tool entries, and the agents' tool list, are
  kept until their files' mtime or size changes (`work.memo`) (O5).
- `chat()` returns its bear cues instead of leaving them on the instance: two
  chats at once took each other's (S6). One `latest_log` for the terminal and
  `/api/log` (S8). One `read_json`, `write_json` and `memory_status` in
  `orthros_work.py` for the referee and the tuner (S3). The hardware look
  takes the card reading Orthros already has instead of starting nvidia-smi
  (S7). `streamlit`, `openai` and `requests` left `agent\requirements.txt`:
  nothing in the agent imports them (S10).

**2026-11-07, first pass**
- Serve mode keeps every request in `ledger.sqlite` (`requests`): wait, answer
  time, tokens (streams counted), the last 24 hours shown across restarts,
  tokens a second and busy share on the page and in the window (O1).
- The field report tells test rounds sent back from reviewer rejections.
- The pre-launch suite runs once per version of the code (O4).
- A task can start from any folder: a non-git folder is copied in (512 MB cap).
- One `find_lms` (S2); `--doctor` names settings nothing reads (S4); a state
  file that cannot be written is said once (S5); Start does not hold the lock
  through git (S9); `serve_host` documented.

**2026-10-27**
- GPU readings through NVML in-process, not a process every two seconds.
- The field report counts the loop's words only, never the model's.
- The page's version numbers cost no git processes unless `.git` changed.
- A calmer bear: hides after ten minutes, fidgets rarely, a salmon once a day.
