"""Orthros's dashboard as a window of its own: tkinter, no browser.

A client of the same local API the web page uses (127.0.0.1:<port>), so it
shows and does what the page does. Closing it leaves Orthros running; run
ORTHROS.bat again to bring it back. The web page stays at the same address for
anyone who wants it.

Two rules carry the look: what can be pressed is solid and coloured, what only
reports is flat -- and the state that matters most is the loudest thing there.

Standard library only, like orthros.py.

    pythonw orthros_gui.py --port 8770
"""

import argparse
import json
import math
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import tkinter as tk
from tkinter import filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))

BG, PANEL, PANEL2, EDGE = "#070b13", "#0d1524", "#121c30", "#23324d"
INK, DIM, FAINT, TRACK = "#e8f1ff", "#8a9cbb", "#55657f", "#1a2438"
A_C, B_C, GOOD, BAD, WARN, SERVE = "#5aa9ff", "#c38bff", "#2ee6a6", "#ff5d6c", "#ffb547", "#22e1ff"
MODE_COLOR = {"self": A_C, "task": B_C, "serve": SERVE}
MODE_TINT = {"self": "#12305a", "task": "#32205a", "serve": "#0b3a47"}
MODES = {"self": "Evolving", "task": "Working on a task", "serve": "Serving the network"}
PHASES = {"idle": "Idle", "paused": "Paused", "running": "Running", "handover": "Handing over",
          "serving": "Serving", "error": "Needs attention"}
PHASE_COLOR = {"serving": SERVE, "running": GOOD, "handover": WARN, "error": BAD}
OUTCOME_COLOR = {"kept": GOOD, "rejected by reviewer": WARN, "edit did not apply": "#94a3b8",
                 "broke a check": BAD, "caught by a check": "#fb923c", "no change": "#2a3650"}
KIND_COLOR = {"good": GOOD, "bad": BAD, "handover": WARN, "start": A_C}

DISPLAY, BODY, MONO = "Bahnschrift", "Segoe UI", "Consolas"
BUTTONS = {                       # background, text, background under the pointer
    "primary": ("#1fb8e0", "#03141f", "#4ccff2"),
    "secondary": ("#1b2d4a", "#d8ecff", "#28446e"),
    "start": ("#22c98a", "#02160f", "#40e0a3"),
    "stop": ("#d8374e", "#ffffff", "#ea5367"),
    "stopping": ("#e9a126", "#231500", "#e9a126"),
    "link": (PANEL, BAD, PANEL),
}


ZOOM = 1.0                        # screen pixels per 96-dpi pixel, set when the window opens


def px(n):
    return int(round(n * ZOOM))


def fmt_n(n):
    n = n or 0
    return "%.1fM" % (n / 1e6) if n >= 1e6 else "%dk" % round(n / 1e3) if n >= 1e3 else str(n)


def fmt_left(s):
    s = max(0, int(s))
    m = s // 60
    return "%dh %dm" % (m // 60, m % 60) if m >= 60 else "%d min" % m if m >= 5 else \
        "%d:%02d" % (m, s % 60)


def fmt_t(s):
    s = max(0, int(s or 0))
    return "%dh %dm" % (s // 3600, s % 3600 // 60) if s >= 3600 else "%dm" % (s // 60)


def hhmm(t):
    return time.strftime("%H:%M", time.localtime(t or 0))


class Api:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port

    def get(self, path, timeout=10):
        with urllib.request.urlopen(self.base + path, timeout=timeout) as resp:
            return json.loads(resp.read())

    def post(self, path, body=None, timeout=900):
        req = urllib.request.Request(self.base + path, json.dumps(body or {}).encode("utf-8"),
                                     {"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read())
            except ValueError:
                return {"error": str(exc)}
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}


# ------------------------------------------------------------------ small parts

def label(parent, text="", fg=INK, font=(BODY, 10), **kw):
    return tk.Label(parent, text=text, fg=fg, bg=kw.pop("bg", parent["bg"]), font=font, **kw)


def paint(button, kind):
    bg, fg, hover = BUTTONS[kind]
    button.kind, button.normal, button.hover = kind, bg, hover
    button.config(bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                  disabledforeground="#5f6f8a" if kind != "stopping" else fg)


def button(parent, text, command, kind="secondary", font=(DISPLAY, 10, "bold"), **kw):
    b = tk.Button(parent, text=text, command=command, relief="flat", bd=0, cursor="hand2",
                  font=font, padx=kw.pop("padx", 12), pady=kw.pop("pady", 5),
                  highlightthickness=0, **kw)
    paint(b, kind)
    b.bind("<Enter>", lambda e: b["state"] != "disabled" and b.config(bg=b.hover))
    b.bind("<Leave>", lambda e: b["state"] != "disabled" and b.config(bg=b.normal))
    return b


def enable(b, on):
    """A button that cannot be pressed now goes flat, so it stops looking pressable."""
    b.config(state="normal" if on else "disabled", bg=b.normal if on else TRACK,
             cursor="hand2" if on else "arrow")


def panel(parent):
    return tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground="#18233a",
                    padx=16, pady=14)


def heading(parent, text, tip=None):
    row = tk.Frame(parent, bg=parent["bg"])
    tk.Frame(row, bg=SERVE, width=3, height=12).pack(side="left", padx=(0, 8))
    label(row, text.upper(), DIM, (DISPLAY, 9, "bold")).pack(side="left")
    if tip:
        mark = label(row, " ? ", FAINT, (DISPLAY, 8, "bold"), bg=TRACK, cursor="question_arrow")
        mark.pack(side="left", padx=6)
        Tip(mark, tip)
    return row


def readonly(text_widget, fill):
    text_widget.config(state="normal")
    text_widget.delete("1.0", "end")
    fill(text_widget)
    text_widget.config(state="disabled")


class Tip:
    """Words that show when the pointer rests on a widget."""

    def __init__(self, widget, text):
        self.widget, self.text, self.top = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _e=None):
        if self.top or not self.text:
            return
        self.top = tk.Toplevel(self.widget)
        self.top.wm_overrideredirect(True)
        self.top.configure(bg=INK)
        tk.Label(self.top, text=self.text, bg=INK, fg="#06101f", font=(BODY, 9), justify="left",
                 wraplength=340, padx=10, pady=8).pack()
        x, y = self.widget.winfo_rootx(), self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.top.wm_geometry("+%d+%d" % (x, y))

    def hide(self, _e=None):
        if self.top:
            self.top.destroy()
            self.top = None


class Tile(tk.Frame):
    """One of the three modes: a big pressable tile, lit when chosen."""

    def __init__(self, parent, glyph, title, sub, mode, command):
        super().__init__(parent, bg=PANEL2, highlightthickness=2, highlightbackground=EDGE,
                         cursor="hand2", padx=12, pady=10)
        self.mode, self.on = mode, None
        self.glyph = label(self, glyph, MODE_COLOR[mode], (BODY, 17))
        self.mark = label(self, "", MODE_COLOR[mode], (DISPLAY, 7, "bold"), anchor="ne")
        self.title = label(self, title.upper(), INK, (DISPLAY, 11, "bold"), anchor="w",
                           justify="left")
        self.sub = label(self, sub, DIM, (BODY, 9), anchor="w", justify="left")
        self.glyph.grid(row=0, column=0, sticky="w")
        self.mark.grid(row=0, column=1, sticky="ne")
        self.title.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.sub.grid(row=2, column=0, columnspan=2, sticky="w")
        self.columnconfigure(1, weight=1)
        self.bind("<Configure>", lambda e: (self.title.config(wraplength=e.width - px(28)),
                                            self.sub.config(wraplength=e.width - px(28))))
        for w in (self, self.glyph, self.title, self.sub, self.mark):
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self.config(highlightbackground=MODE_COLOR[mode]))
            w.bind("<Leave>", lambda e: self.config(
                highlightbackground=MODE_COLOR[mode] if self.on else EDGE))
        self.set(False)

    def set(self, on):
        if on == self.on:
            return
        self.on = on
        bg = MODE_TINT[self.mode] if on else PANEL2
        for w in (self, self.glyph, self.title, self.sub, self.mark):
            w.config(bg=bg)
        self.config(highlightbackground=MODE_COLOR[self.mode] if on else EDGE)
        self.mark.config(text="SELECTED" if on else "")
        self.sub.config(fg="#dbe9ff" if on else DIM)


class Readout(tk.Frame):
    """A number and what it counts: flat, nothing to press."""

    def __init__(self, parent, name, tip=None):
        super().__init__(parent, bg=parent["bg"])
        self.value = label(self, "0", INK, (DISPLAY, 20, "bold"), anchor="w")
        self.value.pack(anchor="w")
        row = tk.Frame(self, bg=self["bg"])
        row.pack(anchor="w")
        self.name = label(row, name.upper(), DIM, (DISPLAY, 8, "bold"))
        self.name.pack(side="left")
        if tip:
            mark = label(row, " ? ", FAINT, (DISPLAY, 7, "bold"), bg=TRACK)
            mark.pack(side="left", padx=4)
            Tip(mark, tip)

    def set(self, value, color=INK):
        self.value.config(text=str(value), fg=color)


# ------------------------------------------------------------------ the window

