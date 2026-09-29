"""Orthros's guard on aider. Loaded into every Python an agent starts.

Orthros puts this folder on PYTHONPATH for the agents it launches, with
ORTHROS_AIDER_GUARD=1. Python imports `sitecustomize` at start-up, so this
runs in every interpreter they start -- and does nothing unless that
interpreter goes on to import aider. It lives outside both agents' folders,
so neither can edit it away.

What aider does unattended that has cost whole turns:

  oversize send   2026-09-23. aider notices a prompt over the window and asks
                  "Try to proceed anyway?" -- yes. LM Studio refuses it with a
                  400, which reads to the agent as its engine dying: it
                  reloads the model and sends the same prompt again, five
                  times, and the turn ends having done nothing.
  file mentions   2026-09-23. A reply that names a file makes aider ask "Add
                  file to the chat?" -- yes to every one, and the request goes
                  again with them attached: 51,548 and then 66,008 tokens
                  against a 32,768 window. On 2026-09-29, smallest first, it
                  pulled in eight files a reply had merely listed and left out
                  the one file the item was about.
  reply room      2026-09-29. The reply ceiling was a fixed 6,000 tokens,
                  chosen when the window was 32,768. The model thinks before
                  it answers, the thinking comes out of the same budget, and
                  aider does not count it: eight rounds in six turns were cut
                  off at the ceiling with 11,000-23,000 tokens of a 49,152
                  window left after the prompt.
  browser tabs    2026-09-29. Every reply cut off at a token limit ends with
                  aider's "Open URL for more info?" -- yes -- and a page about
                  token limits opens on the operator's screen. Nobody is at an
                  unattended agent's screen: it never opens a browser.

So every number here comes from the window the model was loaded with this
turn, per request, and nothing is calibrated to one window size:

  - the reply may use all the room its prompt leaves, less a margin for the
    estimate -- a long thought can finish, and nothing outgrows the window;
  - a prompt that would leave the reply less than an eighth of the window is
    not sent, and says so in words the agent recognises;
  - a reply pulls in only files that the item being worked on names, and only
    while a quarter of the window stays free for the answer.

Each reply is then reported in one line -- thinking, answer, time, the room
it had and whether it finished -- because nothing else records the thinking,
and without it an agent diagnosing a cut-off reply blames the wrong thing.

Every step is wrapped: if aider changes shape, it runs unguarded rather than
not at all.
"""

import os
import re
import sys
import time

REPLY_MARGIN = 0.10    # of the prompt: aider counts with another tokenizer than the model's
MARGIN_TOKENS = 512    # and a little more for the request's own framing
LEAST_REPLY = 0.125    # of the window: a prompt leaving the reply less is not sent
ANSWER_SHARE = 0.25    # of the window, kept free for the answer when files are pulled in
OVERHEAD = 3000        # tokens around the files, before any prompt has been measured
EDIT_MARKS = (">>>>>>> REPLACE", "<<<<<<< SEARCH")
REFUSED = "Orthros guard: prompt too big for the context window"
UNNAMED = "the item does not name them"
NO_ROOM = "it would not fit in the window"
TARGET = "aider.coders.base_coder"
TASK_LIST = "orthros_tasks.md"
OPEN_ITEM = re.compile(r"^([ \t]*)[-*][ \t]*\[ \][ \t]*(.+)$")


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


def room(window, prompt):
    """Tokens a reply may use after a prompt of `prompt` tokens, in `window`."""
    return window - int(prompt * (1 + REPLY_MARGIN)) - MARGIN_TOKENS


def current_item(coder):
    """The item the round works on -- the first open one in the task list in
    the chat, with the lines under it -- or '' when there is no task list."""
    for path in getattr(coder, "abs_fnames", ()) or ():
        if os.path.basename(path) != TASK_LIST:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                lines = handle.read().splitlines()
        except OSError:
            return ""
        for at, line in enumerate(lines):
            match = OPEN_ITEM.match(line)
            if not match:
                continue
            indent = len(match.group(1).expandtabs())
            item = [match.group(2)]
            for more in lines[at + 1:]:
                if more.strip() and len(more) - len(more.lstrip()) <= indent:
                    break
                item.append(more)
            return "\n".join(item)
        return ""
    return ""


def named(rel, text):
    """Does `text` name this file, by its path or its bare name?"""
    base = os.path.basename(rel.replace("\\", "/"))
    return bool(base) and re.search(r"(?<![\w.-])%s(?![\w-])" % re.escape(base), text) is not None


