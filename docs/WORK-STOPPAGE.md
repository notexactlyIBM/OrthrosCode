# Why the agents stopped working, and what changed

An investigation of the turns logged on 2026-09-23, 13:57 to 15:00. Five turns:
three of B improving A, two of A improving B. Between them they kept one
change. Every turn ended early.

| turn | planned | ran | how it ended |
|---|---|---|---|
| B 13:57 | 22 min | 18 min | "It could not think of anything else" |
| A 14:31 | 45 min | 7 min | "Five rounds in a row lost to the engine" |
| B 14:39 | 15 min | 11 min | "Nothing moved in 10 minutes" |
| A 14:52 | 45 min | 7 min | "Five rounds in a row lost to the engine" |
| B 15:00 | 15 min | 14 min | "Every item is ticked" -- after its refill failed |

## The root cause: prompts bigger than the window, read as a dead engine

A's rounds never reached the model. Every one of them was refused by LM Studio:

    litellm.APIConnectionError: APIConnectionError: OpenAIException - Engine
    protocol predict request returned 400: {"error":{"code":400,"message":"request
    (32958 tokens) exceeds the available context size (32768 tokens) ...

The prompt was 190 tokens too big. Three things combined to make one bad
round into a dead turn:

1. **aider's file mentions.** The model's first reply named files it had not
   been sent (`FIELD_REPORT.md`, `supervisor.py`, ...). aider asks "Add file to
   the chat?" for each, `--yes-always` answers yes, the reply's own edits are
   discarded, and the request goes again with every named file attached. For
   B's planning rounds the second request was 51,548, then 55,264, then
   66,008 tokens. Planning prompts name files on purpose -- "name the parts of
   the code it will touch" -- so planning was the worst affected.
2. **"Try to proceed anyway?" -- yes.** aider saw the prompt was over the
   window and sent it regardless, because unattended it says yes to everything.
3. **The misreading.** The agent's list of engine-death phrases contains
   `apiconnectionerror`, and that is how aider words a 400. So the loop took
   an oversized prompt for a crashed engine: it reloaded the model (a minute),
   did not charge the round to the item (so the item was never parked or
   split), and sent the same prompt again. Deterministic, five times, then
   "Five rounds in a row lost to the engine". The field report then told B
   that A's engine kept dying, and B spent its next turns planning a fix for
   engine handling that was never the problem.

Reproduced here against real aider 0.86.2 and a fake LM Studio that enforces
a context limit: unguarded, a reply naming three files pulled all three in and
sent a 9,766-token prompt at an 8,000-token window.

## The other ways turns ended early

- **A rollback wiped the loop's own bookkeeping.** Undoing a round is
  `git checkout -- .`, but the loop only committed rounds that changed code.
  Items a refill had just added, ticks, parks and lessons were uncommitted, so
  the first rejected round after a refill emptied the list again, and the loop
  then stopped because "the item could not be parked" -- the undo had removed
  it. Reproduced with a git-backed test.
- **A rollback item no round could act on.** Orthros's note after a rollback
  said to run `git diff d2e6cea orthros/failed-2`. Rounds cannot run git. B
  spent eight rounds on that item writing notes about a diff it could not see,
  and the checkpoint ended the turn.
- **Rolling back the wrong thing.** A had two idle turns, so Orthros rolled A
  back to its proven version, undoing B's work. The cause was B's task list
  and aider, not A's code, so the proven version failed in the same way.
- **No memory across turns.** The same top item killed both of A's turns; the
  rounds that could have parked it were never charged to it.
- **Refills that gave up.** An empty or timed-out refill ended the session
  (one of them silently), where another brief would have been a different
  prompt. Milestones written in a slightly wrong form counted as nothing.
- **A checkpoint too eager to judge.** Ten minutes can be two rounds on this
  rig; with a refill inside the window, planning counted as "nothing moved".
- **The reviewer mostly said nothing.** "No clear verdict" on most rounds: the
  thinking model spent its 3,000-token budget before writing the verdict.

## What changed

In Orthros (the referee -- takes effect at once, no agent changes needed):

- **orthros_guard/sitecustomize.py**, loaded into the agents' Pythons: a reply
  that already carries an edit pulls no files in; other replies only pull in
  what fits in 55% of the window; a prompt over 85% of the window is not sent.
  Verified against real aider 0.86.2.
- **Items a turn keeps dying on are parked** after two turns (NR_OF_TRIES,
  after fstandhartinger/ralph-wiggum). **An early stop becomes the twin's first
  item**, with the words to search for.
- **The field report diagnoses oversize prompts** instead of counting them as
  engine deaths.
- **ROLLBACK.md** holds the undone diff; the item says what to do if the diff
  was not the cause.
- **One rollback is spared** when turns were lost to the window or the engine.
- **Machine failures are retried** after 2, 5 and 15 minutes before giving up.
- **Giving up is loud**: ORTHROS-NEEDS-YOU.txt, a red page, a desktop
  notification, a beep.
- **Restarts no longer lose turns**, and a reused process id no longer hangs
  Orthros.
- **The page** gains a chat box (ask how it is going; steer the work), a
  read-only raw-output terminal, and a GPU view.
- **`--apply-patch`** brings a fix to agent\ into the live agents.

In the agent (reaches the live agents through `--apply-patch`, below):

- A refused prompt is `refused`, not an engine death: no reload, the round
  counts against the item, and the next round sends less.
- The loop commits its bookkeeping before every round, so an undo undoes only
  that round.
- Refills normalise loosely written milestones and items, move on to the next
  brief instead of stopping, set aside a milestone twice made nothing of, and
  drop items that repeat parked ones.
- The checkpoint needs four rounds before it may stop a session, and counts
  any code change (not just a change in line count) as movement.
- The reviewer retries once with more room, and says why when it gives no
  verdict.
- Temperature by kind of round: code 0.2, verifying 0.2, decomposing 0.5,
  planning and briefs 0.85.
- `test_stop_paths.py` reads the loop's source and fails any way of ending a
  session that does not say why.

## Getting the agent changes into running agents

agent\ is only the template; the live agents are their own git histories.

    python orthros.py --apply-patch patches\2026-09-24-keep-working.patch

Close Orthros first. Each agent gets the patch file by file with a three-way
merge; what applies is checked (imports and tests) and recorded as that
agent's newest proven version. Files that clash with what the agents have
written themselves are left out and listed -- usually SKILLS.md; paste those
by hand or leave them. If a patched agent then fails to start, the usual
retreat undoes it.