class Dashboard:
    def __init__(self, port):
        self.api = Api(port)
        self.port = port
        self.inbox = queue.Queue()       # (callback, value) from the threads that talk to Orthros
        self.d = None
        self.want_task = False
        self.minutes_touched = False
        self.open_reqs = set()
        self.shown = {}                  # what each rebuilt list last showed
        self.tab = "operate"
        self.seen_bad = time.time()
        self.term = {"agent": None, "file": "", "offset": -1}
        self.term_open = False
        self.chat_busy = False

        self.root = tk.Tk()
        global ZOOM
        ZOOM = float(self.root.tk.call("tk", "scaling")) / (96 / 72)
        self.root.title("Orthros")
        self.root.configure(bg=BG)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = min(sw - px(40), px(1560)), min(sh - px(90), px(1040))
        self.root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, px(10)))
        self.root.minsize(px(1100), px(760))
        self.root.iconphoto(True, self.icon())
        self.build()
        threading.Thread(target=self.poll_state, daemon=True).start()
        self.root.after(100, self.pump)
        self.root.after(50, self.draw_gpu)
        self.root.after(1000, self.poll_term)

    # -------------------------------------------------------------- plumbing

    def icon(self):
        img = tk.PhotoImage(width=32, height=32)
        img.put(PANEL, to=(0, 0, 32, 32))
        for cx, color in ((11, A_C), (21, B_C)):
            for x in range(32):
                for y in range(32):
                    if (x - cx) ** 2 + (y - 16) ** 2 <= 25:
                        img.put(color, (x, y))
        return img

    def later(self, work, then=None):
        """Run `work` off the window's thread; hand its result to `then` on it."""
        def run():
            result = work()
            if then:
                self.inbox.put((then, result))
        threading.Thread(target=run, daemon=True).start()

    def pump(self):
        try:
            while True:
                then, value = self.inbox.get_nowait()
                try:
                    then(value)
                except Exception as exc:                  # a bad render must not stop the window
                    self.banner.config(text="Display error: %s" % exc)
                    self.banner.pack(fill="x", before=self.tabs)
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    def poll_state(self):
        """Every 2 s. Once Orthros has answered, ten quiet seconds mean it was closed, and
        its window goes with it; the next ORTHROS.bat opens a new one."""
        seen, quiet = False, 0
        while True:
            try:
                self.inbox.put((self.render, self.api.get("/api/state")))
                seen, quiet = True, 0
            except Exception as exc:
                quiet += 1
                self.inbox.put((self.render_down, str(exc)))
                if seen and quiet >= 5:
                    self.inbox.put((lambda _v: self.root.destroy(), None))
                    return
            time.sleep(2)

    def refresh(self):
        self.later(lambda: self.api.get("/api/state"), self.render)

    # -------------------------------------------------------------- layout

    def build(self):
        top = tk.Frame(self.root, bg=BG, padx=20, pady=12)
        top.pack(fill="x")
        dots = tk.Canvas(top, width=30, height=14, bg=BG, highlightthickness=0)
        dots.create_oval(1, 1, 13, 13, fill=A_C, outline="")
        dots.create_oval(16, 1, 28, 13, fill=B_C, outline="")
        dots.pack(side="left", padx=(0, 10))
        label(top, "ORTHROS", INK, (DISPLAY, 17, "bold")).pack(side="left")
        self.sub = label(top, "", DIM, (DISPLAY, 10, "bold"))
        self.sub.pack(side="left", padx=14)
        self.pill = label(top, "...", DIM, (DISPLAY, 10, "bold"), bg=PANEL2, padx=14, pady=4)
        self.pill.pack(side="right")
        tk.Frame(self.root, bg="#18233a", height=1).pack(fill="x")

        self.banner = label(self.root, "", "#ffd3d8", (BODY, 10, "bold"), bg="#3a0f18",
                            justify="left", anchor="w", padx=20, pady=10, wraplength=1300)
        self.tabs = tk.Frame(self.root, bg=BG, padx=20)
        self.tabs.pack(fill="x", pady=(8, 0))
        self.tab_buttons = {}
        for key, name in (("operate", "OPERATE"), ("diag", "DIAGNOSTICS")):
            col = tk.Frame(self.tabs, bg=BG)
            col.pack(side="left", padx=(0, 6))
            b = tk.Button(col, text=name, relief="flat", bd=0, bg=BG, fg=DIM, cursor="hand2",
                          activebackground=BG, activeforeground=INK, font=(DISPLAY, 10, "bold"),
                          padx=14, pady=6, command=lambda k=key: self.show_tab(k))
            b.pack()
            bar = tk.Frame(col, bg=BG, height=2)
            bar.pack(fill="x")
            self.tab_buttons[key] = (b, bar)
        self.diag_dot = label(self.tabs, "●", BAD, (BODY, 8), bg=BG)

        self.pages = {"operate": tk.Frame(self.root, bg=BG, padx=20, pady=14),
                      "diag": tk.Frame(self.root, bg=BG, padx=20, pady=14)}
        self.build_operate(self.pages["operate"])
        self.build_diag(self.pages["diag"])
        self.show_tab("operate")

    def show_tab(self, key):
        self.tab = key
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True)
        for k, (b, bar) in self.tab_buttons.items():
            b.config(fg=INK if k == key else DIM)
            bar.config(bg=SERVE if k == key else BG)
        if key == "diag":
            self.seen_bad = time.time()
            self.diag_dot.pack_forget()

    # ---- operate

    def build_operate(self, page):
        page.columnconfigure(0, weight=1, uniform="half")
        page.columnconfigure(1, weight=1, uniform="half")
        page.rowconfigure(0, weight=1)

        ops = panel(page)
        ops.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.ops = ops
        modes = tk.Frame(ops, bg=PANEL)
        modes.pack(fill="x")
        self.tiles = {}
        for i, (mode, glyph, title, sub) in enumerate((
                ("self", "⟲", "Evolve", "A and B improve each other"),
                ("task", "☑", "Work on a task", "Both build one project"),
                ("serve", "◉", "Serve the network", "The card answers other machines"))):
            tile = Tile(modes, glyph, title, sub, mode, lambda m=mode: self.pick_mode(m))
            tile.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            modes.columnconfigure(i, weight=1, uniform="tile")
            self.tiles[mode] = tile

        # The big button sizes to its words, with the two lesser stops stacked
        # beside it; what it is doing, and the settings, each get a whole line.
        # Side by side in one row they ran off the panel's edge on a narrow window.
        go_row = tk.Frame(ops, bg=PANEL)
        go_row.pack(fill="x", pady=(16, 0))
        self.go = button(go_row, "START", self.go_pressed, "start", font=(DISPLAY, 14, "bold"),
                         padx=22, pady=14)
        self.go.pack(side="left", fill="y")
        self.stops = tk.Frame(go_row, bg=PANEL)
        self.stop_round = button(self.stops, "Stop after this round",
                                 lambda: self.post("/api/stop"), font=(DISPLAY, 9, "bold"))
        self.stop_round.pack(fill="x")
        self.force = button(self.stops, "FORCE STOP", self.force_stop, "link",
                            font=(DISPLAY, 9, "bold"))
        self.force.pack(fill="x", pady=(6, 0))
        self.headline = label(ops, "", INK, (DISPLAY, 13, "bold"), anchor="w", justify="left",
                              wraplength=px(420))
        self.headline.pack(fill="x", pady=(12, 0))
        self.headline.bind("<Configure>", lambda e: self.headline.config(
            wraplength=e.width - px(8)))
        ctl = tk.Frame(ops, bg=PANEL)
        ctl.pack(fill="x", pady=(8, 0))
        self.settings_row = ctl
        self.turns_box = tk.Frame(ctl, bg=PANEL)
        label(self.turns_box, "turns of", DIM, (BODY, 9)).pack(side="left")
        self.minutes = tk.Spinbox(self.turns_box, from_=5, to=480, increment=5, width=4,
                                  bg="#050a14", fg=INK, buttonbackground=PANEL2, relief="flat",
                                  insertbackground=INK, font=(BODY, 10),
                                  command=self.minutes_changed)
        self.minutes.bind("<KeyRelease>", lambda e: setattr(self, "minutes_touched", True))
        self.minutes.bind("<Return>", lambda e: self.minutes_changed())
        self.minutes.pack(side="left", padx=4)
        label(self.turns_box, "min   first", DIM, (BODY, 9)).pack(side="left")
        self.first = tk.StringVar(value="A")
        first_menu = tk.OptionMenu(self.turns_box, self.first, "A", "B")
        first_menu.config(bg=PANEL2, fg=INK, activebackground="#28446e", activeforeground=INK,
                          relief="flat", highlightthickness=0, bd=0, font=(BODY, 9))
        first_menu["menu"].config(bg=PANEL2, fg=INK, font=(BODY, 9))
        first_menu.pack(side="left", padx=4)
        self.turns_box.pack(side="left")
        self.practice_box = tk.Frame(ctl, bg=PANEL)
        label(self.practice_box, "practice every", DIM, (BODY, 9)).pack(side="left")
        self.practice = tk.Spinbox(self.practice_box, from_=0, to=50, width=3, bg="#050a14",
                                   fg=INK, buttonbackground=PANEL2, relief="flat",
                                   font=(BODY, 10), command=self.practice_changed)
        self.practice.bind("<Return>", lambda e: self.practice_changed())
        self.practice.pack(side="left", padx=4)
        label(self.practice_box, "turns", DIM, (BODY, 9)).pack(side="left")
        mark = label(self.practice_box, " ? ", FAINT, (DISPLAY, 8, "bold"), bg=TRACK)
        mark.pack(side="left", padx=8)
        Tip(mark, "A works on B's code, then B on A's. Every few turns an agent does a practice "
                  "exercise instead: a job it has never seen, scored by tests it never sees. "
                  "0 turns practice off.\n\nEvery few good turns each version is also scored on "
                  "held-out exercises; a version that does worse is rolled back.")
        self.mode_note = label(ops, "", WARN, (DISPLAY, 9, "bold"), anchor="w")
        self.mode_note.pack(fill="x", pady=(6, 0))

        tk.Frame(ops, bg="#18233a", height=1).pack(fill="x", pady=(10, 12))
        self.panes = {"self": tk.Frame(ops, bg=PANEL), "task": tk.Frame(ops, bg=PANEL),
                      "serve": tk.Frame(ops, bg=PANEL)}
        self.build_self_pane(self.panes["self"])
        self.build_task_pane(self.panes["task"])
        self.build_serve_pane(self.panes["serve"])
        self.build_turn_feed(ops)
        self.pane_shown = None

        side = tk.Frame(page, bg=BG)
        side.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self.build_gpu(side)
        self.build_chat(side)

        agents = tk.Frame(page, bg=BG)
        agents.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        heading(agents, "The agents").pack(anchor="w", pady=(0, 8))
        row = tk.Frame(agents, bg=BG)
        row.pack(fill="x")
        row.columnconfigure(0, weight=1, uniform="agent")
        row.columnconfigure(2, weight=1, uniform="agent")
        self.cards = {}
        for i, (name, color) in enumerate((("A", A_C), ("B", B_C))):
            card = AgentCard(row, name, color, self)
            card.grid(row=0, column=i * 2, sticky="nsew")
            self.cards[name] = card
        self.swap = label(row, "⇆", FAINT, (BODY, 18), bg=BG)
        self.swap.grid(row=0, column=1, padx=10)

    def build_self_pane(self, pane):
        self.self_summary = label(pane, "", DIM, (BODY, 9), anchor="w", justify="left")
        self.self_summary.pack(fill="x")
        self.self_summary.bind("<Configure>", lambda e: self.self_summary.config(
            wraplength=e.width - px(8)))

    def build_turn_feed(self, ops):
        """The running turn, round by round, in the agent's own words: its loop's log
        lines, never the model's. Fills what Evolve and a task leave of the panel."""
        box = tk.Frame(ops, bg=PANEL)
        self.turn_feed = box
        self.feed_title = heading(box, "This turn")
        self.feed_title.pack(anchor="w", pady=(12, 6))
        self.feed = tk.Text(box, height=4, bg=PANEL, fg="#b7c6de", relief="flat", wrap="word",
                            font=(BODY, 9), highlightthickness=0, spacing3=3, cursor="arrow")
        self.feed.pack(fill="both", expand=True)
        self.feed.tag_config("time", foreground=FAINT, font=(MONO, 8))
        self.feed.tag_config("round", foreground=INK, font=(DISPLAY, 9, "bold"), spacing1=6)
        for name, color in (("good", GOOD), ("warn", WARN), ("bad", BAD)):
            self.feed.tag_config(name, foreground=color)
        self.feed.config(state="disabled")
        self.feed_lines, self.feed_turn = [], None

    def build_task_pane(self, pane):
        row = tk.Frame(pane, bg=PANEL)
        row.pack(fill="x")
        label(row, "Task", DIM, (BODY, 9)).pack(side="left")
        self.task_var = tk.StringVar(value="")
        self.task_menu = tk.OptionMenu(row, self.task_var, "")
        self.task_menu.config(bg=PANEL2, fg=INK, activebackground="#28446e", activeforeground=INK,
                              relief="flat", highlightthickness=0, bd=0, font=(BODY, 9), width=24)
        self.task_menu["menu"].config(bg=PANEL2, fg=INK, font=(BODY, 9))
        self.task_menu.pack(side="left", padx=6)
        button(row, "New task", self.toggle_new_task, font=(DISPLAY, 9, "bold")).pack(side="left")
        self.task_info = label(row, "", DIM, (BODY, 9))
        self.task_info.pack(side="left", padx=10)
        self.task_keys = None

        form = tk.Frame(pane, bg=PANEL)
        self.new_task = form
        label(form, "Name", DIM, (BODY, 9)).pack(anchor="w", pady=(10, 2))
        self.task_name = tk.Entry(form, bg="#050a14", fg=INK, insertbackground=INK, relief="flat",
                                  font=(BODY, 10))
        self.task_name.pack(fill="x", ipady=4)
        label(form, "What should it build? What goes in, what comes out, how to check it works.",
              DIM, (BODY, 9)).pack(anchor="w", pady=(8, 2))
        self.task_brief = tk.Text(form, height=4, bg="#050a14", fg=INK, insertbackground=INK,
                                  relief="flat", font=(BODY, 10), wrap="word")
        self.task_brief.pack(fill="x")
        label(form, "Folder to work on -- empty for a new one under tasks\\. An existing folder "
                    "must be a git repository; the agents work on a copy of it on a branch of "
                    "their own, and nothing in it changes until you merge.",
              DIM, (BODY, 9), justify="left", wraplength=600).pack(anchor="w", pady=(8, 2))
        folder_row = tk.Frame(form, bg=PANEL)
        folder_row.pack(fill="x")
        self.task_folder = tk.Entry(folder_row, bg="#050a14", fg=INK, insertbackground=INK,
                                    relief="flat", font=(BODY, 10))
        self.task_folder.pack(side="left", fill="x", expand=True, ipady=4)
        button(folder_row, "Browse...", self.browse, font=(DISPLAY, 9, "bold")).pack(
            side="left", padx=(6, 0))
        actions = tk.Frame(form, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        button(actions, "Create task", self.create_task, "primary").pack(side="left")
        button(actions, "Cancel", self.toggle_new_task).pack(side="left", padx=6)
        self.task_msg = label(actions, "", DIM, (BODY, 9), wraplength=400, justify="left")
        self.task_msg.pack(side="left", padx=6)

    def build_serve_pane(self, pane):
        stats = tk.Frame(pane, bg=PANEL)
        stats.pack(fill="x")
        self.readouts = {}
        for i, (key, name, tip) in enumerate((
                ("served", "answered", None),
                ("gave_up", "gave up", "Callers that stopped waiting before their answer came: "
                                       "their timeout was shorter than the model took."),
                ("failed", "failed", None),
                ("refused", "turned away", "Answered 503: A and B were building a tool. Callers "
                                           "are told when to come back."),
                ("denied", "wrong key", None),
                ("tokens", "tokens", None))):
            r = Readout(stats, name, tip)
            r.grid(row=i // 3, column=i % 3, sticky="w", pady=(0, 10))
            stats.columnconfigure(i % 3, weight=1, uniform="stat")
            self.readouts[key] = r

        # The connect details and the tools line keep their place; the list takes what is left.
        box = tk.Frame(pane, bg=PANEL)
        self.connect = box
        self.connect_toggle = button(pane, "▸  CONNECT ANOTHER MACHINE",
                                     self.toggle_connect, font=(DISPLAY, 9, "bold"))
        self.connect_toggle.pack(side="bottom", anchor="w", pady=(10, 0))
        self.tools_line = label(pane, "", DIM, (BODY, 9), anchor="w", justify="left")
        self.tools_line.pack(side="bottom", fill="x", pady=(8, 0))
        self.tools_line.bind("<Configure>", lambda e: self.tools_line.config(
            wraplength=e.width - px(8)))
        heading(pane, "What was asked").pack(anchor="w", pady=(6, 6))
        self.reqs = tk.Text(pane, height=4, bg=PANEL, fg=INK, relief="flat", wrap="word",
                            font=(BODY, 9), cursor="arrow", padx=0, pady=0, spacing1=2,
                            spacing3=6, highlightthickness=0)
        self.reqs.pack(fill="both", expand=True)
        self.reqs.tag_config("time", foreground=FAINT, font=(DISPLAY, 9, "bold"))
        self.reqs.tag_config("tag", foreground=INK, font=(BODY, 10, "bold"))
        self.reqs.tag_config("words", foreground=FAINT, lmargin1=px(48), lmargin2=px(48))
        self.reqs.tag_config("open", foreground="#b7c6de", lmargin1=px(48), lmargin2=px(48))
        for name, color in (("ok", GOOD), ("no", WARN), ("bad", BAD)):
            self.reqs.tag_config(name, foreground=color, font=(DISPLAY, 8, "bold"))
        self.reqs.config(state="disabled")
        self.conn_fields = {}
        for key, name in (("api", "OpenAI API"), ("mcp", "MCP"), ("key", "Key"),
                          ("rule", "Firewall rule, on this PC, once, as administrator"),
                          ("env", "Settings for the other machine")):
            label(box, name.upper(), DIM, (DISPLAY, 8, "bold")).pack(anchor="w", pady=(8, 2))
            row = tk.Frame(box, bg=PANEL)
            row.pack(fill="x")
            field = tk.Entry(row, bg="#050a14", fg="#cfe6ff", readonlybackground="#050a14",
                             relief="flat", font=(MONO, 9))
            field.pack(side="left", fill="x", expand=True, ipady=3)
            button(row, "Copy", lambda f=field: self.copy(f.get()),
                   font=(DISPLAY, 8, "bold")).pack(side="left", padx=(6, 0))
            self.conn_fields[key] = field

    def build_gpu(self, side):
        box = panel(side)
        box.pack(fill="x")
        head = tk.Frame(box, bg=PANEL)
        head.pack(fill="x")
        heading(head, "GPU", "The share of points lit is how busy the card is; the purple "
                             "plane rises with memory in use. The line below is the last two "
                             "minutes.").pack(side="left")
        self.gpu_big = label(head, "-", SERVE, (DISPLAY, 22, "bold"))
        self.gpu_big.pack(side="right")
        self.gpu = tk.Canvas(box, height=px(150), bg=PANEL, highlightthickness=0)
        self.gpu.pack(fill="x", pady=(4, 0))
        self.spark = tk.Canvas(box, height=px(28), bg=PANEL, highlightthickness=0)
        self.spark.pack(fill="x", pady=(4, 0))
        self.gpu_after = self.spark
        # A short window keeps the numbers and the chat, and drops the picture.
        self.root.bind("<Configure>", self.fit_height, add="+")
        mem = tk.Frame(box, bg=PANEL)
        mem.pack(fill="x", pady=(8, 0))
        label(mem, "MEMORY", DIM, (DISPLAY, 8, "bold")).pack(side="left")
        self.mem_val = label(mem, "", DIM, (DISPLAY, 9, "bold"))
        self.mem_val.pack(side="right")
        self.mem_bar = tk.Canvas(mem, height=px(8), bg=TRACK, highlightthickness=0)
        self.mem_bar.pack(side="left", fill="x", expand=True, padx=10)
        self.gpu_stat = label(box, "waiting for readings...", DIM, (BODY, 9), anchor="w")
        self.gpu_stat.pack(fill="x", pady=(6, 0))
        self.gpu_state = {}
        self.lattice_setup()

    def build_chat(self, side):
        box = panel(side)
        box.pack(fill="both", expand=True, pady=(14, 0))
        head = tk.Frame(box, bg=PANEL)
        head.pack(fill="x")
        heading(head, "Talk to Orthros",
                "Ask: an answer from Orthros's own records, put into words by the model.\n\n"
                "Suggest direction: goes first on the chosen agent's task list, which its twin "
                "works through.").pack(side="left")
        button(head, "Clear", self.clear_chat, font=(DISPLAY, 8, "bold")).pack(side="right")
        # The box to type in and its buttons keep their place; the conversation takes the rest.
        self.chat_hint = label(box, "", SERVE, (BODY, 9), anchor="w")
        self.chat_hint.pack(side="bottom", fill="x", pady=(6, 0))
        btns = tk.Frame(box, bg=PANEL)
        btns.pack(side="bottom", fill="x", pady=(8, 0))
        self.chat_text = tk.Text(box, height=2, bg="#050a14", fg=INK, insertbackground=INK,
                                 relief="flat", font=(BODY, 10), wrap="word")
        self.chat_text.pack(side="bottom", fill="x")
        self.chat_text.bind("<Return>", self.chat_enter)
        self.chat = tk.Text(box, height=4, bg=PANEL, fg=INK, relief="flat", wrap="word",
                            font=(BODY, 10), padx=2, pady=4, spacing1=2, spacing3=10,
                            highlightthickness=0)
        self.chat.pack(fill="both", expand=True, pady=(8, 8))
        self.chat.tag_config("you", foreground="#bff6ff", lmargin1=px(110), lmargin2=px(110),
                             justify="right")
        self.chat.tag_config("orthros", foreground=INK, rmargin=px(60))
        self.chat.tag_config("when", foreground=FAINT, font=(DISPLAY, 8))
        self.chat.tag_config("you_when", foreground=FAINT, font=(DISPLAY, 8), justify="right")
        self.chat.config(state="disabled")
        self.ask = button(btns, "Ask", lambda: self.send_chat("ask"), "primary")
        self.ask.pack(side="left")
        self.direct = button(btns, "Suggest direction", lambda: self.send_chat("direct"))
        self.direct.pack(side="left", padx=6)
        label(btns, "for", DIM, (BODY, 9)).pack(side="left", padx=(6, 4))
        self.target = tk.StringVar(value="both")
        self.target_menu = tk.OptionMenu(btns, self.target, "both", "A", "B")
        self.target_menu.config(bg=PANEL2, fg=INK, activebackground="#28446e",
                                activeforeground=INK, relief="flat", highlightthickness=0, bd=0,
                                font=(BODY, 9))
        self.target_menu["menu"].config(bg=PANEL2, fg=INK, font=(BODY, 9))
        self.target_menu.pack(side="left")
        self.has_task_target = False

    # ---- diagnostics

    def build_diag(self, page):
        page.columnconfigure(0, weight=1, uniform="d")
        page.columnconfigure(1, weight=1, uniform="d")
        page.rowconfigure(1, weight=1)

        hk = panel(page)
        hk.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        head = tk.Frame(hk, bg=PANEL)
        head.pack(fill="x")
        heading(head, "Housekeeping", "What interrupted work and stray clicks leave behind. "
                                      "Clean up clears what is safe to clear; the rest is "
                                      "only said.").pack(side="left")
        self.hk_fix = button(head, "Clean up", self.housekeeping_fix, "primary",
                             font=(DISPLAY, 9, "bold"))
        self.hk_fix.pack(side="right")
        button(head, "Check", self.housekeeping_check, font=(DISPLAY, 9, "bold")).pack(
            side="right", padx=6)
        self.hk = tk.Text(hk, height=6, bg=PANEL, fg=INK, relief="flat", wrap="word",
                          font=(BODY, 9), highlightthickness=0, spacing3=4)
        self.hk.pack(fill="both", expand=True, pady=(10, 0))
        for name, color in (("done", GOOD), ("can", WARN), ("you", DIM)):
            self.hk.tag_config(name, foreground=color, font=(DISPLAY, 8, "bold"))

        tools = panel(page)
        tools.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        heading(tools, "Tools").pack(anchor="w")
        self.catalog = tk.Text(tools, height=12, bg=PANEL, fg=INK, relief="flat", wrap="word",
                               font=(BODY, 9), highlightthickness=0, spacing3=3)
        self.catalog.pack(fill="both", expand=True, pady=(10, 0))
        self.catalog.tag_config("h", foreground=DIM, font=(DISPLAY, 8, "bold"), spacing1=8)
        self.catalog.tag_config("name", foreground="#cfe6ff", font=(MONO, 9))
        self.catalog.tag_config("what", foreground=DIM)

        events = panel(page)
        events.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(14, 0))
        heading(events, "Recent").pack(anchor="w")
        self.events = tk.Text(events, bg=PANEL, fg=INK, relief="flat", wrap="word",
                              font=(BODY, 9), highlightthickness=0, spacing3=4)
        self.events.pack(fill="both", expand=True, pady=(10, 0))
        self.events.tag_config("time", foreground=FAINT, font=(DISPLAY, 9, "bold"))
        for kind, color in KIND_COLOR.items():
            self.events.tag_config(kind, foreground=color)

        right = tk.Frame(page, bg=BG)
        right.grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=(14, 0))
        bal = panel(right)
        bal.pack(fill="x")
        heading(bal, "Balance", "Each turn's length leans towards evening out the time and "
                                "tokens the two agents have had.").pack(anchor="w")
        self.bal = {}
        for key in ("Time", "Tokens"):
            row = tk.Frame(bal, bg=PANEL)
            row.pack(fill="x", pady=(8, 0))
            label(row, key, DIM, (BODY, 9), width=7, anchor="w").pack(side="left")
            canvas = tk.Canvas(row, height=10, bg=TRACK, highlightthickness=0)
            canvas.pack(side="left", fill="x", expand=True, padx=8)
            val = label(row, "", DIM, (BODY, 9), width=14, anchor="e")
            val.pack(side="left")
            self.bal[key] = (canvas, val)

        mach = panel(right)
        mach.pack(fill="x", pady=(14, 0))
        head = tk.Frame(mach, bg=PANEL)
        head.pack(fill="x")
        heading(head, "Machine").pack(side="left")
        button(head, "Check hardware", lambda: self.post("/api/hardware"),
               font=(DISPLAY, 8, "bold")).pack(side="right")
        self.machine = label(mach, "", INK, (BODY, 9), anchor="w", justify="left")
        self.machine.pack(anchor="w", pady=(8, 0))

        scores = panel(right)
        scores.pack(fill="both", expand=True, pady=(14, 0))
        heading(scores, "Scores").pack(anchor="w")
        self.scores = label(scores, "", DIM, (BODY, 9), anchor="nw", justify="left",
                            wraplength=560)
        self.scores.pack(anchor="w", pady=(8, 0))

        raw = panel(page)
        raw.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(14, 0))
        head = tk.Frame(raw, bg=PANEL)
        head.pack(fill="x")
        self.raw_toggle = button(head, "▸  RAW OUTPUT", self.toggle_raw,
                                 font=(DISPLAY, 9, "bold"))
        self.raw_toggle.pack(side="left")
        self.raw_file = label(head, "", DIM, (MONO, 9))
        self.raw_file.pack(side="left", padx=10)
        self.raw_agent = tk.StringVar(value="auto")
        menu = tk.OptionMenu(head, self.raw_agent, "auto", "A", "B",
                             command=lambda _v: self.term.update(agent=None))
        menu.config(bg=PANEL2, fg=INK, relief="flat", highlightthickness=0, bd=0, font=(BODY, 9),
                    activebackground="#28446e", activeforeground=INK)
        menu["menu"].config(bg=PANEL2, fg=INK)
        menu.pack(side="right")
        self.follow = tk.BooleanVar(value=True)
        tk.Checkbutton(head, text="follow", variable=self.follow, bg=PANEL, fg=DIM,
                       selectcolor=PANEL2, activebackground=PANEL, activeforeground=INK,
                       font=(BODY, 9), highlightthickness=0, bd=0).pack(side="right", padx=8)
        self.raw = tk.Text(raw, height=12, bg="#02050b", fg="#b9d7f5", relief="flat",
                           wrap="char", font=(MONO, 9), highlightthickness=0, padx=10, pady=8)

    # -------------------------------------------------------------- the GPU lattice

    def fit_height(self, event):
        if event.widget is not self.root:
            return
        tall = event.height >= px(1000)
        if tall and not self.gpu.winfo_ismapped():
            self.gpu.pack(fill="x", pady=(4, 0), before=self.gpu_after)
        elif not tall and self.gpu.winfo_ismapped():
            self.gpu.pack_forget()

    def lattice_setup(self):
        n = 7
        self.pts = [(x / (n - 1) * 2 - 1, y / (n - 1) * 2 - 1, z / (n - 1) * 2 - 1)
                    for x in range(n) for y in range(n) for z in range(n)]
        order, seed = list(range(len(self.pts))), 7
        for i in range(len(order) - 1, 0, -1):
            seed = seed * 16807 % 2147483647
            j = seed % (i + 1)
            order[i], order[j] = order[j], order[i]
        self.lit_order = order
        self.corners = [(x * 2 - 1, y * 2 - 1, z * 2 - 1) for x in (0, 1) for y in (0, 1)
                        for z in (0, 1)]
        self.edges = [(0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4),
                      (1, 5), (2, 6), (3, 7)]
        c = self.gpu
        self.plane = c.create_polygon(0, 0, 0, 0, 0, 0, fill="#3b2b72", outline="#9b6fe8")
        self.edge_items = [c.create_line(0, 0, 0, 0, fill="#22314b") for _ in self.edges]
        self.dot_items = [c.create_oval(0, 0, 0, 0, fill=FAINT, outline="") for _ in self.pts]
        self.angle, self.lit_shown, self.mem_shown, self.last_draw = 0.6, 0.0, 0.0, time.time()

    def draw_gpu(self):
        self.root.after(60, self.draw_gpu)
        if self.tab != "operate" or not self.gpu.winfo_ismapped():
            return
        c = self.gpu
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10:
            return
        now_t = time.time()
        dt, self.last_draw = min(0.2, now_t - self.last_draw), now_t
        g = self.gpu_state or {}
        self.angle += dt * 0.06
        util = max(0.0, min(100.0, float(g.get("util") or 0)))
        self.lit_shown += (util / 100 * len(self.pts) - self.lit_shown) * min(1, dt / 0.6)
        mem = (g.get("mem_used") or 0) / g["mem_total"] if g.get("mem_total") else 0
        self.mem_shown += (mem - self.mem_shown) * min(1, dt / 0.6)
        ca, sa, ct, st = math.cos(self.angle), math.sin(self.angle), math.cos(.42), math.sin(.42)
        scale, cx, cy = min(w, h) * 0.36, w / 2, h / 2

        def project(p):
            x, y, z = p
            x1, z1 = x * ca + z * sa, -x * sa + z * ca
            y1, z2 = y * ct - z1 * st, y * st + z1 * ct
            k = 6 / (6 + z2)
            return cx + x1 * scale * k, cy - y1 * scale * k, k

        if self.mem_shown > 0.01:
            yy = self.mem_shown * 2 - 1
            quad = [project(p) for p in ((-1, yy, -1), (1, yy, -1), (1, yy, 1), (-1, yy, 1))]
            c.coords(self.plane, *[v for x, y, _ in quad for v in (x, y)])
        corners = [project(p) for p in self.corners]
        for item, (a, b) in zip(self.edge_items, self.edges):
            c.coords(item, corners[a][0], corners[a][1], corners[b][0], corners[b][1])
        lit = set(self.lit_order[:int(round(self.lit_shown))])
        for i, (item, p) in enumerate(zip(self.dot_items, self.pts)):
            x, y, k = project(p)
            r = (2.6 if i in lit else 1.3) * k
            c.coords(item, x - r, y - r, x + r, y + r)
            c.itemconfig(item, fill=A_C if i in lit else "#34405a")

    # -------------------------------------------------------------- rendering

    def render_down(self, why):
        self.pill.config(text="ORTHROS IS NOT RUNNING", fg=BAD)
        self.headline.config(text="Orthros is not answering at %s. Run ORTHROS.bat."
                                  % self.api.base, fg=BAD)

    def render(self, d):
        if not isinstance(d, dict) or "phase" not in d:
            return self.render_down("no state")
        self.d = d
        phase = d["phase"]
        self.pill.config(text=(PHASES.get(phase, phase) + (" (simulation)" if d.get("simulate")
                                                           else "")).upper(),
                         fg=PHASE_COLOR.get(phase, DIM))
        self.sub.config(text=("WORKING ON THE TASK %s" % d.get("task", "")).upper()
                        if d["mode"] == "task" else MODES.get(d["mode"], "").upper())
        alert = d.get("alert") if d.get("paused") else None
        msg = ("Orthros needs you (%s): %s\nIt wrote ORTHROS-NEEDS-YOU.txt too. Press Start "
               "once it is dealt with." % (hhmm(alert[0]), alert[1]) if alert else
               "The machine was not ready. Trying again in %s." % fmt_left(d["backoff"])
               if d.get("backoff") else d.get("message") if phase == "error" else "")
        if msg:
            self.banner.config(text=msg)
            self.banner.pack(fill="x", before=self.tabs)
        else:
            self.banner.pack_forget()
        self.root.title("⚠ Orthros needs you" if alert else
                        "Orthros · %s working" % d["running"]["agent"] if d.get("running")
                        else "Orthros")
        if alert and self.shown.get("alert") != alert[0]:
            self.shown["alert"] = alert[0]
            self.root.bell()
        self.render_controls(d)
        self.render_mode(d)
        self.render_service(d)
        self.gpu_state = d.get("gpu") or {}
        self.render_gpu(d)
        for name, card in self.cards.items():
            card.render(d)
        self.render_chat(d.get("chat") or [], d.get("directions") or 0)
        self.render_diag(d)

    def render_controls(self, d):
        active = d.get("paused") is False or bool(d.get("running"))
        mode = "task" if self.want_task else d["mode"]
        if not active:
            text, kind = "▶  START", "start"
        elif d.get("stop_mode"):
            text, kind = "STOPPING...", "stopping"
        elif d.get("running"):
            text, kind = "■  STOP AFTER THIS TURN", "stop"
        elif d["mode"] == "serve":
            text, kind = "■  STOP SERVING", "stop"
        else:
            text, kind = "■  STOP", "stop"
        if self.go.kind != kind or self.go["text"] != text:
            paint(self.go, kind)
            self.go.config(text=text)
        self.go.config(state="disabled" if kind == "stopping" else "normal")
        if not self.minutes_touched and self.root.focus_get() is not self.minutes:
            self.set_spin(self.minutes, d["settings"].get("session_minutes", 60))
        self.first.set(d["running"]["agent"] if d.get("running") else d.get("next", "A"))
        # Turn settings belong to the turns: none in serve mode, practice only in Evolve.
        if mode == "serve":
            self.settings_row.pack_forget()
        elif not self.settings_row.winfo_ismapped():
            self.settings_row.pack(fill="x", pady=(8, 0), after=self.headline)
        if mode == "self" and not self.practice_box.winfo_ismapped():
            self.practice_box.pack(side="left", padx=(24, 0))
        elif mode != "self":
            self.practice_box.pack_forget()
        if d.get("running"):
            if not self.stops.winfo_ismapped():
                self.stops.pack(side="left", padx=(12, 0), anchor="n")
            enable(self.stop_round, d.get("stop_mode") not in ("now", "force"))
        else:
            self.stops.pack_forget()

    def render_mode(self, d):
        mode = "task" if self.want_task else d["mode"]
        for m, tile in self.tiles.items():
            tile.set(m == mode)
        self.ops.config(highlightbackground=MODE_COLOR[mode])
        if self.pane_shown != mode:
            for pane in self.panes.values():
                pane.pack_forget()
            self.turn_feed.pack_forget()
            if mode == "serve":
                self.panes[mode].pack(fill="both", expand=True)
            else:
                self.panes[mode].pack(fill="x")
                self.turn_feed.pack(fill="both", expand=True)
            self.pane_shown = mode
        self.render_feed(d)
        run = d.get("running")
        run_mode = None if not run else "self" if run.get("kind") != "task" else \
            "serve" if ("\\tools\\" in (run.get("workspace") or "")
                        or "/tools/" in (run.get("workspace") or "")) else "task"
        self.mode_note.config(text="SWITCHES WHEN THE RUNNING TURN ENDS"
                              if run_mode and run_mode != mode else "")
        phase = d["phase"]
        line = ("Paused" + (": " + d["message"].split("\n")[0] if d.get("message") else "")
                if phase == "paused" else "Idle. Pick a mode and press Start."
                if phase == "idle" else d.get("message") or PHASES.get(phase, ""))
        line = line[:1].upper() + line[1:]
        svc = d.get("service") or {}
        if d["mode"] == "serve" and phase == "serving" and svc.get("in_hand"):
            line += " · %d in hand" % svc["in_hand"]
        color = WARN if d.get("stop_mode") else {"serving": "#bff6ff", "running": "#c8fbe8",
                                                  "handover": "#ffe6bd", "error": "#ffc7cd"}.get(
                                                      phase, DIM)
        self.headline.config(text=("●  " + line), fg=color)
        # the evolve pane
        if self.root.focus_get() is not self.practice:
            self.set_spin(self.practice, d["settings"].get("practice_every", 4))
        bits = []
        for n in ("A", "B"):
            a = d["agents"][n]
            if a.get("held_out"):
                bits.append("%s held-out %d/%d" % (n, a["held_out"][0], a["held_out"][1]))
            p = (a.get("practice") or [])[-1:]
            if p:
                bits.append("%s practice %s %d/%d" % (n, p[0][1], p[0][2], p[0][3]))
        # Only when there are scores: a line saying there are none took room from the feed.
        self.self_summary.config(text="   ·   ".join(bits))
        if bits and not self.self_summary.winfo_ismapped():
            self.self_summary.pack(fill="x")
        elif not bits:
            self.self_summary.pack_forget()
        # the task pane
        keys = [t["key"] for t in d.get("tasks") or []]
        if keys != self.task_keys:
            self.task_keys = keys
            menu = self.task_menu["menu"]
            menu.delete(0, "end")
            for t in d.get("tasks") or []:
                menu.add_command(label=t["name"], command=lambda k=t["key"]: self.pick_task(k))
        chosen = next((t for t in d.get("tasks") or [] if t["key"] == d.get("task")), None)
        self.task_var.set(chosen["name"] if chosen else ("choose a task" if keys else
                                                         "no tasks yet"))
        self.task_info.config(text=("%d done · %d open%s%s" % (
            chosen["done"], chosen["open"], " · %d parked" % chosen["parked"]
            if chosen["parked"] else "", " · branch %s of %s" % (
                chosen["branch"], chosen["source"]) if chosen.get("source") else ""))
            if chosen else "")
        if d.get("task") and not self.has_task_target:
            self.target_menu["menu"].add_command(label="the task",
                                                 command=lambda: self.target.set("task"))
            self.has_task_target = True

    FEED_GOOD = ("Reviewer accepted", "Ticked off", "Test written", "is kept", "Kept")
    FEED_WARN = ("sent back", "rejected", "Rolled back", "did not match", "Nothing changed",
                 "Nothing moved")
    FEED_BAD = ("Parked", "broke", "error", "cut off", "ran out", "outgrew", "lost")

    def render_feed(self, d):
        """Gather the running turn's loop lines as they arrive; the state holds only the last few."""
        run = d.get("running")
        if run:
            key = (run.get("agent"), run.get("started") or run.get("token"))
            if key != self.feed_turn:
                self.feed_turn, self.feed_lines = key, []
            for when, text in (d.get("live") or {}).get("log") or []:
                row = (str(when)[:5], str(text).strip())
                if row[1] and not row[1].startswith("VRAM free") and row not in self.feed_lines[-40:]:
                    self.feed_lines.append(row)
            self.feed_lines = self.feed_lines[-300:]
            title = "This turn  ·  %s" % (self.describe_run(run))
        else:
            title = "Last turn" if self.feed_lines else "This turn"
        self.feed_title.winfo_children()[-1].config(text=title.upper())
        shown = (title, len(self.feed_lines), self.feed_lines[-1:] if self.feed_lines else None)
        if shown == self.shown.get("feed"):
            return
        self.shown["feed"] = shown

        def fill(t):
            if not self.feed_lines:
                t.insert("end", "Nothing running. The next turn's rounds show here as they "
                                "happen.", "time")
            for when, text in self.feed_lines:
                if text.startswith("Round "):
                    t.insert("end", when + "  ", "time")
                    t.insert("end", " ".join(text.split()) + "\n", "round")
                    continue
                tag = ("good" if any(w in text for w in self.FEED_GOOD) else
                       "bad" if any(w in text for w in self.FEED_BAD) else
                       "warn" if any(w in text for w in self.FEED_WARN) else ())
                t.insert("end", when + "  ", "time")
                t.insert("end", text + "\n", tag)
        readonly(self.feed, fill)
        self.feed.see("end")

    @staticmethod
    def describe_run(run):
        kind, label_ = run.get("kind"), run.get("label") or ""
        ws = run.get("workspace") or ""
        if kind == "task" and ("\\tools\\" in ws or "/tools/" in ws):
            return "%s builds the tool %s" % (run.get("agent"), label_)
        if kind == "task":
            return "%s on the task %s" % (run.get("agent"), label_)
        if kind in ("practice", "eval"):
            return "%s, %s %s" % (run.get("agent"), kind, label_)
        return "%s on %s's code" % (run.get("agent"), "B" if run.get("agent") == "A" else "A")

    def render_service(self, d):
        s = d.get("service") or {}
        for key, r in self.readouts.items():
            value = s.get(key) or 0
            r.set(fmt_n(value) if key == "tokens" else value,
                  WARN if key == "gave_up" and value else BAD if key in ("failed", "denied")
                  and value else INK)
        recent = (s.get("recent") or [])[:10]
        shown = json.dumps([recent, sorted(self.open_reqs)])
        if shown != self.shown.get("reqs"):
            self.shown["reqs"] = shown
            top = self.reqs.yview()[0]

            def fill(t):
                if not recent:
                    t.insert("end", "No requests yet: what callers ask shows up here.", "words")
                for r in recent:
                    at = str(r["at"])
                    mark = "req" + at.replace(".", "_")
                    opened = at in self.open_reqs
                    cls = "ok" if r["result"] == "answered" else "no" if \
                        r["result"].startswith("turned") else "bad"
                    res = ("ANSWERED · %s TOK · %ss" % (fmt_n(r["tokens"]).upper(),
                                                              r["seconds"])
                           if r["result"] == "answered" else r["result"].upper())
                    t.insert("end", hhmm(r["at"]) + "   ", ("time", mark))
                    t.insert("end", (r.get("tag") or "…") + "   ", ("tag", mark))
                    t.insert("end", res + "\n", (cls, mark))
                    words = r.get("full") or r["ask"] if opened else r["ask"]
                    if not opened and len(words) > 240:
                        words = words[:240] + " …"
                    t.insert("end", "%s · %s\n" % (r.get("user") or r["from"], words),
                             ("open" if opened else "words", mark))
                    t.tag_bind(mark, "<Button-1>", lambda e, a=at: self.toggle_req(a))
            readonly(self.reqs, fill)
            self.reqs.yview_moveto(top)
        tools = s.get("tools") or []
        self.tools_line.config(text="Tools built on request: " + ", ".join(
            "%s (%s)" % (t["key"], t["state"]) for t in tools) if tools else
            "No tools built on request yet: an MCP client asks for one with build_tool.")
        base = (s.get("urls") or [""])[0]
        port = d["settings"].get("serve_port", 8777)
        values = {"api": base + "/v1" if base else "", "mcp": base + "/mcp" if base else "",
                  "key": s.get("key", ""),
                  "rule": 'netsh advfirewall firewall add rule name="Orthros serve" dir=in '
                          'action=allow protocol=TCP localport=%s profile=private' % port,
                  "env": "ORTHROS_URL=%s   ORTHROS_KEY=%s" % (base, s.get("key", ""))}
        for key, field in self.conn_fields.items():
            if field.get() != values[key]:
                field.config(state="normal")
                field.delete(0, "end")
                field.insert(0, values[key])
                field.config(state="readonly")

    def render_gpu(self, d):
        g = d.get("gpu")
        hist = (d.get("gpu_history") or [])[-60:]
        c = self.spark
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if len(hist) > 1 and w > 10:
            pts = [(i / (len(hist) - 1) * w, h - 1 - max(0, min(100, u)) / 100 * (h - 2))
                   for i, u in enumerate(hist)]
            c.create_polygon(0, h, *[v for p in pts for v in p], w, h, fill="#0b2a36", outline="")
            c.create_line(*[v for p in pts for v in p], fill=SERVE, width=1.5)
        if not g:
            self.gpu_big.config(text="-")
            self.gpu_stat.config(text="No readings: nvidia-smi was not found or did not answer.")
            return
        self.gpu_big.config(text="%d%%" % round(g.get("util") or 0))
        total, used = g.get("mem_total") or 0, g.get("mem_used") or 0
        self.mem_val.config(text="%.1f / %.1f GB" % (used / 1024, total / 1024))
        self.mem_bar.delete("all")
        bw = self.mem_bar.winfo_width()
        if total and bw > 2:
            self.mem_bar.create_rectangle(0, 0, bw * used / total, px(8), fill=B_C,
                                          outline="")
        bits = [g.get("name") or "GPU"]
        if g.get("temp") is not None:
            bits.append("%d°C" % round(g["temp"]))
        if g.get("power") is not None:
            bits.append("%d W" % round(g["power"]))
        live = d.get("live") or {}
        if live.get("tok_per_sec"):
            bits.append("%s tok/s" % live["tok_per_sec"])
        self.gpu_stat.config(text="  ·  ".join(bits))

    def render_chat(self, chat, waiting):
        shown = json.dumps([chat, waiting])
        if shown == self.shown.get("chat"):
            return
        self.shown["chat"] = shown

        def fill(t):
            if not chat:
                t.insert("end", "Ask how it is going, or suggest where the work should go next.",
                         "when")
            for when, who, text in chat:
                mine = who == "you"
                t.insert("end", text + "\n", "you" if mine else "orthros")
                t.insert("end", hhmm(when) + "\n", "you_when" if mine else "when")
            if waiting:
                t.insert("end", "%d direction(s) waiting for the running turn to end." % waiting,
                         "when")
        readonly(self.chat, fill)
        self.chat.see("end")

    def render_diag(self, d):
        bad = any(e[2] == "bad" and e[0] > self.seen_bad for e in d.get("events") or [])
        if self.tab != "diag" and bad:
            self.diag_dot.pack(side="left")
        events = d.get("events") or []
        shown = json.dumps(events)
        if shown != self.shown.get("events"):
            self.shown["events"] = shown

            def fill(t):
                for when, text, kind in events:
                    t.insert("end", hhmm(when) + "  ", "time")
                    t.insert("end", "● ", kind if kind in KIND_COLOR else "time")
                    t.insert("end", text + "\n")
            readonly(self.events, fill)
        self.render_housekeeping(d.get("leftovers") or [])
        cat = (d.get("service") or {}).get("catalog")
        shown = json.dumps(cat)
        if shown != self.shown.get("catalog"):
            self.shown["catalog"] = shown

            def fill(t):
                if not cat:
                    t.insert("end", "Shown once Orthros runs this version.", "what")
                    return
                for title, rows in (("FOR THE NETWORK (MCP)", cat["network"]),
                                    ("BUILT ON REQUEST", cat["built"]),
                                    ("THE AGENTS' OWN, INSIDE THEIR TURNS", cat["agents"])):
                    t.insert("end", title + "\n", "h")
                    if not rows:
                        t.insert("end", "none yet\n", "what")
                    for r in rows:
                        t.insert("end", r["name"], "name")
                        t.insert("end", "   %s%s\n" % (r["what"], "  [%s]" % r["state"]
                                                       if r.get("state") else ""), "what")
            readonly(self.catalog, fill)
        agents = d["agents"]
        for key, field, fmt in (("Time", "seconds", fmt_t), ("Tokens", "tokens", fmt_n)):
            a, b = agents["A"].get(field) or 0, agents["B"].get(field) or 0
            canvas, val = self.bal[key]
            canvas.delete("all")
            w = canvas.winfo_width()
            share = a / (a + b) if a + b else 0.5
            canvas.create_rectangle(0, 0, w * share, 10, fill=A_C, outline="")
            canvas.create_rectangle(w * share, 0, w, 10, fill=B_C, outline="")
            val.config(text="%s · %s" % (fmt(a), fmt(b)) if a + b else "-")
        h = d.get("hardware") or {}
        look, use = h.get("look") or {}, dict(h.get("configured") or {}, **(h.get("good") or {}))
        rows = [("card", "%s, %d GB" % (look["gpu"], round((look.get("vram_mb") or 0) / 1024))
                 if look.get("gpu") else "not looked at yet"),
                ("memory", "%d GB, %s CPUs" % (round(look["ram_mb"] / 1024), look.get("cpus"))
                 if look.get("ram_mb") else "-"),
                ("model", use.get("LC_MODEL_KEY") or look.get("model") or "-"),
                ("context", fmt_n(int(use["LC_CONTEXT"])) + " tokens"
                 if use.get("LC_CONTEXT") else "-"),
                ("settings", "; ".join(h.get("why") or []) or "fitted to this machine")]
        self.machine.config(text="\n".join("%-10s %s" % r for r in rows))
        lines = []
        for n in ("A", "B"):
            a = agents[n]
            for p in (a.get("practice") or [])[-3:]:
                lines.append("%s practice %s: %d/%d" % (n, p[1], p[2], p[3]))
            for s in (a.get("scores") or [])[-3:]:
                lines.append("%s %s held-out: %d/%d exercises, %d/%d tests, %s"
                             % (n, hhmm(s[0]), s[1], s[2], s[3], s[4], s[5]))
            r24 = a.get("rounds_24h") or []
            if r24:
                lines.append("%s, last 24 h: %s" % (n, ", ".join("%s %d" % tuple(o) for o in r24)))
        self.scores.config(text="\n".join(lines) or "No scores yet.")

    def render_housekeeping(self, found):
        shown = json.dumps(found)
        if shown == self.shown.get("hk"):
            return
        self.shown["hk"] = shown

        def fill(t):
            if not found:
                t.insert("end", "Nothing left behind.")
            for what, done, fixable in found:
                t.insert("end", "CLEARED  " if done else "CAN CLEAR  " if fixable else
                         "FOR YOU  ", "done" if done else "can" if fixable else "you")
                t.insert("end", what + "\n")
        readonly(self.hk, fill)
        enable(self.hk_fix, any(f[2] and not f[1] for f in found))

    # -------------------------------------------------------------- actions

    def post(self, path, body=None, then=None):
        self.later(lambda: self.api.post(path, body), lambda r: (then and then(r),
                                                                 self.refresh()))

    def copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    @staticmethod
    def set_spin(spin, value):
        if spin.get() != str(value):
            spin.delete(0, "end")
            spin.insert(0, str(value))

    def minutes_changed(self):
        self.minutes_touched = True
        try:
            self.post("/api/settings", {"session_minutes": int(self.minutes.get())})
        except ValueError:
            pass

    def practice_changed(self):
        try:
            self.post("/api/settings", {"practice_every": int(self.practice.get())})
        except ValueError:
            pass

    def go_pressed(self):
        d = self.d or {}
        if d.get("paused") is False or d.get("running"):
            self.post("/api/pause")
            return
        try:
            minutes = int(self.minutes.get())
        except ValueError:
            minutes = None
        self.minutes_touched = False
        self.post("/api/start", {"first": self.first.get(), "minutes": minutes})

    def force_stop(self):
        if messagebox.askyesno("Force stop", "Kill the running agent now? Its current round is "
                                             "lost.", parent=self.root):
            self.post("/api/force")

    def change_allowed(self, mode, task=None):
        """Ask before changing what Orthros is doing while it is doing something."""
        d = self.d
        if not d or not (d.get("paused") is False or d.get("running")):
            return True
        if mode == d["mode"] and (mode != "task" or task is None or task == d.get("task")):
            return True
        doing = "working on the task %s" % d.get("task") if d["mode"] == "task" else \
            MODES[d["mode"]].lower()
        to = "working on the task %s" % task if mode == "task" else MODES[mode].lower()
        run = d.get("running")
        if run:
            left = max(0, run["minutes"] * 60 - ((d.get("live") or {}).get("elapsed") or 0))
            then = "%s's turn finishes first -- about %s -- and then Orthros switches." % (
                run["agent"], fmt_left(left))
        elif d["mode"] == "serve":
            then = ("Serving stops at once: callers are turned away and go to their next "
                    "provider, and the model is unloaded.")
        else:
            then = "It switches before the next turn starts."
        return messagebox.askyesno("Change what Orthros is doing?",
                                   "Orthros is %s.\n\nSwitch to %s?\n\n%s" % (doing, to, then),
                                   parent=self.root)

    def pick_mode(self, mode):
        if mode == "task":
            key = (self.d or {}).get("task")
            if key:
                return self.choose("task", key)
            self.want_task = True
            self.new_task.pack(fill="x")
            if self.d:
                self.render_mode(self.d)
            self.task_name.focus_set()
            return
        self.want_task = False
        self.new_task.pack_forget()
        self.choose(mode)

    def pick_task(self, key):
        self.choose("task", key)

    def choose(self, mode, task=None):
        if not self.change_allowed(mode, task):
            self.want_task = False
            if self.d:
                self.render_mode(self.d)
            return
        body = {"mode": mode} if task is None else {"mode": mode, "task": task}

        def done(r):
            if r.get("result") != "ok":
                self.task_msg.config(text=r.get("result") or r.get("error") or "", fg=BAD)
            else:
                self.want_task = False
        self.post("/api/mode", body, done)

    def toggle_new_task(self):
        if self.new_task.winfo_ismapped():
            self.new_task.pack_forget()
            self.want_task = False
        else:
            self.new_task.pack(fill="x")
            self.task_name.focus_set()
        if self.d:
            self.render_mode(self.d)

    def browse(self):
        folder = filedialog.askdirectory(parent=self.root, title="A git repository to work on")
        if folder:
            self.task_folder.delete(0, "end")
            self.task_folder.insert(0, os.path.normpath(folder))

    def create_task(self):
        body = {"name": self.task_name.get().strip(),
                "brief": self.task_brief.get("1.0", "end").strip(),
                "folder": self.task_folder.get().strip()}
        self.task_msg.config(text="Making a working copy of the folder..." if body["folder"]
                             else "", fg=DIM)

        def done(r):
            if r.get("error"):
                self.task_msg.config(text=r["error"], fg=BAD)
                return
            self.task_name.delete(0, "end")
            self.task_brief.delete("1.0", "end")
            self.task_folder.delete(0, "end")
            self.new_task.pack_forget()
            self.task_msg.config(text="Created. Press Start, or it begins at the next handover.",
                                 fg=DIM)
            self.choose("task", r.get("key"))
        self.post("/api/task", body, done)

    def toggle_req(self, at):
        if at in self.open_reqs:
            self.open_reqs.discard(at)
        else:
            self.open_reqs.add(at)
        if self.d:
            self.render_service(self.d)

    def toggle_connect(self):
        if self.connect.winfo_ismapped():
            self.connect.pack_forget()
            self.connect_toggle.config(text="▸  CONNECT ANOTHER MACHINE")
        else:
            self.connect.pack(side="bottom", fill="x", before=self.connect_toggle)
            self.connect_toggle.config(text="▾  CONNECT ANOTHER MACHINE")

    def chat_enter(self, event):
        if not (event.state & 0x1):             # Shift+Enter starts a new line
            self.send_chat("ask")
            return "break"
        return None

    def send_chat(self, kind):
        text = self.chat_text.get("1.0", "end").strip()
        if not text or self.chat_busy:
            return
        self.chat_busy = True
        enable(self.ask, False)
        enable(self.direct, False)
        self.chat_hint.config(text="Thinking... If the model has to load first, that takes a "
                                   "minute." if kind == "ask" else "")

        def done(r):
            self.chat_busy = False
            enable(self.ask, True)
            enable(self.direct, True)
            self.chat_hint.config(text="Could not send: %s" % r["error"] if r.get("error") else "")
            if not r.get("error"):
                self.chat_text.delete("1.0", "end")
                self.render_chat(r.get("chat") or [], 0)
        self.post("/api/chat", {"text": text, "kind": kind, "target": self.target.get()}, done)

    def clear_chat(self):
        self.post("/api/chat/clear", None, lambda r: self.chat_hint.config(
            text="" if r.get("result") == "ok" else "Restart Orthros once to use Clear."))

    def housekeeping_check(self):
        self.later(lambda: self.api.get("/api/housekeeping", timeout=120),
                   lambda r: self.render_housekeeping(r.get("found") or []))

    def housekeeping_fix(self):
        enable(self.hk_fix, False)
        self.post("/api/housekeeping", None, lambda r: self.render_housekeeping(
            r.get("found") or []))

    def toggle_raw(self):
        self.term_open = not self.term_open
        if self.term_open:
            self.raw.pack(fill="both", expand=True, pady=(10, 0))
            self.raw_toggle.config(text="▾  RAW OUTPUT")
            self.term["agent"] = None
        else:
            self.raw.pack_forget()
            self.raw_toggle.config(text="▸  RAW OUTPUT")

    def poll_term(self):
        """The running turn's log, fetched only while it is open to be read."""
        self.root.after(1000, self.poll_term)
        if not (self.term_open and self.tab == "diag" and self.d) or self.term.get("busy"):
            return
        pick = self.raw_agent.get()
        d = self.d
        if pick != "auto":
            agent = pick
        elif d.get("running"):
            agent = d["running"]["agent"]
        else:
            la = (d["agents"]["A"].get("last") or {}).get("started") or 0
            lb = (d["agents"]["B"].get("last") or {}).get("started") or 0
            agent = "B" if lb > la else "A"
        if agent != self.term["agent"]:
            self.term = {"agent": agent, "file": "", "offset": -1}
        self.term["busy"] = True
        query = urllib.parse.urlencode({"agent": agent, "file": self.term["file"],
                                        "offset": self.term["offset"]})

        def show(r):
            self.term["busy"] = False
            if not isinstance(r, dict) or "offset" not in r:
                return
            if r.get("reset"):
                self.raw.config(state="normal")
                self.raw.delete("1.0", "end")
            self.term.update(file=r.get("file") or "", offset=r["offset"])
            self.raw_file.config(text=(r.get("file") or "no log yet for %s" % agent)
                                 + ("  · live" if r.get("live") else ""))
            if r.get("text"):
                self.raw.config(state="normal")
                self.raw.insert("end", r["text"])
                extra = int(self.raw.index("end-1c").split(".")[0]) - 4000
                if extra > 0:
                    self.raw.delete("1.0", "%d.0" % extra)
                if self.follow.get():
                    self.raw.see("end")
            self.raw.config(state="disabled")

        def fetch():
            try:
                return self.api.get("/api/tail?" + query)
            except Exception:
                return None
        self.later(fetch, show)

    def run(self):
        self.root.mainloop()


