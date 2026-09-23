"""Move a class out of a growing file, mechanically.

Splitting a source file is the one change that buys back context as a project
grows -- the loop sends only the files an item names, so a project in six
modules costs a fraction of one in a single file. It is also the change the
model is worst at. The move itself is large: delete two hundred lines here,
create them there, fix the imports both ways. That is a long reply against a
prompt already holding the whole file, and on 2026-08-10 it cost seven rounds
out of fourteen without finishing.

None of it needs judgement. Which lines belong to a class, which imports it
uses, what has to be imported back -- a parser knows all of that exactly, in
milliseconds, and cannot truncate halfway through. So the loop does it itself,
the same way it ticks its own milestones rather than asking.

Conservative on purpose: it refuses anything it cannot prove safe, and it puts
both files back if the result does not import and run.
"""

import ast
import os
import re


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def write(path, body):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)


def _module_names(tree):
    """Every name defined at the top level, and the node that defines it."""
    found = {}
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            found[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node
    return found


def _names_used(node):
    """Every bare name the node mentions. Deliberately over-inclusive."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _imports(tree):
    """Top-level import statements, as (source_line, names_bound)."""
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = {(a.asname or a.name).split(".")[0] for a in node.names}
            out.append((node, names))
        elif isinstance(node, ast.ImportFrom):
            names = {(a.asname or a.name) for a in node.names}
            out.append((node, names))
    return out


def _segment(body, node):
    """The exact source of a top-level node, including any decorators."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    lines = body.splitlines(keepends=True)
    return "".join(lines[start - 1:node.end_lineno])


def candidates(path):
    """Classes worth moving, largest first. Returns [(name, lines)].

    A class is only a candidate if nothing it needs would have to be imported
    back from the file it is leaving. That is what keeps this from creating a
    circular import, and it is why the leaves go first: move `Particle` before
    `Terrain`, and by the time `Terrain` moves its dependency is already
    somewhere else.
    """
    body = read(path)
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    defined = _module_names(tree)
    out = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        used = _names_used(node)
        # Anything it needs that still lives in this file is a problem, and
        # that includes constants. An earlier version of this waved those
        # through on the grounds that they only point one way; they do not.
        # The file it leaves has to import the class back, so a class that
        # imports a constant forwards makes exactly the cycle the check was
        # meant to prevent -- `worms_game` -> `projectile` -> `worms_game`,
        # which fails at import time on a half-built module.
        #
        # Move the constants to a module of their own first and the problem
        # disappears: everything then imports in one direction.
        if {n for n in used if n in defined and n != node.name}:
            continue
        out.append((node.name, node.end_lineno - node.lineno + 1))
    out.sort(key=lambda pair: -pair[1])
    return out


def extract_constants(path, into=None, verify=None):
    """Move the module-level settings into a file of their own.

    This is the move that unblocks every other one. While the constants live
    beside the classes, any class taken out has to import them back, and the
    file it left has to import the class -- a cycle, and an import error the
    moment either module is loaded. With them somewhere neutral, everything
    imports one way and the classes come out cleanly, biggest last.

    Shared mutable state comes too. A list several modules append to has to be
    the same list, and `from constants import particles` binds the same object
    in each of them, which is what that needs.
    """
    body = read(path)
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False, "will not parse"

    defined = _module_names(tree)
    moving = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not names:
            continue
        # Only settled values -- anything built from a class or function in
        # this file belongs to the program, not to its configuration. The
        # name being assigned is itself a Name node, so it has to come out
        # of the comparison or every assignment disqualifies itself.
        depends = {n for n in _names_used(node.value) if n in defined}
        if depends:
            continue
        moving.append((node, names))
    if not moving:
        return False, "no module-level settings to move"

    folder = os.path.dirname(path)
    target = into or os.path.join(folder, "constants.py")
    if os.path.exists(target):
        return False, "%s already exists" % os.path.basename(target)

    segments = [_segment(body, node) for node, _ in moving]
    names = sorted({n for _, ns in moving for n in ns})

    before = body
    new_body = ('"""Settings and shared state, kept apart so every other module\n'
                'can import them without importing each other."""\n\n'
                + "".join(segments))
    remaining = body
    for seg in segments:
        remaining = remaining.replace(seg, "", 1)
    remaining = re.sub(r"\n{4,}", "\n\n\n", remaining)
    module = os.path.splitext(os.path.basename(target))[0]
    remaining = _add_import(remaining, "from %s import %s\n" % (module, ", ".join(names)))

    write(target, new_body)
    write(path, remaining)
    if verify and not verify():
        write(path, before)
        os.remove(target)
        return False, "moving the settings broke it -- put back"
    return True, "moved %d setting(s) into %s" % (len(names), os.path.basename(target))


def plan_extraction(path, name):
    """What moving `name` out of `path` would produce. Returns a dict or None."""
    body = read(path)
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return None
    defined = _module_names(tree)
    node = defined.get(name)
    if not isinstance(node, ast.ClassDef):
        return None

    used = _names_used(node)
    internal = {n for n in used if n in defined and n != name}
    if any(isinstance(defined[n], (ast.ClassDef, ast.FunctionDef)) for n in internal):
        return None                      # would need importing back: a cycle

    # Imports the moved class actually uses, in their original order.
    keep = []
    for imp, bound in _imports(tree):
        if bound & used:
            keep.append(_segment(body, imp).rstrip("\n"))

    # Module-level constants it needs, imported forwards from the old file.
    constants = sorted(n for n in internal)

    module = os.path.splitext(os.path.basename(path))[0]
    head = list(keep)
    if constants:
        head.append("from %s import %s" % (module, ", ".join(constants)))

    moved = _segment(body, node)
    new_body = "\n".join(head) + ("\n\n\n" if head else "") + moved.rstrip("\n") + "\n"

    # Take it out of the original and import it back in its place.
    remaining = body.replace(moved, "", 1)
    remaining = re.sub(r"\n{4,}", "\n\n\n", remaining)
    return {
        "name": name,
        "module": module,
        "new_body": new_body,
        "remaining": remaining,
        "imports_back": constants,
        "lines": node.end_lineno - node.lineno + 1,
    }


def extract(path, name, into=None, verify=None):
    """Move one class into its own module. Returns (ok, message).

    `verify` is called with no arguments after the files are written and must
    return True if the project still works. Anything else and both files go
    back exactly as they were -- a split that breaks the build is worse than
    no split, and this runs unattended.
    """
    plan = plan_extraction(path, name)
    if not plan:
        return False, "cannot move %s safely" % name

    folder = os.path.dirname(path)
    target = into or os.path.join(folder, "%s.py" % _snake(name))
    if os.path.exists(target):
        return False, "%s already exists" % os.path.basename(target)

    before = read(path)
    # The old file imports what just left it.
    line = "from %s import %s\n" % (os.path.splitext(os.path.basename(target))[0], name)
    remaining = _add_import(plan["remaining"], line)

    write(target, plan["new_body"])
    write(path, remaining)

    if verify and not verify():
        write(path, before)
        os.remove(target)
        return False, "moving %s broke it -- put back" % name
    return True, "moved %s (%d lines) into %s" % (name, plan["lines"],
                                                  os.path.basename(target))


def _unsafe_method(node):
    """Why this method cannot leave its class, or '' if it can.

    A method body works unchanged as a plain function that takes the instance
    as a parameter named `self` -- almost always. These are the exceptions,
    each of which would compile fine and break at the first call.
    """
    if node.decorator_list:
        return "it is decorated"
    if isinstance(node, ast.AsyncFunctionDef):
        return "it is async"
    if node.name.startswith("__") and node.name.endswith("__"):
        return "it is a special method"
    if not node.args.args or node.args.args[0].arg != "self":
        return "its first parameter is not self"
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                and sub.func.id == "super" and not sub.args:
            return "it calls super() with no arguments"
        if isinstance(sub, ast.Name) and sub.id == "__class__":
            return "it uses __class__"
        if isinstance(sub, ast.Attribute) and sub.attr.startswith("__") \
                and not sub.attr.endswith("__"):
            return "it uses a name-mangled attribute"      # self.__x stops mangling
        if isinstance(sub, (ast.Global, ast.Nonlocal)):
            return "it rebinds a global"
    return ""


def method_candidates(path, min_tokens=800):
    """Methods worth moving out, largest first. Returns [(class, method, tokens)].

    For the case class extraction cannot reach: a single class too big to fit
    alongside its own reply, whose methods refer to everything else so the
    class cannot move as a whole. On 2026-09-21 that was Game at 12,600
    tokens, and two of its nine methods were 80% of it.
    """
    body = read(path)
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    defined = _module_names(tree)
    bound = set()
    for _, names in _imports(tree):
        bound |= names
    out = []
    for klass in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for node in klass.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            size = len(_segment(body, node)) // 4
            if size < min_tokens or _unsafe_method(node):
                continue
            used = _names_used(node)
            # Anything it needs from this file, other than by import, would
            # have to be imported back from here: a cycle. Imported names are
            # fine -- the new module imports them from where they really live.
            if {n for n in used if n in defined and n not in bound}:
                continue
            out.append((klass.name, node.name, size))
    out.sort(key=lambda row: -row[2])
    return out


def _call_for(args):
    """The argument list that forwards a signature unchanged, minus self."""
    parts = [a.arg for a in args.posonlyargs + args.args][1:]
    if args.vararg:
        parts.append("*" + args.vararg.arg)
    elif args.kwonlyargs:
        pass
    parts += ["%s=%s" % (a.arg, a.arg) for a in args.kwonlyargs]
    if args.kwarg:
        parts.append("**" + args.kwarg.arg)
    return ", ".join(["self"] + parts)


def extract_method(path, class_name, method_name, verify=None):
    """Move one method's body into its own module. Returns (ok, message).

    The body goes into `<class>_<method>.py` as a plain function that still
    takes `self`, so not a line of it changes. The class keeps the method,
    reduced to one line that calls the moved function with the same
    arguments, so every caller in the project works as before. Checked by
    `verify`, and both files put back if it fails.
    """
    body = read(path)
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False, "will not parse"
    klass = next((n for n in tree.body
                  if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    node = next((n for n in (klass.body if klass else [])
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == method_name), None)
    if node is None:
        return False, "no %s.%s" % (class_name, method_name)
    why = _unsafe_method(node)
    if why:
        return False, "cannot move %s.%s: %s" % (class_name, method_name, why)

    used = _names_used(node)
    keep = [_segment(body, imp).rstrip("\n") for imp, names in _imports(tree)
            if names & used]
    module = "%s_%s" % (_snake(class_name), method_name.strip("_"))
    target = os.path.join(os.path.dirname(path), module + ".py")
    if os.path.exists(target):
        return False, "%s already exists" % os.path.basename(target)

    lines = body.splitlines(keepends=True)
    segment = "".join(lines[node.lineno - 1:node.end_lineno])
    indent = len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())
    dedented = "".join(l[indent:] if l[:indent].strip() == "" else l
                       for l in segment.splitlines(keepends=True))
    header = ('"""`%s.%s`, moved out of %s by LocalCoder to keep that file small.\n\n'
              'The class still has a %s() that calls this, so nothing that uses it\n'
              'changed. `self` is the %s instance. Edit the code here.\n"""\n\n'
              % (class_name, method_name, os.path.basename(path), method_name, class_name))
    new_body = header + "\n".join(keep) + ("\n\n\n" if keep else "") + dedented.rstrip("\n") + "\n"

    pad = " " * indent
    stub = ("%sdef %s(%s):\n%s    return %s.%s(%s)\n"
            % (pad, method_name, ast.unparse(node.args), pad, module, method_name,
               _call_for(node.args)))
    remaining = "".join(lines[:node.lineno - 1]) + stub + "".join(lines[node.end_lineno:])
    remaining = _add_import(remaining, "import %s\n" % module)

    write(target, new_body)
    write(path, remaining)
    if verify and not verify():
        write(path, body)
        os.remove(target)
        return False, "moving %s.%s broke it -- put back" % (class_name, method_name)
    return True, "moved %s.%s (%d lines) into %s" % (
        class_name, method_name, node.end_lineno - node.lineno + 1, os.path.basename(target))


def _add_import(body, line):
    """Put the import after the existing ones, not at the very top."""
    lines = body.splitlines(keepends=True)
    last = 0
    for i, text in enumerate(lines[:40]):
        if re.match(r"^(import|from)\s", text):
            last = i + 1
    return "".join(lines[:last]) + line + "".join(lines[last:])


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