def split_reply(coder, text):
    """(thinking, answer) of a reply as aider holds it while it streams."""
    names = [getattr(coder, "reasoning_tag_name", "") or ""]
    try:
        from aider.reasoning_tags import REASONING_TAG
        names.append(REASONING_TAG)
    except Exception:
        pass
    for name in filter(None, names):
        start = text.find("<%s>" % name)
        if start < 0:
            continue
        start += len(name) + 2
        end = text.find("</%s>" % name, start)
        if end < 0:
            return text[start:], ""              # cut off while still thinking
        return text[start:end], text[end + len(name) + 3:]
    return "", text


def say(line):
    """One whole line on stdout. Not through aider's console, which wraps at 80
    columns and split every line the field report and the tuner look for."""
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def report(coder, seconds, ended):
    """One line on what the reply just received was made of."""
    thinking, answer = split_reply(coder, coder.partial_response_content or "")
    count = coder.main_model.token_count
    think = count(thinking) if thinking.strip() else 0
    said = count(answer) if answer.strip() else 0
    say(
        "Orthros guard: reply {:,} tokens -- {:,} thinking, {:,} answer -- in {:d}s at {:d} tok/s, "
        "of {:,} it could use (prompt {:,}, window {:,}); {}.".format(
            think + said, think, said, int(seconds), int((think + said) / max(seconds, 0.001)),
            getattr(coder, "_orthros_allowed", 0), getattr(coder, "_orthros_prompt", 0),
            _window(coder), ended))


def no_browser(url, *args, **kwargs):
    say("Orthros guard: not opening %s -- nobody is at this screen." % url)
    return False


def patch(module):
    """Wrap Coder.check_tokens, Coder.check_for_file_mentions and Coder.send, and
    keep aider from opening a browser."""
    coder_class = getattr(module, "Coder", None)
    if coder_class is None or getattr(coder_class, "_orthros_guarded", False):
        return False
    import webbrowser
    webbrowser.open = webbrowser.open_new = webbrowser.open_new_tab = no_browser
    mentions = getattr(coder_class, "check_for_file_mentions", None)
    check = getattr(coder_class, "check_tokens", None)
    send = getattr(coder_class, "send", None)
    cut_off = getattr(module, "FinishReasonLength", None)
    if mentions is None or check is None:
        return False

    def check_tokens(self, messages):
        # aider calls this just before every request, reflections included,
        # with the exact messages it is about to send.
        try:
            window = _window(self)
            if window:
                used = self.main_model.token_count(messages)
                left = room(window, used)
                self._orthros_prompt = used
                if left < window * LEAST_REPLY:
                    self.io.tool_error("%s: ~%d of %d tokens, leaving a reply ~%d. Not sending it."
                                       % (REFUSED, used, window, max(0, left)))
                    return False
                params = getattr(self.main_model, "extra_params", None)
                if not isinstance(params, dict):
                    params = {}
                    self.main_model.extra_params = params
                params["max_tokens"] = left
                self._orthros_allowed = left
        except Exception:
            pass
        return check(self, messages)

    def check_for_file_mentions(self, content):
        try:
            if any(mark in (content or "") for mark in EDIT_MARKS):
                # The model already did the work. Adding files now would throw
                # its edit away and ask again with a bigger prompt.
                return None
            wanted = self.get_file_mentions(content) - self.ignore_mentions
            item = current_item(self)
            unnamed = sorted(rel for rel in wanted if item and not named(rel, item))
            wanted = [rel for rel in wanted if rel not in unnamed]
            too_big = []
            window = _window(self)
            if window:
                used = (getattr(self, "_orthros_prompt", 0) or OVERHEAD + sum(
                    _tokens(p) for p in set(self.abs_fnames) | set(self.abs_read_only_fnames)))
                used += self.main_model.token_count(content or "")
                for rel in sorted(wanted, key=lambda r: _tokens(self.abs_root_path(r))):
                    cost = _tokens(self.abs_root_path(rel))
                    if used + cost > window * (1 - ANSWER_SHARE):
                        too_big.append(rel)
                    else:
                        used += cost
            self.ignore_mentions.update(unnamed + too_big)
            for left_out, why in ((unnamed, UNNAMED), (too_big, NO_ROOM)):
                if left_out:
                    say("Orthros guard: not adding %s -- %s." % (", ".join(left_out), why))
        except Exception:
            pass
        return mentions(self, content)

    def guarded_send(self, *args, **kwargs):
        started, ended = time.time(), "finished"
        try:
            yield from send(self, *args, **kwargs)
        except BaseException as exc:
            # Not the error's name: the agents read lines with engine errors'
            # names in them as the engine dying, and aider has printed it anyway.
            ended = ("ran out of room" if cut_off and isinstance(exc, cut_off)
                     else "stopped by an error")
            raise
        finally:
            try:
                report(self, time.time() - started, ended)
            except Exception:
                pass

    coder_class.check_for_file_mentions = check_for_file_mentions
    coder_class.check_tokens = check_tokens
    if send is not None:
        coder_class.send = guarded_send
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
