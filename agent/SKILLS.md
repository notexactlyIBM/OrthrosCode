# Skills: how common changes are done in this codebase

**Add a setting.** In config.cmd add `set "LC_NAME=value"` under a `REM ---`
heading that says what it does and why. Read it where it is used:
`env_int("LC_NAME", default)` in supervisor_env.py, or
`_env_int("LC_NAME", default)` in ralph_common.py. Nothing else reads config.cmd.

**Add a tool a round can ask for.** In ralph_tools.py add a regex like
`FIND_ASK`, handle it in `handle_tool_requests` by writing the answer into
FOUND.md and replacing the request line with a note. Then add one line
describing it to RALPH_PROMPT.md under "How to work".

**Grow a module past ~9,000 tokens? Split it.** Make a new module holding
the function and the imports it needs, import it back where it was used,
and keep the name. Never merge modules back together.

**Add a new ralph_ module.** Create `ralph_<name>.py` with the function and
the imports it needs. Import it back where it was used (usually
`ralph_session.py` or another `ralph_` module) and keep the name. Then add
`test_ralph_<name>.py` at the top level: `class Test...(unittest.TestCase)`,
using `tempfile` for any files, no network, no LM Studio, no sleeping.
The whole suite must still finish in seconds.

**Add a test.** A `test_<module>.py` at the top level, with
`class Test...(unittest.TestCase)`. Use `tempfile` for any files. No network,
no LM Studio, no sleeping: the whole suite runs after every edit and must
take seconds. Never delete or weaken a test to make a change pass.

**Change what the model is told.** Prompts that LocalCoder writes are
constants in ralph_prompts.py. The standing prompt for a folder is its
RALPH_PROMPT.md; the task list header is read every round.

**Record something the next session should know.** `record_lesson(workspace,
text)` in ralph_tools.py appends to LESSONS.md, whose newest lines go in
front of every round.

**Find where something is used.** Write `FIND: name` in the task list and
stop; the matches are in FOUND.md next round. `DOCS: module` does the same
with an installed library's own documentation.

**Read something too big to be sent.** `DIGEST: <file> -- <question>` reads
the file in parts, carrying notes from part to part, and puts the answer in
FOUND.md (ralph_digest.py). Slow -- one request a part -- but nothing is too
long. `.localcoder-aider.log` is last session's full transcript.

**Add a way for a session to stop -- or better, not to.** An early stop
throws away the rest of the turn, so first try to recover: park the item
(`park_task`), move to the next brief, or send less next round. When a stop
is truly needed, return False straight after `self.stop("why")`, in a method
whose docstring says "False to stop". test_stop_paths.py fails any stop that
does not say why.

**Keep a round inside the context window.** A round sends the task list, the
files `files_for_task` picks from the item's backticked names, SKILLS.md and
any fresh answers (ralph_send.py). A reply that names another file can pull
it in too. A prompt bigger than the window is refused -- `refused` on the
RoundResult -- and the next round on that item sends less.

