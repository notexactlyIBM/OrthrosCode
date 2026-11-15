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

### Measure the test rounds sent back, after the next `--fresh`
- 2026-11-15 changed `agent\ralph_testfirst.py` (below). It reaches A and B
  only through `--fresh`. In the 14 days before, 85 of 249 rounds on the
  agents' own code were test rounds sent back (47 for changing the test their
  item named, 38 for a test that passed unchanged), and 30 of 214 scoring
  rounds. After a day of self mode on the new template, count again in
  `ledger.sqlite` (`reason LIKE 'test round: the%'`): the first kind should be
  near none, and no item should have two "passes before any change" in a row.

### The held-out exam no longer tells versions apart
- **Why:** 58 of 58 against 57 of 58 on 2026-11-15, and the same for weeks. The
  gate still stops a broken version; it cannot show a better one. The work a
  scoring took is now told beside the score, which gives the twin a direction,
  but does not decide anything.
- **Also:** a scoring takes the first `eval_count` exercises by name, so four of
  the twelve (the last four by name) have never been scored. `--doctor` now
  warns. With exercises ending when their list is done, `eval_count: 12` costs
  about an hour, less than eight did before.
- **Do, with the card free to try them:** add harder exercises (coarser items
  the agent must split itself, more edge cases in the hidden tests), each tried
  once by the current agents so that it is neither full marks nor hopeless.
  Then choose each scoring's set by headroom: exercises the last passed version
  did not fully pass first, a quarter of the set from ones never scored, the
  rest those scored longest ago -- compared with the latest passed score of
  each exercise rather than only the parent's. That is a change to the gate
  itself, so it wants its own pass and tests.
- **Done when:** a scoring's total is below full marks, and every exercise in
  `evals\` has been scored within three scorings.

### Judge the bear's walk in the window
- 2026-11-07's hump read as an arch in the window. 2026-11-08 flattened the
  back and dropped the head to a walking bear's line (`FOURS` in
  `orthros_bear.py`, set from renders against a photo). Walk it in and out a
  few times (come to the chat card, leave it ten minutes) and adjust those
  numbers if the head sits wrong. No test can judge this.

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

**2026-11-15** (needs an Orthros restart; the `agent\` part needs `--fresh`)
- A practice or a scoring ends when its own list is done. The ledger and the
  turn logs showed a held-out exercise finished in three or four minutes and
  the loop then inventing work on it until its eight ran out: over half of a
  70-minute scoring. Orthros asks for the stop when the loop reports it is
  looking for more work and no item is open (`list_is_done`).
- The minutes, rounds and tokens a scoring took are kept with the score and
  told in the field report beside the version before (`cost_words`). They do
  not gate anything.
- `orthros.json` that does not parse stops Orthros with a message; it used to
  be replaced by the defaults and a new serve key. An unreadable state file is
  set aside and the hourly copy used; it used to be read as no history.
  `write_json` reaches the disk before the rename.
- Test rounds (`agent\`): an item about a test gets no test round; a test the
  item names may be written again; a test that passes on the unchanged code is
  not asked for twice -- the code round is told and decides.
- `--doctor` warns when `eval_count` leaves held-out exercises unscored.

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
