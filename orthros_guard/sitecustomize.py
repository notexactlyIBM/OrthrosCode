"""Orthros's guard on aider. Loaded into every Python an agent starts.

Orthros puts this folder on PYTHONPATH for the agents it launches, with
ORTHROS_AIDER_GUARD=1. Python imports `sitecustomize` at start-up, so this
runs in every interpreter they start -- and does nothing unless that
interpreter goes on to import aider. It lives outside both agents' folders,
so neither can edit it away.

Two things aider does unattended that took down whole turns on 2026-09-23:

  file mentions   A reply that names a file aider has not been given makes it
                  ask "Add file to the chat?". --yes-always says yes to every
                  one, the reply's own edits are thrown away, and the request
                  is sent again with all of them attached: 51,548 and then
                  66,008 tokens against a 32,768 window. A reply that already
                  carries its edit no longer pulls files in, and any other
                  reply only pulls in what still fits.

  oversize send   aider notices a prompt over the window and asks "Try to
                  proceed anyway?" -- yes again. LM Studio refuses it with a
                  400, which reads to the agent as its engine dying: it
                  reloads the model and sends the same prompt again, five
                  times, and the turn ends having done nothing. The guard
                  refuses to send instead, and says so in words the agent
                  can recognise.

Every step is wrapped: if aider changes shape, it runs unguarded rather than
not at all.
"""

import os
import sys

MENTION_SHARE = 0.55   # of the window, the most files may take after mentions
SEND_SHARE = 0.85      # of the window, the most a prompt may be when sent
OVERHEAD = 3000        # tokens of system prompt, repo map and chat around the files
EDIT_MARKS = (">>>>>>> REPLACE", "<<<<<<< SEARCH")
REFUSED = "Orthros guard: prompt too big for the context window"
TARGET = "aider.coders.base_coder"


def _tokens(path):
    try:
        return os.path.getsize(path) // 4
    except OSError:
        return 0


def _window(coder):
    try:
        return int((coder.main_model.info or {}).get("max_input_tokens") or 0)
    except Exception:
        return 0


def patch(module):
    """Wrap Coder.check_for_file_mentions and Coder.check_tokens."""
    coder_class = getattr(module, "Coder", None)
    if coder_class is None or getattr(coder_class, "_orthros_guarded", False):
        return False
    mentions = getattr(coder_class, "check_for_file_mentions", None)
    check = getattr(coder_class, "check_tokens", None)
    if mentions is None or check is None:
        return False

    def check_for_file_mentions(self, content):
        try:
            if any(mark in (content or "") for mark in EDIT_MARKS):
                # The model already did the work. Adding files now would throw
                # its edit away and ask again with a bigger prompt.
                return None
            limit = int(_window(self) * MENTION_SHARE)
            if limit:
                used = OVERHEAD + sum(_tokens(p) for p in
                                      set(self.abs_fnames) | set(self.abs_read_only_fnames))
                wanted = self.get_file_mentions(content) - self.ignore_mentions
                left_out = []
                for rel in sorted(wanted, key=lambda r: _tokens(self.abs_root_path(r))):
                    cost = _tokens(self.abs_root_path(rel))
                    if used + cost > limit:
                        self.ignore_mentions.add(rel)
                        left_out.append(rel)
                    else:
                        used += cost
                if left_out:
                    self.io.tool_output("Orthros guard: not adding %s -- it would not fit "
                                        "in the window." % ", ".join(left_out))
        except Exception:
            pass
        return mentions(self, content)

    def check_tokens(self, messages):
        try:
            limit = _window(self)
            if limit:
                used = self.main_model.token_count(messages)
                if used >= limit * SEND_SHARE:
                    self.io.tool_error("%s: ~%d of %d tokens. Not sending it."
                                       % (REFUSED, used, limit))
                    return False
        except Exception:
            pass
        return check(self, messages)

    coder_class.check_for_file_mentions = check_for_file_mentions
    coder_class.check_tokens = check_tokens
    coder_class._orthros_guarded = True
    return True


class _Finder:
    """Patches aider's Coder the moment its module has run, and not before."""

    def find_spec(self, name, path=None, target=None):
        if name != TARGET:
            return None
        import importlib.util
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(name)
        except Exception:
            return None
        loader = getattr(spec, "loader", None) if spec else None
        run = getattr(loader, "exec_module", None)
        if run is None:
            return None

        def exec_module(module):
            run(module)
            try:
                patch(module)
            except Exception:
                pass

        loader.exec_module = exec_module
        return spec


def _chain():
    """Run the sitecustomize this one hides, if the machine has one.

    Being first on PYTHONPATH means being the `sitecustomize` Python finds;
    one that a distribution or the operator installed would otherwise never
    run in the agents' interpreters.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for entry in sys.path:
        folder = os.path.abspath(entry or os.curdir)
        path = os.path.join(folder, "sitecustomize.py")
        if folder == here or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                code = compile(handle.read(), path, "exec")
            exec(code, {"__name__": "sitecustomize", "__file__": path})
        except Exception:
            pass
        return


if os.environ.get("ORTHROS_AIDER_GUARD") == "1" and TARGET not in sys.modules:
    sys.meta_path.insert(0, _Finder())
_chain()
