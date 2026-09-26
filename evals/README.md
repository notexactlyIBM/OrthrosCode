# Held-out exercises

The same format as `exercises\` (see its README), but never used for
practice. They score a new version of an agent before it is proven: each
exercise is worked on in a fresh copy by the version being judged, its hidden
tests are run, and the result is compared with the scores of the version it
came from, exercise by exercise. A version that does worse is not proven, and
its changes do not reach its twin.

So that the score means something:

- the agents never practise on these, and their names never appear in a
  field report -- only the totals do;
- nothing here is copied into an agent's folder, only into `evals-runs\`;
- once scores have been recorded against an exercise, do not change it:
  versions scored before and after would no longer be comparable. Add a new
  one instead.

Written for OrthrosCode on 2026-09-26, standard library only. Each has a
reference solution outside this repository that passes all its tests.
