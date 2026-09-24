@echo off
REM ==========================================================
REM  LocalCoder settings.  Edit this file, nothing else.
REM ==========================================================

REM --- The folder the AI can read and edit. -----------------
REM  Orthros: this copy works on the other one.  A edits B, and
REM  B edits A.  Run them one at a time -- they share one card and
REM  one LM Studio.  Each copy's own git history is the undo.  %~dp0 is
REM  this folder, so the pair works wherever OrthrosCode is unpacked.
set "LC_WORKSPACE=%~dp0..\OrthrosCode B"

REM --- Which model to load. --------------------------------
REM  Leave BLANK to just use whatever is already loaded in LM Studio.
REM  To see valid keys, run:  LIST_MODELS.bat
REM  Dense 27B: every parameter thinks on every token. The 35b-a3b is a
REM  mixture-of-experts that only wakes 3B of its 35B per token, which is
REM  why it was fast but kept producing edits that would not apply.
REM  Keep the A3B for quick chat; this is the one for real work.
REM
REM  This is unsloth's build. Benchmarked against the lmstudio-community
REM  build of the identical model, 3 runs each, 900-token generations:
REM    lmstudio-community  46.2 tok/sec
REM    unsloth             60.7 tok/sec
REM  Same weights, same quant name, 32% apart. Worth knowing before
REM  swapping publishers to "the same" model.
REM
REM  2026-09-21: moved to Qwen 3.8 27B, lmstudio-community Q4_K_M.
REM  Two things it gives up against the 3.6 build above, both worth
REM  checking in the first run's log:
REM    - no MTP head, so no speculative decoding.  On 3.6 that was
REM      55 tok/sec with it and 42 without.
REM    - lmstudio-community rather than unsloth, which measured 32%
REM      slower on 3.6 for the same weights.
REM  Its vision projector (mmproj, 0.87 GB) is switched off by moving the
REM  file out of the model folder -- LM Studio only loads one it finds
REM  there.  Keep it in a folder outside the models directory, and move
REM  it back beside the model to get vision again.
REM  To go back:  set "LC_MODEL_KEY=qwen3.6-27b-mtp"
set "LC_MODEL_KEY=qwen/qwen3.8-27b"

