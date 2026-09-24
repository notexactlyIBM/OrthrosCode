# Practice exercises

Small coding jobs the agents have never seen, used to measure how well an
agent codes in general -- not how well it edits itself. In self-improvement
mode, every few turns (`practice_every` in orthros.json) one turn is a
practice: a fresh copy of an exercise, a short session, then the hidden tests
in `hidden\` are run against what it wrote. The score goes into that agent's
FIELD_REPORT.md, which its twin reads when deciding what to improve.

Each exercise is a folder with:

    task.md             what to build, written as the task list's first items
    <module>.py         a stub, so the files and names are fixed
    hidden\test_*.py     the scoring tests; never copied into the practice folder

Add your own the same way. Keep them small (one session), standard library
only, and specific enough that the hidden tests are fair.
