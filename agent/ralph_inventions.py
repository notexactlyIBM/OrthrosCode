"""Attributes the code reads that nothing ever creates.

The failure these catch has no other symptom until it happens in front of a
user: a round writes `self.frame_surface.blit(self.parallax_clouds_surf, ...)`
against a surface no round ever created. It parses. It often survives the
smoke run too, because the line sits inside a branch that only runs later.

Both checks read the syntax tree rather than the text, and both would rather
miss an invention than cry wolf: a false alarm becomes a task-list item the
next round wastes itself on, and teaches the model to ignore the check.
"""

import ast
import os

from ralph_common import read_text


def _parse(files):
    trees = {}
    for path in files:
        if not path.lower().endswith(".py") or not os.path.isfile(path):
            continue
        try:
            trees[path] = ast.parse(read_text(path))
        except (SyntaxError, ValueError):
            continue
    return trees


def _self_attrs(node, ctx):
    """Names of `self.<name>` under node with the given context (Load/Store)."""
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute) and isinstance(sub.ctx, ctx)
                and isinstance(sub.value, ast.Name) and sub.value.id == "self"):
            yield sub.attr


def _class_names(klass):
    """What a class defines in its own body: methods, properties, class attributes."""
    names = set()
    for item in klass.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(item.name)
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            names.add(item.target.id)
    return names


def _dynamic(klass):
    """True if the class creates attributes in ways a reader cannot see."""
    for sub in ast.walk(klass):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and sub.name in ("__getattr__", "__getattribute__"):
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                and sub.func.id == "setattr":
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == "__dict__":
            return True
    return False


def _base_names(klass):
    out = []
    for base in klass.bases:
        if isinstance(base, ast.Name):
            out.append(base.id)
        elif isinstance(base, ast.Attribute):
            out.append(base.attr)
        else:
            out.append("?")
    return out


def _outsiders(trees):
    """Classes that inherit from outside the project, directly or not.

    A subclass of a project class that subclasses `unittest.TestCase` is as
    much a stranger's child as the parent is: whatever the base provides is
    invisible here either way. Missing that cost real rounds -- every test
    class two levels down had `self.assertEqual` reported as invented, and
    the agents "fixed" it by aliasing assert methods into their own classes.
    """
    bases = {}
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases.setdefault(node.name, []).extend(_base_names(node))
    project = set(bases)
    outside = {name for name, parents in bases.items()
               if any(b != "object" and b not in project for b in parents)}
    growing = True
    while growing:                      # inherited from a parent that is one
        growing = False
        for name, parents in bases.items():
            if name not in outside and any(b in outside for b in parents):
                outside.add(name)
                growing = True
    return project, outside


def phantom_attributes(files):
    """Attributes read on `self` that nothing in the project assigns.

    Returns [(file, name)].

    Definitions are pooled across every file and every class. Once a big
    method has been moved into a module of its own, the attributes it reads
    are assigned back in the class's __init__, in another file -- and mixins
    read what the class they are mixed into assigns.

    Classes that inherit from something outside the project are skipped: a
    `threading.Thread` subclass reading `self.name` or a tkinter frame reading
    `self.master` is using what its base provides, which this cannot see.
    """
    trees = _parse(files)
    project, outside = _outsiders(trees)
    defined = set()
    readers = []                   # (path, node whose reads count)
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                defined |= _class_names(node)
                defined.update(_self_attrs(node, ast.Store))
                if node.name not in outside and not _dynamic(node):
                    readers.append((path, node))
        # Methods moved out of their class live on as module-level functions
        # whose first parameter is still `self`.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.args.args \
                    and node.args.args[0].arg == "self":
                defined.update(_self_attrs(node, ast.Store))
                readers.append((path, node))
    found = []
    seen = set()
    for path, node in readers:
        for name in sorted(set(_self_attrs(node, ast.Load)) - defined):
            if (path, name) not in seen:
                seen.add((path, name))
                found.append((path, name))
    return found


def _calls_parent_init(stmt):
    for sub in ast.walk(stmt):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "__init__":
            return True
    return False


def _reads_now(stmt):
    """`self.x` reads that run when this statement runs -- not ones inside a
    nested function, lambda or class, which run later if at all."""
    stack = [stmt]
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)) \
                and node is not stmt:
            continue
        if (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name) and node.value.id == "self"):
            yield node.attr
        stack.extend(ast.iter_child_nodes(node))


def used_before_set(files):
    """Attributes read earlier in __init__ than they are assigned.

    Returns [(file, class, name)].

    The other half of the invented-attribute problem, and the half that hides
    better. Found in a real project on 2026-08-14:

        self.damage_radius = game.weapons[self.weapon_type][...]   # line 17
        self.weapon_type = weapon_type                             # line 19

    It parses, flake8 passes it, the name is plainly assigned so the phantom
    check passes it, and the object cannot be built.

    Constructors only, and only statement order within them. Once the parent's
    __init__ has been called, anything a project class assigns counts as set,
    and a class whose base is outside the project is skipped altogether --
    what its base sets up is invisible here.
    """
    trees = _parse(files)
    project, outside = _outsiders(trees)
    class_level = set()
    stored_anywhere = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_level |= _class_names(node)
                stored_anywhere.update(_self_attrs(node, ast.Store))
    found = []
    for path, tree in trees.items():
        for klass in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            if klass.name in outside:
                continue
            init = next((n for n in klass.body
                         if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
            if not init:
                continue
            assigned = set(class_level)
            for stmt in init.body:
                # Reads first: within one statement the right-hand side runs
                # before the assignment lands.
                for name in _reads_now(stmt):
                    if name not in assigned:
                        found.append((path, klass.name, name))
                        assigned.add(name)          # report each name once
                assigned.update(_self_attrs(stmt, ast.Store))
                if _calls_parent_init(stmt):
                    assigned |= stored_anywhere
    return found