REM --- MEMORY, the thing most likely to end a run. ------------
REM  Windows counts one limit for everything a program may need, and the
REM  graphics driver charges system memory to back what the model puts on
REM  the card.  A 27B model at 32k context therefore needs roughly its
REM  video memory AGAIN in system commit.  On 2026-09-22, on a 32 GB
REM  machine with a small page file, that limit was reached repeatedly:
REM  the engine failed 119 allocations across three turns ("bad
REM  allocation"), died 27 times, and Windows killed the orchestrator and
REM  a desktop app.  Free video memory was never the problem -- 6 GB was
REM  spare on the card throughout.
REM
REM  What helps, in order:
REM    1. Give Windows a bigger page file (System > About > Advanced
REM       system settings > Performance > Advanced > Virtual memory).
REM       System-managed, or 32 GB, on an SSD.
REM    2. Close browsers and Electron apps while a run is on.
REM    3. The settings below: no draft model, smaller files per round,
REM       a smaller reply ceiling.
REM    4. Lower LC_CONTEXT to 24576 if it still happens -- but check the
REM       logs first for rounds that "hit a token limit".

REM --- Context window, in tokens. --------------------------
REM  Bigger = the AI remembers more of your code at once.  What sets the
REM  ceiling is NOT what will load -- it is what is left on the card
REM  afterwards.  llama.cpp allocates compute buffers and captures a CUDA
REM  graph WHILE ANSWERING, out of that leftover, and a card with no room
REM  fails the request with "bad allocation" whatever you asked it.
REM
REM  Measured 2026-08-06 with a 15k-token request, three times each:
REM    65536 + draft head   3043 MB free   3 of 3 FAILED
REM    65536, no draft head 3739 MB free   0 of 3 failed   42 tok/sec
REM    57344 + draft head   3564 MB free   0 of 3 failed   55 tok/sec
REM    49152 + draft head   4133 MB free   0 of 6 failed   54 tok/sec
REM
REM  Then 49152 failed 3 of 3 in a real run, because that test was wrong:
REM  it sent the files at 15,092 tokens, and aider wraps them in its own
REM  system prompt.  The real refill round -- the biggest prompt of any
REM  session -- is 18,533.  It dies at the first decode step after the
REM  prompt is processed.  So the number that matters is not the context
REM  size on its own but context AND prompt together, and 49152 has room
REM  for one 15k request and not for one 18.5k request.
REM
REM  32768 is the setting this project ran on for weeks without a crash.
REM  It is still 1.8x the largest prompt ever measured here, and it leaves
REM  about 1GB more headroom than 49152 for the decode-time allocations
REM  that are what actually fail.  Do not raise it to buy context that is
REM  not being used -- peak measured use is 18.5k of it.
REM
REM  Twice the context for the same memory: in LM Studio, open the model's
REM  default settings (My Models, the gear) and set Flash Attention on and
REM  K and V cache quantization to Q8_0.  `lms load` cannot set those, but
REM  it uses the model's defaults.  The cache then takes half the room, so
REM  65536 here costs about what 32768 cost before.  Try it with SELFTEST,
REM  watch the first turn, and come back to 32768 on any "bad allocation".
REM  Running at 65536 with those settings since 2026-09-24.
set "LC_CONTEXT=65536"

REM --- How many requests it can answer at once. -------------
REM  LEAVE THIS AT 1.  Memory used = LC_CONTEXT x LC_PARALLEL, so the
REM  LM Studio default of 4 quietly costs you four times the memory for
REM  no benefit when only one person is using it.  This was the cause of
REM  the crash at 97% while loading.
set "LC_PARALLEL=1"

REM --- GPU offload:  max  |  off  |  a number like 0.8 -----
REM  Keep this at max.  Anything less pushes layer 0 onto the CPU, which
REM  makes LM Studio switch off a fused kernel this model relies on and
REM  the whole thing gets slower.  Only lower it if max will not load.
set "LC_GPU=max"

REM --- Prompt caching (1 = on, 0 = off). -------------------
REM  Off because it does nothing here, NOT because it fixes anything.
REM  aider's prompt caching is a feature of the Anthropic and DeepSeek
REM  APIs; against an OpenAI-compatible local endpoint it is a no-op.
REM
REM  Do not confuse it with LM Studio's OWN prompt cache, which is what
REM  produces the crash, and which this setting does not control:
REM    E srv alloc: failed to allocate memory for prompt cache state:
REM                 bad allocation
REM  That snapshot is ~2 GB, taken after every request, out of the same
REM  card the model is on.  Tested 2026-08-06 with this set to 0: the
REM  crash happened anyway, so the flag is not the lever.  See the note
REM  on LC_CONTEXT for what actually governs it.
set "LC_PROMPT_CACHE=0"

REM --- Speculative decoding (1 = on, 0 = off). -------------
REM  Drafts several tokens per step and checks them in one pass.  Measured
REM  2026-08-06 on this build: 90-94% draft acceptance, and worth 55 tok/sec
REM  against 42 with it off -- a 30% speedup.  LEAVE IT ON.
REM  It is not free in memory: turning it off buys back about 700MB.  But
REM  lowering LC_CONTEXT buys the same headroom and costs no speed, so
REM  reach for that first.  This is the lever for when you have already
REM  cut context and still have no room.
REM  Ignored on builds with no MTP head.
set "LC_SPECULATIVE=0"

REM --- LM Studio server port. ------------------------------
set "LC_PORT=1234"

REM --- Where the chat box appears:  browser  |  terminal ----
set "LC_UI=browser"

REM --- How the AI writes file edits. ------------------------
REM  diff  = fast, cheap, occasionally misapplies on weak models
REM  whole = rewrites whole files, slower but more reliable
set "LC_EDIT_FORMAT=diff"

REM --- Repo map size in tokens (0 = off). -------------------
REM  This is the summary of your codebase sent with every message.
REM  Raise for better awareness, lower for speed.
set "LC_MAP_TOKENS=2048"

REM --- Repo map for unattended rounds, in tokens (0 = off). -
REM  A one-screen summary of every other file: its classes, functions and
REM  their signatures.  Off while the project was one file, because then
REM  it only repeated what was already being sent.  Now that the source is
REM  split into modules, each round is sent just the module its item names,
REM  and without a map the model cannot see what the rest of the project
REM  offers -- so it calls methods that do not exist, or re-implements
REM  ones that do.  1024 costs about 3% of the window and closes that gap.
set "LC_RALPH_MAP_TOKENS=1024"

REM --- Turn a plain folder into a git repo? (1/0) ----------
REM  The browser chat box refuses to run outside a git repo, so LocalCoder
REM  quietly makes one for any folder that is not already a project.  It
REM  also snapshots whatever you have dropped in each time it starts, which
REM  is what lets you undo the AI's edits.  Your real git projects are
REM  never touched by this.  Set to 0 to disable and use the terminal.
set "LC_INIT_GIT=1"

REM --- Cleanup on exit (1 = yes, 0 = no). ------------------
set "LC_UNLOAD_ON_EXIT=1"
set "LC_STOP_SERVER_ON_EXIT=1"

REM --- Seconds to wait for a reply before giving up. --------
set "LC_TIMEOUT=900"

REM ==========================================================
REM  RALPH.bat -- working through the task list unattended.
REM ==========================================================

REM --- Which file holds the checkboxes. --------------------
REM  Leave BLANK and it finds the markdown file whose name contains
REM  "notes", "tasks", "todo" or "plan".  Set it if you have several.
set "LC_RALPH_NOTES="

REM --- Files it is allowed to edit, separated by semicolons. -
REM  The notes file is always added, so only list the code here.
REM  Globs work, so `*.py` keeps up as one file becomes several.
REM
REM  This does NOT mean everything listed is sent every round: items name
REM  the function they are about, and only the file holding that symbol
REM  goes in.  With ONE file that does nothing, and one file is where the
REM  trouble starts -- worms_game.py reached 1,403 lines, 52% of the
REM  window, and rounds began failing for want of room to reply.  Splitting
REM  the source into modules is what buys that back, which is why the glob
REM  is here: the split should not also need a config edit at 3am.
set "LC_RALPH_FILES=*.py"

REM --- Default minutes for option 2. ------------------------
set "LC_RALPH_MINUTES=30"

REM --- Give up on a single round after this many seconds. ---
REM  Stops one wedged round from eating the whole budget.
set "LC_RALPH_ITER_TIMEOUT=420"

REM --- Give up on one REQUEST after this many seconds. ------
REM  This is the important one.  When LM Studio's engine dies mid-answer
REM  the connection just hangs, and aider sits waiting for the full
REM  LC_TIMEOUT before admitting it.  With that at 900 the loop lost 75
REM  of 93 minutes to five dead requests.  A legitimate full-length
REM  reply is 8192 tokens, which even at the slowest rate seen (50/sec)
REM  takes under 170 seconds -- so anything past 240 is a corpse.
set "LC_RALPH_API_TIMEOUT=240"

REM --- Temperature: cold to write code, warm to invent work. -
REM  Editing code and thinking up work want opposite things from the
REM  same model.  A diff has exactly one correct form, and every degree
REM  of freedom is another chance the SEARCH block will not match.  A
REM  round asked for the next ten things to build wants range, and at a
REM  low temperature returns the same safe four ideas every time.
REM  Set per round, automatically.  Raise the second one if the batches
REM  it writes all look alike; lower the first if diffs stop applying.
set "LC_TEMP_CODE=0.2"
set "LC_TEMP_BRAINSTORM=0.85"

REM --- Brainstorming when the list runs dry. ----------------
REM  One refill tops the list up and goes straight back to work, which
REM  means stopping to think again twenty minutes later -- and each
REM  return trip costs a whole round.  When the list is genuinely empty
REM  it stays in generation until there are this many items queued, for
REM  at most this many rounds in a row.
set "LC_RALPH_BRAINSTORM_UNTIL=12"
set "LC_RALPH_BRAINSTORM_ROUNDS=3"

REM --- A second agent reviews every change (1/0). ----------
REM  After each round that changes code, a separate request -- fresh
REM  context, no file access, no stake in the change -- reads the diff
REM  and the item and says keep or reject.  A rejected round is rolled
REM  back and the reason is written under the item, so the next try
REM  knows what was wrong.  That is how the two compare notes.
REM
REM  Every other check asks whether the code is well formed.  This is the
REM  only one that asks whether it does what the item said, and until now
REM  the worker answered that about its own work.  Roughly doubles the
REM  time per round.  Same model, so the same blind spots -- but a cold
REM  read of a diff catches what the author talked itself past.
set "LC_RALPH_REVIEW=1"

REM --- Trading time for results. ------------------------------
REM  Tries an item gets before it is parked.  Each try runs warmer than
REM  the one before, so the tries differ, and the tests and the reviewer
REM  keep the one that holds -- more tries, better odds, more time.
set "LC_RALPH_ATTEMPTS=3"
REM  An item that names no file it can be matched to: first ask the model
REM  which files, from an outline of every module.  One short request.
set "LC_RALPH_LOCATE=1"
REM  Modules summed up in GISTS.md by the model per refill, for the planner.
REM  0 = keep only the docstring summaries, which cost nothing.
set "LC_RALPH_GISTS_PER_REFILL=6"
REM  Most parts a DIGEST: request reads a file in.  About 5,000 tokens a
REM  part and one request each, so 12 is roughly 60,000 tokens of file.
set "LC_RALPH_DIGEST_PARTS=12"

REM --- Start even when the card is shared? (1/0) -----------
REM  LEAVE THIS AT 0.  An unattended run refuses to start if something
REM  else is already on the graphics card -- a second LM Studio, an
REM  ollama server, another llama-server.  Two engines on one 24GB card
REM  is not slow, it is a session that never finishes a round: on
REM  2026-08-11, with three LM Studios and ollama up, a 90-minute run
REM  made about ten attempts in 48 minutes, completed no rounds at all,
REM  and had to be killed.
REM  Counting the processes catches what free VRAM cannot -- an idle
REM  rival has claimed nothing yet, and will the moment it loads.
REM  Set to 1 only if you have measured that your setup really fits.
set "LC_SHARE_GPU=0"

REM --- Short-form instructions (1/0). ----------------------
REM  Swaps the prose in LocalCoder's own prompts for imperative orders.
REM  Be clear about what this does and does not buy.  Measured here:
REM  789 -> 620 tokens per generating prompt, against a round that sends
REM  about 13,000.  That is 1.3%, not 75%.
REM
REM  The big saving people report from terse prompting comes from agents
REM  that narrate their tool calls -- "I executed the web search tool" ->
REM  "Tool work".  This model has no such channel: it emits a diff.  What
REM  it DOES spend is reasoning, up to 3,000 tokens of it per round, and
REM  no wording in the prompt has ever shortened that.  The lever for
REM  that one is LC_RALPH_REASONING below.
REM
REM  Worth trying anyway for a reason that is not tokens: a small model
REM  follows five short orders more reliably than four paragraphs about
REM  why the orders are what they are.
set "LC_RALPH_TERSE=1"

REM --- How hard the model thinks before answering. ----------
REM  low | medium | high, or blank to leave it alone.
REM  The reply ceiling covers the model's reasoning as well as its answer,
REM  and this one reasons at length -- a review round once spent 2,900
REM  tokens thinking against a 3,000 ceiling and had a hundred left to
REM  answer with.  If this build honours the parameter, "low" is the only
REM  thing that reaches that.  Telling it to be brief in the prompt does
REM  not, and never has.
set "LC_RALPH_REASONING=low"

REM --- Split a source file once it passes this many tokens. -
REM  A file the model cannot hold alongside its own reply is a file no
REM  round can finish work in.  At 1,403 lines worms_game.py was taking
REM  73% of the window on its own and half the rounds ran out of room to
REM  answer.  Past this size LocalCoder moves a class into its own module
REM  itself -- parsed, not prompted, verified by importing and starting
REM  the program, and put back if that fails.  Asking the model to do it cost seven rounds
REM  of fourteen and did not finish.
REM  If one class is too big on its own, its largest method is moved
REM  into <class>_<method>.py instead, leaving a one-line stub in the
REM  class.  (2026-09-21, on a test project: one 12,567-token file down
REM  to 6,332, behaving identically.)
set "LC_RALPH_MAX_FILE_TOKENS=7000"

REM --- Finished items to keep in the task list. -------------
REM  The rest are filed into DONE.md.  They still count as done and are
REM  still there to read -- they just stop being resent on every round.
REM  This is what stops the task list outgrowing the context window: the
REM  file grows forever, the window does not.  Measured here: 57 finished
REM  items were costing 3,522 tokens a round to describe work that was
REM  already over.  A few are kept because a round has no memory, and
REM  they are the only thing telling it what the last few rounds did.
set "LC_RALPH_KEEP_DONE=8"

REM --- How many times it may refill an empty task list. -----
REM  0 = as many as the clock allows.  That is the point: ask for 90
REM  minutes and it should spend 90 minutes.  With this at 4, a 90-minute
REM  run spent 32 and handed the rest back with the plan half-built.
REM
REM  When the list runs dry it does one of four things, in rotation:
REM    decompose  take the next `## [ ]` milestone from PLAN.md and break
REM               it into five to ten concrete items   (3 rounds in 5)
REM    brief      take one of the standing sections at the bottom of your
REM               task list and turn it into items     (1 round in 5)
REM    verify     re-read what is already ticked off, check it against the
REM               code, and write items for what is wrong  (1 round in 5)
REM    plan       when no milestones are left, write a fresh set of six to
REM               twelve into PLAN.md and start again
REM
REM  So it plans coarsely, works finely, and checks itself -- and never
REM  runs out of work while there is time on the clock.  Set a number if
REM  you would rather it stopped after a fixed amount.
set "LC_RALPH_REFILLS=0"

REM --- How often it stops to check it is getting somewhere. -
REM  In minutes.  At each checkpoint it reports what moved since the
REM  last one, and stops early if the answer is nothing.
set "LC_RALPH_CHECKPOINT=10"
REM  ...but only once this many rounds have run since the last one.  Ten
REM  minutes is two or three rounds on a 27B model, fewer with a refill
REM  or a slow review in them -- too few to call a run stuck, and it was
REM  ending sessions that were about to get going.
set "LC_RALPH_CHECKPOINT_ROUNDS=4"

REM --- Longest reply the model may give, in tokens. ---------
REM  aider never sends a limit of its own, so without this the model
REM  talks until the context window is full: measured at 21,278 tokens
REM  for one reply, which loses the round.  A good working round's reply
REM  is about 2,700.
REM
REM  But this ceiling covers the model's REASONING as well as its answer,
REM  and this one reasons at length.  Measured 2026-08-06: three review
REM  rounds "hit a token limit" at 42%, 59% and 59% of the window -- not
REM  close to full.  They hit this number.  One spent 2,900 tokens
REM  thinking against a 3,000 ceiling and had a hundred left to answer
REM  with.  8000 leaves room for both; LocalCoder raises it on its own
REM  when a reply is cut off with window to spare, and lowers it only
REM  when the window itself is genuinely full.
set "LC_RALPH_MAX_OUTPUT=6000"

REM --- Two-step editing for hard items (1/0). ---------------
REM  aider's "architect" mode: the model proposes the change, then a
REM  second pass applies it.  Documented as more reliable on weak
REM  models, but it doubles the requests per round, and on a 32k
REM  window that is a real risk.  Off until measured.
set "LC_RALPH_ARCHITECT=0"

REM --- What to launch to prove it still works. --------------
REM  After every round the program is started headless for a few
REM  seconds.  If it will not start, the round is rolled back.
REM  Leave BLANK to find the script with `if __name__ == "__main__"`.
REM  Orthros: "none" -- the other copy's scripts are bench_parallel.py,
REM  supervisor.py and gui.py, and starting any of them loads models on
REM  the LM Studio this run is using, or opens a browser every round.
REM  A name that is not a file means nothing is launched; every module
REM  is imported instead, which catches the same crashes.
set "LC_RALPH_RUN=none"
set "LC_RALPH_RUN_SECONDS=6"