class AgentCard(tk.Frame):
    """One agent: what it is doing, its turn's time as a ring, where its rounds went."""

    def __init__(self, parent, name, color, dash):
        super().__init__(parent, bg=PANEL, highlightthickness=2, highlightbackground="#18233a",
                         padx=14, pady=10)
        self.name, self.color, self.dash = name, color, dash
        top = tk.Frame(self, bg=PANEL)
        top.pack(fill="x")
        label(top, " %s " % name, "#06101f", (DISPLAY, 15, "bold"), bg=color, padx=4).pack(
            side="left")
        who = tk.Frame(top, bg=PANEL)
        who.pack(side="left", padx=12)
        self.role = label(who, "", INK, (DISPLAY, 11, "bold"), anchor="w")
        self.role.pack(anchor="w")
        self.ver = label(who, "", DIM, (BODY, 9), anchor="w")
        self.ver.pack(anchor="w")
        button(top, "log", self.open_log, font=(DISPLAY, 8, "bold"), padx=8, pady=2).pack(
            side="right", padx=(12, 0))
        self.nums = {}
        for key in ("tokens", "sent back", "kept", "rounds"):
            r = Readout(top, key)
            r.value.config(font=(DISPLAY, 14, "bold"))
            r.name.config(font=(DISPLAY, 7, "bold"))
            r.pack(side="right", padx=(14, 0))
            self.nums[key] = r

        mid = tk.Frame(self, bg=PANEL)
        mid.pack(fill="x", pady=(8, 0))
        mid.columnconfigure(0, weight=3, uniform="mid")
        mid.columnconfigure(1, weight=2, uniform="mid")
        now = tk.Frame(mid, bg=PANEL)
        now.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.ring = tk.Canvas(now, width=px(60), height=px(60), bg=PANEL, highlightthickness=0)
        self.lines = label(now, "", DIM, (BODY, 9), anchor="nw", justify="left")
        self.lines.pack(side="left", fill="both", expand=True)
        self.lines.bind("<Configure>", lambda e: self.lines.config(wraplength=e.width - px(4)))
        outcomes = tk.Frame(mid, bg=PANEL)
        outcomes.grid(row=0, column=1, sticky="new")
        self.outc_label = label(outcomes, "", DIM, (DISPLAY, 8, "bold"), anchor="w")
        self.outc_label.pack(fill="x", pady=(0, 3))
        self.outc = tk.Canvas(outcomes, height=px(8), bg=TRACK, highlightthickness=0)
        self.outc.pack(fill="x")
        self.legend = label(outcomes, "", DIM, (BODY, 8), anchor="w", justify="left")
        self.legend.pack(fill="x", pady=(4, 0))
        self.legend.bind("<Configure>", lambda e: self.legend.config(wraplength=e.width))
        self.totals = label(self, "", FAINT, (BODY, 9), anchor="w")
        self.totals.pack(fill="x", pady=(8, 0))

    def open_log(self):
        logs = os.path.join(HERE, "logs")
        try:
            names = sorted(f for f in os.listdir(logs) if f.endswith("-%s.log" % self.name))
        except OSError:
            names = []
        if names:
            os.startfile(os.path.join(logs, names[-1]))

    def render(self, d):
        a = d["agents"][self.name]
        run = d.get("running")
        on = bool(run) and run.get("agent") == self.name
        live = d.get("live") or {} if on else {}
        peer = "B" if self.name == "A" else "A"
        self.config(highlightbackground=self.color if on else "#18233a")
        if on:
            ws = run.get("workspace") or ""
            role = ("Building the tool %s" % run.get("label") if run.get("kind") == "task" and
                    ("\\tools\\" in ws or "/tools/" in ws) else "Working on the task %s"
                    % run.get("label") if run.get("kind") == "task" else "Practising: %s"
                    % run.get("label") if run.get("kind") == "practice" else
                    "Being scored: %s" % run.get("label") if run.get("kind") == "eval"
                    else "Working on %s" % peer)
            total = run["minutes"] * 60
            gone = live.get("elapsed") or 0
            left = max(0, total - gone)
            self.draw_ring(gone / total * 100 if total else 0, fmt_left(left), left < 120)
            what = "starting up -- loading the model" if live.get("phase") == "starting" else \
                "%s%s%s" % (live.get("phase") or "", " · round %s" % live["round"]
                            if live.get("round") else "", " · try %s of %s" % (
                                live["attempt"], live["budget"])
                            if live.get("attempt") and live.get("budget") else "")
            item = live.get("item") or live.get("detail") or ""
            detail = [what, item[:110] + (" …" if len(item) > 110 else "")]
            if live.get("last_round_seconds"):
                detail.append("last round %ss · %s in / %s out%s" % (
                    live["last_round_seconds"], fmt_n(live.get("last_in")),
                    fmt_n(live.get("last_out")), " · %s tok/s" % live["tok_per_sec"]
                    if live.get("tok_per_sec") else ""))
            if isinstance(live.get("review"), str) and live.get("review"):
                detail.append("reviewer: %s" % live["review"][:140])
            self.lines.config(text="\n".join(x for x in detail if x), fg=INK)
        else:
            self.ring.pack_forget()
            if d.get("paused") is False and d.get("next") == self.name and (
                    d["mode"] != "serve" or any(t.get("state") == "queued" for t in
                                                (d.get("service") or {}).get("tools") or [])):
                role = "Up next"
                where = "a tool" if d["mode"] == "serve" else "the task" if \
                    d["mode"] == "task" else peer
                self.lines.config(text="next turn: %s min on %s" % (
                    d["planned"][self.name], where), fg=DIM)
            else:
                role = "Waiting"
                last = a.get("last") or {}
                self.lines.config(text=("last turn %s: %s\n%s" % (
                    hhmm(last["started"]), "%s rounds, %s kept" % (last.get("rounds"),
                                                                   last.get("kept"))
                    if last.get("launched") else "failed to start", last.get("reason") or ""))
                    if last.get("started") else "not run yet", fg=DIM)
        self.role.config(text=role.upper() + ("   ●" if on else ""),
                         fg=GOOD if on else INK)
        proof = ("%d change set(s) to prove" % a["unproven"] if a.get("unproven") else
                 "%d waiting for a score" % a["unscored"] if a.get("unscored") else
                 "proven" if a.get("version") == a.get("proven") else "")
        held = "  ·  held-out %d/%d" % tuple(a["held_out"][:2]) if a.get("held_out") else ""
        self.ver.config(text="%s%s%s" % (a.get("version") or "", "  ·  " + proof
                                         if proof else "", held),
                        fg=GOOD if proof == "proven" else WARN if proof else DIM)
        s = live if on else (a.get("last") or {})
        tokens = (live.get("tokens_in") or 0) + (live.get("tokens_out") or 0) if on else \
            s.get("tokens") or 0
        self.nums["rounds"].set(s.get("rounds") or 0)
        self.nums["kept"].set((live.get("accepted") if on else s.get("kept")) or 0)
        self.nums["sent back"].set((live.get("rejected") if on else s.get("sent_back")) or 0)
        self.nums["tokens"].set(fmt_n(tokens))
        rows = a.get("rounds_24h") or []
        total = sum(n for _, n in rows)
        kept = sum(n for o, n in rows if o == "kept")
        self.outc_label.config(text="ROUNDS, LAST 24 H   %s" % (
            "%d OF %d KEPT" % (kept, total) if total else "NONE"))
        c = self.outc
        c.delete("all")
        w, x = c.winfo_width(), 0
        for outcome, n in rows:
            width = w * n / total if total else 0
            c.create_rectangle(x, 0, x + width, px(8), outline="", fill=OUTCOME_COLOR.get(
                outcome, BAD if outcome.startswith("lost") else DIM))
            x += width
        self.legend.config(text="   ".join("■ %s %d" % (o, n) for o, n in rows[:4]))
        self.totals.config(text="   ".join(filter(None, (
            "%d turns" % a.get("sessions", 0), fmt_t(a.get("seconds")),
            "%s tokens" % fmt_n(a.get("tokens")), "%d kept" % a.get("kept", 0),
            "%d carried in" % a["carried_in"] if a.get("carried_in") else "",
            "%d rolled back" % a["rollbacks"] if a.get("rollbacks") else ""))))

    def draw_ring(self, pct, text, low):
        c = self.ring
        if not c.winfo_ismapped():
            c.pack(side="left", padx=(0, 14), before=self.lines)
        c.delete("all")
        box = (px(6), px(6), px(54), px(54))
        c.create_oval(*box, outline=TRACK, width=px(6))
        c.create_arc(*box, start=90, extent=-3.6 * max(0, min(100, pct)),
                     style="arc", outline=WARN if low else self.color, width=px(6))
        c.create_text(px(30), px(30), text=text, fill=INK, font=(DISPLAY, 8, "bold"))


def bring_back():
    """Show the dashboard window that is already open, instead of a second one."""
    import ctypes
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _extra):
        title, kind = ctypes.create_unicode_buffer(200), ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, title, 200)
        user32.GetClassNameW(hwnd, kind, 64)
        if kind.value == "TkTopLevel" and "Orthros" in title.value:
            found.append(hwnd)
        return True
    user32.EnumWindows(each, None)
    for hwnd in found:
        user32.ShowWindow(hwnd, 9)                 # SW_RESTORE
        user32.SetForegroundWindow(hwnd)


def main():
    parser = argparse.ArgumentParser(description="Orthros's dashboard, in a window")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        main.mutex = kernel32.CreateMutexW(None, False, "OrthrosDashboard%d" % args.port)
        if ctypes.get_last_error() == 183:         # ERROR_ALREADY_EXISTS: one is open
            bring_back()
            return 0
        try:                                       # sharp text on high-DPI screens
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    Dashboard(args.port).run()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
