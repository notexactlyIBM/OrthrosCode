"""Orthros the bear: a low-poly grizzly living in the left third of the chat card in
Orthros's window. It walks out from behind the chat box when you come to talk,
watches you type, ponders while Orthros thinks, acts out the mood of each answer,
and walks back behind the box when the chat goes quiet. Now and then a salmon swims
along the bottom of the GPU picture, and it climbs up to catch and eat it. Its
lines glow faintly, more the busier the card is. (It had sparks along its lines
too, for a day: they read as dots on the bear, and cost a redraw a few times a
second. For another day it stood by the GPU picture and poked its dots.)

Two halves. Rig is the puppet: the drawing's mesh (orthros_bear_mesh.py) on a
skeleton, 2.5D -- every vertex has a depth from a rounded body shape, the drawing's
outline is a wall round each piece from its front to its back, bones turn in 3D,
polygons are drawn back to front -- with two-bone IK for the paws and feet.
Bear is its brain and its drawing on a tkinter canvas (its den, or the picture's):
every part of the body has somewhere it would like to be, made of layers (posture,
breathing, slow weight shifts, where it looks, what it is doing, any mood), and
follows it on a spring, so nothing pops.

The model ends each chat answer with [mood: ...] and may cue moves with [do: ...]
(orthros.py takes both off); the bear plays them.

Light on purpose (2026-10-21): tkinter takes about 35 ms to draw the whole bear,
so it runs at 15 frames a second only while it moves or you chat and at 5 while it
only stands, redraws only when it has moved enough to see or its glow has changed
by a tenth, turns far round only while it walks (the only time its back and sides
are drawn), stops while its tab is hidden, and draws nothing while it hides behind
the chat box.

Coordinates are the drawing's pixels: x right, y down, z towards the viewer.
Standard library only, like orthros.py.
"""

import math
import random
import time

from orthros_bear_mesh import FACES, VERTS

MOODS = ("happy", "laugh", "excited", "curious", "thinking", "surprised", "sad", "shy",
         "proud", "sleepy", "confused", "encouraging", "calm")

ART_W, ART_MID, ART_FEET, ART_TALL = 493, 248, 950, 925
SNAP = 11                          # a joint this close to a line intersection sits on it
# how far each piece stands out from its middle plane: a deep-chested bear with a round
# head and a long muzzle; the arms' middle plane is a little in front of the body's
DEPTH = {"body": 0.55, "head": 0.6, "muzzle": 72, "arm": 30, "leg": 34, "armMid": 22}
# how thick each piece is at its outline, either side of its middle plane: its side
# walls (2026-10-21: the outline lay on the middle plane, so side-on, or on all fours,
# the bear was a paper cut-out -- the drawing has too few points inside its outline
# for a bulge alone to give it a body)
WALL = {"body": 74, "head": 44, "leg": 26, "arm": 22, "ear": 5}
F = 2600                           # the camera's distance (far: a gentle perspective)
CAM = (ART_MID, 560)               # what the camera looks at
VIEWER = 2200                      # where the person at the screen is, in front of the bear
FPS, IDLE_FPS = 15, 5             # while it moves or you chat; while it only stands and breathes
GLOW = "#9fd6ff"                   # its lines, lit


# ---- small 3D maths: 3x3 matrices row-major, vectors as tuples

def norm(v):
    n = math.hypot(*v) or 1
    return (v[0] / n, v[1] / n, v[2] / n)


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mulv(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


I3 = (1, 0, 0, 0, 1, 0, 0, 0, 1)


def mm(A, B):
    return tuple(A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c]
                 for r in range(3) for c in range(3))


def mv(M, v):
    return (M[0] * v[0] + M[1] * v[1] + M[2] * v[2], M[3] * v[0] + M[4] * v[1] + M[5] * v[2],
            M[6] * v[0] + M[7] * v[1] + M[8] * v[2])


# pitch: + brings the top towards you (a nod); yaw: + turns the front to screen right;
# roll: + tips the top to screen right
def rot_x(d):
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return (1, 0, 0, 0, c, s, 0, -s, c)


def rot_y(d):
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return (c, 0, s, 0, 1, 0, -s, 0, c)


def rot_z(d):
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return (c, -s, 0, s, c, 0, 0, 0, 1)


def euler(yaw=0, pitch=0, roll=0):
    return mm(rot_y(yaw or 0), mm(rot_x(pitch or 0), rot_z(roll or 0)))


def swing(a, b):
    """The rotation that turns direction a into direction b (both unit)."""
    c = max(-1.0, min(1.0, dot(a, b)))
    k = cross(a, b)
    s = math.hypot(*k)
    if s < 1e-6:
        return I3 if c > 0 else rot_z(180)
    k = mulv(k, 1 / s)
    K = (0, -k[2], k[1], k[2], 0, -k[0], -k[1], k[0], 0)
    K2 = mm(K, K)
    return tuple(I3[i] + s * K[i] + (1 - c) * K2[i] for i in range(9))


def newell(pts):
    """A polygon's normal (not unit), whichever way round it goes."""
    n = (0, 0, 0)
    for k in range(len(pts)):
        n = add(n, cross(pts[k - 1], pts[k]))
    return n


def cross2(p, q, r):
    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])


def triangulate(pts):
    """Ear clipping: a polygon (2D points, either way round) as triangles of its corner
    numbers, each going the same way round as the polygon."""
    n = len(pts)
    area = sum(pts[k - 1][0] * pts[k][1] - pts[k][0] * pts[k - 1][1] for k in range(n))
    s = 1 if area >= 0 else -1
    turn = lambda a, b, c: cross2(pts[a], pts[b], pts[c]) * s
    idx, out = list(range(n)), []
    while len(idx) > 3:
        cut = 0                          # (a polygon with no ear: clip anyway)
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if turn(a, b, c) > 1e-9 and not any(
                    j not in (a, b, c) and turn(a, b, j) > 0 and turn(b, c, j) > 0 and turn(c, a, j) > 0
                    for j in idx):
                cut = k
                break
        out.append((idx[cut - 1], idx[cut], idx[(cut + 1) % len(idx)]))
        del idx[cut]
    out.append(tuple(idx))
    return out


def outline(tris):
    """The loops round some triangles of one polygon (corner numbers, all the same way
    round): its own sides where they show, and the fold where the rest turned away."""
    edges = {(t[k], t[(k + 1) % 3]) for t in tris for k in range(3)}
    nxt = {a: b for a, b in edges if (b, a) not in edges}
    loops = []
    while nxt:
        a = next(iter(nxt))
        loop = [a]
        while True:
            b = nxt.pop(a, None)
            if b is None or b == loop[0]:
                break
            loop.append(b)
            a = b
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def ease(x):
    return smooth(0, 1, x)


def osc(t, hz, ph=0.0):
    return math.sin((t * hz + ph) * math.pi * 2)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mix(c1, c2, k):
    """Colour c1 moved k of the way to c2 ('#rrggbb')."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * k) for x, y in zip(a, b))


# ---- the skeleton: (name, parent, joint in the drawing, snap to the nearest intersection?)
BONES = (
    ("root", None, (250, 650), False),
    ("spine", "root", (250, 650), False),
    ("chest", "spine", (262, 440), True),
    ("neck", "chest", (265, 322), True),
    ("head", "neck", (258, 262), False),
    ("jaw", "head", (256, 214), False),
    ("earL", "head", (168, 92), True), ("earR", "head", (334, 91), True),
    ("upperL", "chest", (128, 352), False), ("foreL", "upperL", (72, 482), True),
    ("pawL", "foreL", (92, 610), True),
    ("upperR", "chest", (372, 352), True), ("foreR", "upperR", (427, 484), True),
    ("pawR", "foreR", (406, 610), True),
    ("thighL", "root", (195, 660), False), ("shinL", "thighL", (132, 782), True),
    ("footL", "shinL", (120, 891), True),
    ("thighR", "root", (310, 660), False), ("shinR", "thighR", (343, 785), True),
    ("footR", "shinR", (370, 889), True),
)
TIPS = {"pawL": (80, 690), "pawR": (418, 690), "footL": (100, 950), "footR": (400, 950)}
# which part each polygon belongs to (by its middle), drawn round the art; the arms' inner
# edges follow the drawing's own long lines from the shoulder down to the paw
AREAS = {
    "earL": ((136, 24), (205, 24), (200, 84), (168, 104), (140, 110)),
    "earR": ((300, 24), (362, 24), (365, 110), (336, 104), (306, 84)),
    "armL": ((60, 286), (100, 290), (133, 326), (150, 422), (126, 489), (114, 532), (123, 618),
             (112, 640), (108, 668), (106, 680), (96, 712), (14, 712), (16, 470), (44, 392)),
    "armR": ((440, 286), (393, 296), (389, 344), (401, 405), (385, 475), (400, 561), (401, 605),
             (400, 636), (384, 646), (392, 684), (413, 690), (440, 692), (485, 692), (485, 470),
             (462, 380)),
}
# The snout is a faceted block: how far each of its points stands out from the face, as a
# share of DEPTH["muzzle"]. Found by position (within 3 px); any other point is 0.
SNOUT = (
    (232, 165, 1), (241, 158, 1), (270, 162, 1), (241, 171, 1), (236, 178, 1), (269, 177, 1),
    (270, 184, 1), (237, 187, 1), (264, 190, 1), (244, 191, 1), (254, 191, 1),
    (247, 169, 1.12), (259, 169, 1.12), (248, 181, 1.12), (258, 180, 1.12),
    (250, 203, 0.97), (260, 204, 0.97), (232, 208, 0.9), (270, 206, 0.9),
    (234, 215, 0.75), (273, 215, 0.75), (242, 221, 0.7), (266, 220, 0.7), (226, 208, 0.35),
    (277, 208, 0.35), (252, 247, 0.3), (258, 248, 0.3),
)
# points on the body a paw can reach for: (bone, x, y, z), just in front of its surface
ANCHORS = {
    "muzzleL": ("head", 226, 196, 125), "muzzleR": ("head", 288, 196, 125),
    "cheekL": ("head", 178, 170, 78), "cheekR": ("head", 338, 170, 78),
    "crownL": ("head", 200, 60, 52), "crownR": ("head", 312, 60, 52),
    "chinL": ("head", 238, 252, 125), "chinR": ("head", 276, 252, 125),
    "bellyL": ("spine", 215, 560, 175), "bellyR": ("spine", 298, 560, 175),
    "chestL": ("chest", 225, 400, 180), "chestR": ("chest", 300, 400, 180),
    "hipL": ("spine", 168, 586, 125), "hipR": ("spine", 330, 586, 125),
    "upL": ("chest", 96, 210, 125), "upR": ("chest", 404, 210, 125),
    "top": ("head", 258, 10, 0), "nose": ("head", 256, 176, 121),
}
LIGHT = norm((-0.45, -0.55, 0.7))


def inside(p, poly):
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        (xi, yi), (xj, yj) = poly[i], poly[j]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def middle(ids):
    return (sum(VERTS[i][0] for i in ids) / len(ids), sum(VERTS[i][1] for i in ids) / len(ids))


def part_of(ids):
    c = middle(ids)
    for part, poly in AREAS.items():
        if inside(c, poly):
            return part
    if c[1] < 252:
        return "head"
    if c[1] > 700:
        return "legL" if c[0] < 250 else "legR"
    return "body"


class Rig:
    """The puppet: build once, then set_pose() and shapes() each frame."""

    def __init__(self):
        self.bones = []
        for name, parent, at, snap in BONES:
            p = at
            if snap:
                best = SNAP
                for v in VERTS:
                    d = math.hypot(v[0] - at[0], v[1] - at[1])
                    if d < best:
                        best, p = d, v
            self.bones.append({"name": name, "parent": parent, "rest": (p[0], p[1], 0)})
        self.B = {b["name"]: i for i, b in enumerate(self.bones)}
        for b in self.bones:
            b["p"] = -1 if b["parent"] is None else self.B[b["parent"]]
        self.build_skin()
        self.world = [(I3, (0, 0, 0))] * len(self.bones)
        self.out = [(0, 0, 0)] * len(self.verts)
        bend = lambda a, b, c, back: self.bend_of(a, b, c, back)
        self.bend = {"L": (bend("upperL", "foreL", "pawL", -0.35), bend("thighL", "shinL", "footL", 0.45)),
                     "R": (bend("upperR", "foreR", "pawR", -0.35), bend("thighR", "shinR", "footR", 0.45))}
        self.set_pose({})

    def rest(self, name):
        return self.bones[self.B[name]]["rest"]

    def build_skin(self):
        """The vertex copies each part draws with (arms get their own, so an arm swings clear
        of the body), their depths and bone weights, and the face's moving features."""
        faces = [{"ids": f, "part": part_of(f)} for f in FACES]
        verts, index = [], {}
        for f in faces:
            vs = []
            for i in f["ids"]:
                key = "%s:%d" % (f["part"], i) if f["part"] in ("armL", "armR") else str(i)
                if key not in index:
                    index[key] = len(verts)
                    verts.append({"x": VERTS[i][0], "y": VERTS[i][1], "parts": set()})
                verts[index[key]]["parts"].add(f["part"])
                vs.append(index[key])
            f["vs"] = vs

        def span(part):
            rows = {}
            for f in faces:
                if f["part"] == part:
                    for i in f["ids"]:
                        band = math.floor(VERTS[i][1] / 20 + 0.5)
                        lo, hi = rows.get(band, (math.inf, -math.inf))
                        rows[band] = (min(lo, VERTS[i][0]), max(hi, VERTS[i][0]))

            def at(y):
                b = y / 20
                lo = rows.get(math.floor(b)) or rows.get(math.ceil(b))
                hi = rows.get(math.ceil(b)) or lo
                if not lo:
                    return None
                t = b - math.floor(b)
                return (lo[0] + (hi[0] - lo[0]) * t, lo[1] + (hi[1] - lo[1]) * t)
            return at

        body_span, head_span = span("body"), span("head")

        def bulge(x, y, s, k):
            r = s(y)
            if not r:
                return 0
            cx, hw = (r[0] + r[1]) / 2, max(20, (r[1] - r[0]) / 2)
            u = (x - cx) / hw
            return k * hw * math.sqrt(max(0, 1 - u * u))

        def off_line(p, a, b):
            ab = (b[0] - a[0], b[1] - a[1])
            t = max(0, min(1, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / (ab[0] ** 2 + ab[1] ** 2)))
            return math.hypot(p[0] - a[0] - ab[0] * t, p[1] - a[1] - ab[1] * t)

        def limb(p, chain, r):           # a rounded limb round a chain of joints
            best = min(off_line(p, chain[i], chain[i + 1]) for i in range(len(chain) - 1))
            return r * math.sqrt(max(0, 1 - (best / (r * 1.5)) ** 2))

        J = self.rest
        chains = {"armL": (J("upperL"), J("foreL"), J("pawL"), TIPS["pawL"]),
                  "armR": (J("upperR"), J("foreR"), J("pawR"), TIPS["pawR"]),
                  "legL": (J("thighL"), J("shinL"), J("footL"), TIPS["footL"]),
                  "legR": (J("thighR"), J("shinR"), J("footR"), TIPS["footR"])}

        def wall(y, part):
            """How thick the piece is at its outline (the head widening into the neck,
            the body narrowing into the legs)."""
            if part in ("armL", "armR"):
                return WALL["arm"]
            if part in ("earL", "earR"):
                return WALL["ear"]
            if part == "head":
                return WALL["head"] + (WALL["body"] - WALL["head"]) * smooth(150, 262, y)
            if part in ("legL", "legR"):
                return WALL["leg"] + (WALL["body"] - WALL["leg"]) * (1 - smooth(700, 760, y))
            return WALL["body"]

        def depth(x, y, part, front=True):
            """How far a point stands out from its piece's middle plane; the front has the
            muzzle and the toes, the back neither."""
            if part in ("armL", "armR"):
                return limb((x, y), chains[part], DEPTH["arm"])
            if part in ("legL", "legR"):
                toes = (y - 900) * 0.9 if front and y > 900 else 0
                lz = limb((x, y), chains[part], DEPTH["leg"]) + toes
                t = smooth(700, 760, y)
                return lz * t + bulge(x, y, body_span, DEPTH["body"]) * (1 - t)
            if part in ("earL", "earR"):
                return 8
            if part == "head":
                s = front and next((s for s in SNOUT if math.hypot(s[0] - x, s[1] - y) < 3), None)
                return bulge(x, y, head_span, DEPTH["head"]) + (DEPTH["muzzle"] * s[2] if s else 0)
            return bulge(x, y, body_span, DEPTH["body"])

        # the outline (edges with a polygon on one side only) is the top of the side walls
        uses = {}
        for f in faces:
            vs = f["vs"]
            for k in range(len(vs)):
                a, b = vs[k], vs[(k + 1) % len(vs)]
                key = (min(a, b), max(a, b))
                uses[key] = uses.get(key, 0) + 1
        rim = {i for key, n in uses.items() if n == 1 for i in key}
        for i, v in enumerate(verts):
            parts = v["parts"]
            v["part"] = ("armL" if "armL" in parts else "armR" if "armR" in parts else
                         "head" if "head" in parts else
                         next((p for p in parts if p.startswith("ear")), None) or
                         ("legL" if "legL" in parts else "legR" if "legR" in parts else "body"))
            mid = DEPTH["armMid"] if v["part"].startswith("arm") else 0
            out = lambda front: sum(wall(v["y"], p) + (0 if i in rim else depth(v["x"], v["y"], p, front))
                                    for p in parts) / len(parts)
            v["z"], v["zback"] = mid + out(True), mid - out(False)
            v["w"] = self.weights(v)
        near = lambda c, r: [i for i, v in enumerate(verts)
                             if v["part"] == "head" and math.hypot(v["x"] - c[0], v["y"] - c[1]) < r]
        self.eyes = [near((219, 116), 13), near((280, 117), 13)]
        self.nose = near((256, 176), 16)
        for f in faces:
            c = middle(f["ids"])
            f["bias"] = 38 if f["part"].startswith("arm") else 0      # arms in front of the body
            if f["part"] == "head" and (math.hypot(c[0] - 219, c[1] - 116) < 11 or
                                        math.hypot(c[0] - 280, c[1] - 117) < 11 or
                                        math.hypot(c[0] - 256, c[1] - 176) < 14):
                f["bias"] = 6                                        # eyes and nose on the face
            vs = f["vs"]
            a = sum(verts[vs[k]]["x"] * verts[vs[(k + 1) % len(vs)]]["y"] -
                    verts[vs[(k + 1) % len(vs)]]["x"] * verts[vs[k]]["y"] for k in range(len(vs)))
            f["sign"] = 1 if a >= 0 else -1                          # its way round, facing you
            # the face's features: their copies at the back of the head are drawn without
            # lines, else a head bent towards you shows a second face from the inside
            f["feature"] = f["part"] == "head" and (
                ((c[0] - 257) / 42) ** 2 + ((c[1] - 188) / 64) ** 2 < 1 or
                math.hypot(c[0] - 219, c[1] - 116) < 16 or math.hypot(c[0] - 280, c[1] - 117) < 16)
        # The back: each polygon again, behind its piece's middle plane and the other way
        # round; and round the outline a wall from the front to the back -- so a bear on
        # all fours, or turned, is a solid and not a cut-out (2026-10-21: it had no back,
        # and could neither bend nor turn far; then a back and no walls, and side-on it
        # was a sheet).
        back_of = {}

        def behind(i):
            if i not in back_of:
                back_of[i] = len(verts)
                verts.append(dict(verts[i], z=verts[i]["zback"]))
            return back_of[i]
        walls = []
        for f in faces:
            vs = f["vs"]
            for k in range(len(vs)):
                a, b = vs[k], vs[(k + 1) % len(vs)]
                if uses[(min(a, b), max(a, b))] > 1:
                    continue
                quad = [a, b, behind(b), behind(a)]
                # it faces out of its polygon: across the edge, away from the inside
                dx, dy = verts[b]["x"] - verts[a]["x"], verts[b]["y"] - verts[a]["y"]
                n = newell([(verts[i]["x"], verts[i]["y"], verts[i]["z"]) for i in quad])
                walls.append(dict(f, vs=quad, wall=True, feature=False,
                                  sign=1 if (n[0] * dy - n[1] * dx) * f["sign"] > 0 else -1))
        for f in list(faces):
            faces.append(dict(f, vs=[behind(i) for i in reversed(f["vs"])], back=True))
        faces += walls
        # The front in triangles: a long polygon that is not flat (the snout's sides, from
        # the brow to the mouth) turns away a part at a time, its fold drawn where it turns,
        # and not all at once, which leaves a hole: the snout side-on looked hollow.
        for f in faces:
            if f.get("back") or f.get("wall"):
                continue
            pts = [(verts[i]["x"], verts[i]["y"]) for i in f["vs"]]
            f["tris"] = triangulate(pts)
            f["size"] = [max(4, abs(cross2(pts[i], pts[j], pts[k]))) for i, j, k in f["tris"]]
            f["whole2"] = max(4, abs(sum(pts[k][0] * pts[k - 1][1] - pts[k - 1][0] * pts[k][1]
                                         for k in range(len(pts)))))
            f["vis"], f["turning"] = [True] * len(f["tris"]), False
        self.faces, self.verts = faces, verts

    def weights(self, v):
        """Which bones move a vertex, and how much: blended across each joint."""
        w = {}
        B, J = self.B, self.rest

        def put(name, k):
            if k > 0.001:
                w[B[name]] = w.get(B[name], 0) + k
        x, y, part = v["x"], v["y"], v["part"]

        def t(a, b):
            ab = (b[0] - a[0], b[1] - a[1])
            return ((x - a[0]) * ab[0] + (y - a[1]) * ab[1]) / (ab[0] ** 2 + ab[1] ** 2)
        if part in ("armL", "armR"):
            s = part[-1]
            sh, el, wr = J("upper" + s), J("fore" + s), J("paw" + s)
            top = smooth(sh[1] - 50, sh[1] + 20, y)          # the top of the shoulder stays on the chest
            a, b = t(sh, el), t(el, wr)
            fore = smooth(0.78, 1.08, a) * (1 - smooth(0.82, 1.1, b))
            paw = smooth(0.82, 1.1, b)
            put("chest", 1 - top)
            put("upper" + s, top * (1 - fore - paw))
            put("fore" + s, top * fore)
            put("paw" + s, top * paw)
        elif part in ("earL", "earR"):
            put(part, 1)
        elif part == "head":
            jaw = ((x - 256) / 34) ** 2 + ((y - 236) / 22) ** 2 < 1 and y > 214   # under the mouth
            neckish = smooth(232, 262, y)
            put("jaw" if jaw else "head", 1 - neckish)
            put("neck", neckish)
        elif part in ("legL", "legR") or (part == "body" and y > 640):
            s = "R" if part == "legR" or (part == "body" and x >= 250) else "L"
            hip, kn, an = J("thigh" + s), J("shin" + s), J("foot" + s)
            on_leg = smooth(645, 735, y) * (smooth(40, 95, abs(x - 250)) if part == "body" else 1)
            a, b = t(hip, kn), t(kn, an)
            shin = smooth(0.82, 1.12, a) * (1 - smooth(0.78, 1.0, b))
            foot = smooth(0.78, 1.0, b)
            put("spine", 1 - on_leg)
            put("thigh" + s, on_leg * (1 - shin - foot))
            put("shin" + s, on_leg * shin)
            put("foot" + s, on_leg * foot)
        else:                            # the body: belly on the spine, chest above, neck on top
            chest = smooth(610, 450, y)
            neck = smooth(345, 285, y) * (1 - smooth(55, 110, abs(x - 262)))
            put("spine", 1 - chest)
            put("chest", chest * (1 - neck))
            put("neck", chest * neck)
        total = sum(w.values())
        return [(b, k / total) for b, k in w.items()]

    def bend_of(self, a, b, c, back):
        """Which way a limb's middle joint bends as drawn, plus back or forward."""
        A, E, C = self.rest(a), self.rest(b), self.rest(c)
        u, ae = norm(sub(C, A)), sub(E, A)
        return norm(add(norm(sub(ae, mulv(u, dot(ae, u)))), (0, 0, back)))

    def fk(self, name, local):
        i = self.B[name]
        b = self.bones[i]
        R, p = self.world[b["p"]]
        self.world[i] = (mm(R, local), add(p, mv(R, sub(b["rest"], self.bones[b["p"]]["rest"]))))

    def joint(self, name):
        return self.world[self.B[name]][1]

    def anchor(self, name):
        if name in ("restL", "restR"):              # the paw hanging as drawn
            R, p = self.world[self.B["chest"]]
            return add(p, mv(R, sub(self.rest("paw" + name[-1]), self.rest("chest"))))
        bone, x, y, z = ANCHORS[name]
        R, p = self.world[self.B[bone]]
        return add(p, mv(R, sub((x, y, z), self.rest(bone))))

    def ik(self, a, b, c, target, pole, parent_r, end_local, shrug=0):
        """Two-bone IK: from the joint at a towards target, the middle joint bending to pole."""
        A = self.joint(a)
        L1 = math.hypot(*sub(self.rest(b), self.rest(a)))
        L2 = math.hypot(*sub(self.rest(c), self.rest(b)))
        d = sub(target, A)
        dist = math.hypot(*d)
        if shrug and dist > (L1 + L2) * 0.92:      # a far reach lifts the shoulder a little
            A = add(A, mulv(d, min(shrug, dist - (L1 + L2) * 0.92) / dist))
            d = sub(target, A)
            dist = math.hypot(*d)
        reach = max(abs(L1 - L2) + 1, min(L1 + L2 - 0.5, dist))
        u = mulv(d, 1 / (dist or 1))
        cos_a = clamp((L1 * L1 + reach * reach - L2 * L2) / (2 * L1 * reach), -1, 1)
        pp = sub(pole, mulv(u, dot(pole, u)))
        if math.hypot(*pp) < 1e-4:
            pp = cross(u, (0, 0, 1))
        pp = norm(pp)
        E = add(A, add(mulv(u, L1 * cos_a), mulv(pp, L1 * math.sqrt(1 - cos_a * cos_a))))
        T = add(A, mulv(u, reach))
        rest_dir = lambda p, q: norm(sub(self.rest(q), self.rest(p)))
        Ru = mm(swing(mv(parent_r, rest_dir(a, b)), norm(sub(E, A))), parent_r)
        Rf = mm(swing(mv(Ru, rest_dir(b, c)), norm(sub(T, E))), Ru)
        self.world[self.B[a]] = (Ru, A)
        self.world[self.B[b]] = (Rf, E)
        self.world[self.B[c]] = (mm(Rf, end_local), T)

    def set_pose(self, pose):
        """pose: per bone {x, y, z (root only), yaw, pitch, roll}; armL/R, legL/R: targets for
        the wrists and ankles; breathe; jaw; face: {blink, twitch}."""
        r = pose.get("root", {})
        root = self.bones[0]["rest"]
        self.world[0] = (euler(r.get("yaw"), r.get("pitch"), r.get("roll")),
                         add(root, (r.get("x", 0), r.get("y", 0), r.get("z", 0))))
        loc = lambda n: euler(*(pose.get(n, {}).get(k) for k in ("yaw", "pitch", "roll")))
        self.fk("spine", loc("spine"))
        self.fk("chest", mm(loc("chest"), rot_x(pose.get("breathe", 0))))
        self.fk("neck", loc("neck"))
        self.fk("head", loc("head"))
        self.fk("jaw", rot_x(pose.get("jaw", 0) * 16))
        self.fk("earL", loc("earL"))
        self.fk("earR", loc("earR"))
        chest_r, chest_p = self.world[self.B["chest"]]
        root_r, root_p = self.world[0]
        for s in "LR":
            up = self.B["upper" + s]
            self.world[up] = (chest_r, add(chest_p, mv(chest_r, sub(self.rest("upper" + s), self.rest("chest")))))
            arm = pose.get("arm" + s) or self.anchor("rest" + s)
            self.ik("upper" + s, "fore" + s, "paw" + s, arm, mv(chest_r, self.bend[s][0]), chest_r,
                    loc("paw" + s), 30)
            th = self.B["thigh" + s]
            self.world[th] = (root_r, add(root_p, mv(root_r, sub(self.rest("thigh" + s), root))))
            foot = pose.get("leg" + s) or self.rest("foot" + s)
            self.ik("thigh" + s, "shin" + s, "foot" + s, foot, mv(root_r, self.bend[s][1]), root_r,
                    loc("foot" + s))
        out = self.out = []
        for v in self.verts:                 # skin: each vertex follows its bones
            x = y = z = 0
            for b, k in v["w"]:
                R, p = self.world[b]
                rest = self.bones[b]["rest"]
                q = mv(R, (v["x"] - rest[0], v["y"] - rest[1], v["z"] - rest[2]))
                x += (q[0] + p[0]) * k
                y += (q[1] + p[1]) * k
                z += (q[2] + p[2]) * k
            out.append([x, y, z])
        face = pose.get("face", {})
        shut = clamp(face.get("blink", 0), -0.25, 1)
        if shut:                            # a blink squashes each eye towards its middle line
            for ids in self.eyes:
                cy = sum(out[i][1] for i in ids) / len(ids)
                for i in ids:
                    out[i][1] = cy + (out[i][1] - cy) * (1 - shut * 0.85)
        if face.get("twitch"):
            for i in self.nose:
                out[i][1] -= face["twitch"] * 4 * (1 - abs(self.verts[i]["x"] - 256) / 20)

    @staticmethod
    def project(p, o):
        """Where a point lands on the canvas: o = (x, feet, scale), where the feet's middle goes."""
        k = F / max(200, F - p[2])
        return (o[0] + (CAM[0] + (p[0] - CAM[0]) * k - ART_MID) * o[2],
                o[1] + (CAM[1] + (p[1] - CAM[1]) * k - ART_FEET) * o[2])

    def shapes(self, o):
        """The polygons facing you, back to front: (key, face number, flat screen points,
        light). The key is the face number, or (face number, k) for the k-th piece of a
        front polygon partly turned away."""
        screen = [self.project(p, o) for p in self.out]
        s2 = o[2] * o[2]
        order = []
        for n, f in enumerate(self.faces):
            vs = f["vs"]
            m = len(vs)
            a = sum(screen[vs[k]][0] * screen[vs[(k + 1) % m]][1] -
                    screen[vs[(k + 1) % m]][0] * screen[vs[k]][1] for k in range(m)) * f["sign"]
            pieces = [vs]
            if "tris" not in f:              # a back or a wall: all of it, if it faces you
                if a < 0.5:
                    continue
            else:
                # A big polygon is split into its triangles only while it is clearly turning
                # (shrunk under a third of its size, until back over two fifths), and then a
                # triangle goes only once clearly turned away: near rest every polygon is
                # whole, so a sliver held nearly edge-on doesn't flash a fold on and off.
                tris = f["tris"]
                f["turning"] = len(tris) > 1 and f["whole2"] >= 800 and \
                    a / (f["whole2"] * s2) < (0.4 if f["turning"] else 0.3)
                if f["turning"]:
                    vis = f["vis"] = [cross2(screen[vs[i]], screen[vs[j]], screen[vs[k]]) * f["sign"] /
                                      (f["size"][t] * s2) >= (-0.12 if f["vis"][t] else -0.02)
                                      for t, (i, j, k) in enumerate(tris)]
                    if not any(vis):
                        continue
                    if not all(vis):
                        pieces = [[vs[c] for c in loop]
                                  for loop in outline([t for t, on in zip(tris, vis) if on])]
                elif a < -0.5:
                    continue                 # turned away from you
            z = sum(self.out[i][2] for i in vs) / m + f["bias"]
            p, q, r = self.out[vs[0]], self.out[vs[1]], self.out[vs[2]]
            nrm = norm(cross(sub(q, p), sub(r, p)))
            lit = max(0, dot(nrm if nrm[2] >= 0 else mulv(nrm, -1), LIGHT))
            for k, piece in enumerate(pieces):
                key = n if piece is vs else (n, k)
                order.append((z, key, n, [c for i in piece for c in screen[i]], lit))
        order.sort(key=lambda e: e[0])
        return [e[1:] for e in order]


# ---- what it does: each runs for dur seconds with c (see Clip)

def scratch_face(c):
    k, s, o = c.env(0.7, 0.8), c.side, c.out
    # the wrist high on the side of the head, raking down the cheek
    c.arm(s, "cheek" + s, (o * 8 + osc(c.t, 3.2, 0.25) * 4, -18 + osc(c.t, 3.2) * 13, 2), k, 12)
    c.add("head.roll", -o * 11 * k), c.add("head.yaw", o * 6 * k), c.add("head.pitch", 5 * k)
    c.add("spine.roll", -o * 2 * k)
    c.face("blink", 0.55 * k), c.mute("look", k)


def sniff(c):
    k = c.env(0.8, 0.8)
    c.add("head.pitch", -17 * k), c.add("neck.pitch", -8 * k)
    c.add("head.yaw", osc(c.t, 0.3) * 14 * k)
    c.add("earL.pitch", 10 * k), c.add("earR.pitch", 10 * k)
    burst = 1 if c.t % 1.3 < 0.55 else 0
    c.face("twitch", max(0, osc(c.t, 7)) * burst * k)
    c.add("breathe", max(0, osc(c.t, 3.5)) * burst * 1.4 * k)
    c.mute("look", k)


def stretch(c):
    k, up = c.env(1.0, 1.2), c.window(0.6, 3.6, 0.6)
    c.arm("L", "upL", (-10, -30, -10), up, 4), c.arm("R", "upR", (10, -30, -10), up, 4)
    c.add("spine.pitch", -7 * k), c.add("chest.pitch", -5 * k)
    c.add("head.pitch", -20 * c.window(1.0, 3.4, 0.5))
    c.jaw(0.9 * c.window(1.1, 3.2, 0.5)), c.face("blink", 0.9 * c.window(1.0, 3.6, 0.4))
    c.add("root.y", -6 * up)
    c.mute("look", k)


def ponder(c):
    k, s, o = c.env(1.1, 1.1), c.side, c.out
    c.arm(s, "chin" + s, (-o * 4, 12, 8), k, 5)
    c.add("head.pitch", -9 * k), c.add("head.yaw", -o * 12 * k), c.add("head.roll", o * 7 * k)
    c.mute("look", k)
    if c.t > 2.2:
        c.face("blink", 0.15)


def sway(c):
    k = c.env(0.8, 1.2)
    c.add("root.roll", osc(c.t, 0.42) * 2.2 * k), c.add("head.roll", -osc(c.t, 0.42) * 1.6 * k)


def nod(c):
    k = c.env(0.2, 0.4)
    c.add("head.pitch", max(0, osc(c.t, 1.6)) * 9 * k)
    c.add("earL.pitch", 8 * k), c.add("earR.pitch", 8 * k)


def greet(c):
    s, o, k = c.side, c.out, c.env(0.6, 0.7)
    c.arm(s, "up" + s, (o * osc(c.t, 2.4) * 18, 30, 30), k, 9)
    c.add("head.roll", -o * 7 * k), c.add("earL.pitch", 10 * k), c.add("earR.pitch", 10 * k)


ACTIONS = {"scratch_face": (3.6, scratch_face), "sniff": (4.0, sniff), "stretch": (5.0, stretch),
           "ponder": (5.5, ponder), "sway": (4.4, sway), "nod": (1.4, nod), "greet": (2.8, greet)}
CUES = set(ACTIONS) | {"fish"}          # what [do: ...] may ask for: a move, or a salmon


# ---- how it feels: (seconds, the sign over its head, the move)

def happy(c):
    k = c.env(0.3, 0.6)
    c.add("root.y", -max(0, osc(c.t, 2.3)) * 12 * c.window(0.2, 1.6, 0.2))
    c.add("head.roll", 10 * k), c.add("earL.pitch", 14 * k), c.add("earR.pitch", 14 * k)
    c.face("blink", 0.35 * k)


def laugh(c):
    k, s = c.env(0.3, 0.7), c.side
    c.add("head.pitch", -13 * k), c.add("neck.pitch", -4 * k)
    c.add("chest.roll", osc(c.t, 6.5) * 2.4 * k), c.add("root.y", -abs(osc(c.t, 3.2)) * 4 * k)
    c.jaw((0.45 + 0.4 * max(0, osc(c.t, 5))) * k)
    c.arm(s, "belly" + s, (0, 0, 6), k, 8)
    c.face("blink", 0.6 * k)


def excited(c):
    k, hop = c.env(0.25, 0.7), c.window(0.2, 0.9, 0.2)
    c.add("root.y", -26 * math.sin(clamp((c.t - 0.2) / 0.7, 0, 1) * math.pi))
    c.arm("L", "upL", (10, -40, 30), k * 0.9, 10), c.arm("R", "upR", (-10, -40, 30), k * 0.9, 10)
    c.add("earL.pitch", 16 * k), c.add("earR.pitch", 16 * k), c.add("head.pitch", -6 * k)
    c.face("blink", -0.2 * hop)


def curious(c):
    k, o = c.env(0.6, 0.8), c.out
    c.add("head.roll", o * 17 * k), c.add("spine.pitch", 6 * k), c.add("head.yaw", o * 6 * k)
    c.add("earL.pitch", 12 * k), c.add("earR.pitch", 12 * k)


def surprised(c):
    k = c.env(0.12, 0.9)
    c.add("spine.pitch", -8 * k), c.add("root.y", -9 * k), c.add("head.pitch", -5 * k)
    c.arm("L", "chestL", (-20, -20, 30), k * 0.7, 16), c.arm("R", "chestR", (20, -20, 30), k * 0.7, 16)
    c.add("earL.pitch", 18 * k), c.add("earR.pitch", 18 * k), c.face("blink", -0.25 * k)


def sad(c):
    k = c.env(1.2, 1.2)
    c.add("head.pitch", 18 * k), c.add("neck.pitch", 6 * k), c.add("chest.pitch", 7 * k)
    c.add("root.y", 5 * k)
    c.add("earL.roll", -22 * k), c.add("earR.roll", 22 * k)
    c.add("earL.pitch", -10 * k), c.add("earR.pitch", -10 * k)
    c.face("blink", 0.45 * k), c.mute("look", k)


def shy(c):
    k, s, o = c.env(0.6, 0.8), c.side, c.out
    c.arm(s, "muzzle" + s, (-o * 6, 4, 16), k, 9)
    c.add("head.yaw", -o * 18 * k), c.add("head.pitch", 9 * k), c.add("head.roll", -o * 5 * k)
    c.face("blink", 0.7 * k), c.mute("look", k)


def proud(c):
    k = c.env(0.6, 0.8)
    c.add("chest.pitch", -7 * k), c.add("head.pitch", -10 * k), c.add("root.y", -4 * k)
    c.arm("L", "hipL", (0, 0, 0), k, 7), c.arm("R", "hipR", (0, 0, 0), k, 7)
    c.add("root.y", -3 * max(0, osc(c.t, 0.8)) * k)          # a little rise on its toes


def confused(c):
    k, s, o = c.env(0.6, 0.8), c.side, c.out
    c.arm(s, "crown" + s, (osc(c.t, 3.5) * 8, osc(c.t, 3.5, 0.25) * 5, 10), k, 10)
    c.add("head.roll", -o * (10 + 6 * osc(c.t, 0.6)) * k), c.add("head.pitch", 4 * k)
    c.mute("look", k)


def encouraging(c):
    k, s, o = c.env(0.4, 0.7), c.side, c.out
    c.add("head.pitch", max(0, osc(c.t, 1.6)) * 8 * c.window(0.1, 1.5, 0.2))
    c.arm(s, "chest" + s, (o * 30, -40, 50), k, 8)
    c.add("earL.pitch", 10 * k), c.add("earR.pitch", 10 * k), c.add("head.roll", -o * 5 * k)


def calm(c):
    nod(c)
    c.face("blink", 0.4 * c.env(0.4, 0.6))


MOOD = {"happy": (2.8, "♥", happy), "laugh": (3.2, "ha!", laugh), "excited": (2.8, "!", excited),
        "curious": (3.2, "?", curious), "thinking": (3.6, "…", ponder),
        "surprised": (2.4, "!", surprised), "sad": (4.2, "…", sad), "shy": (3.4, "♡", shy),
        "proud": (3.2, "★", proud), "sleepy": (4.8, "z", stretch), "confused": (3.4, "?", confused),
        "encouraging": (3.0, "✓", encouraging), "calm": (1.8, "", calm)}
SLOW = ("sad",)
OMEGA = {"root": 5, "spine": 4.5, "chest": 5, "neck": 6, "head": 7, "ear": 15, "jaw": 12,
         "blink": 32, "twitch": 30, "breathe": 5}


def omega_of(key):
    return OMEGA.get("ear" if key.startswith("ear") else key.split(".")[0], 6)


class Clip:
    """One action or mood under way, and what its move may do to the frame."""

    def __init__(self, name, dur, run, side):
        self.name, self.dur, self.run, self.side = name, dur, run, side
        self.out = -1 if side == "L" else 1
        self.t, self.stop_at, self.frame = 0.0, dur, None

    def env(self, a, b):
        return ease(self.t / a) * (1 - ease((self.t - (self.stop_at - b)) / b))

    def window(self, a, b, edge=0.3):
        return (ease((self.t - a) / edge) * (1 - ease((self.t - b) / edge)) *
                (1 if self.t < self.stop_at else 0))

    def add(self, key, v):
        self.frame.add(key, v)

    def arm(self, s, goal, off, w, omega):
        self.frame.arms[s].append((goal, off, w, omega))

    def mute(self, what, k):
        self.frame.mutes[what] = max(self.frame.mutes.get(what, 0), k)

    def face(self, k, v):
        f = self.frame.face
        f[k] = min(f[k], v) if v < 0 else max(f[k], v)

    def jaw(self, v):
        self.frame.jaw = max(self.frame.jaw, v)


class Frame:
    """What every layer wants of the body this frame."""

    def __init__(self):
        self.T, self.mutes, self.omegas = {}, {}, {}
        self.arms = {"L": [], "R": []}
        self.face = {"blink": 0, "twitch": 0}
        self.jaw = 0
        self.look = None

    def add(self, key, v):
        self.T[key] = self.T.get(key, 0) + v


DEN_QUIET = 120                    # seconds without a word before it walks off to hide
SALMON_EVERY = (240, 540)          # a salmon now and then, while nobody is chatting
WALK = 170                         # how fast it walks, drawing px a second
STRIDE = 140                       # how far it goes in one cycle of its four paws
# a bear's walk: left hind, left fore, right hind, right fore, a quarter apart
PAWS = (("legL", 0.0), ("armL", 0.25), ("legR", 0.5), ("armR", 0.75))


def gait(u):
    """(how far ahead of its hip or shoulder a paw is, how high it is lifted) at u, 0..1,
    of its cycle: planted for two thirds while the body goes over it, then swung forward."""
    reach = STRIDE * 0.65 / 2
    if u < 0.65:
        return reach - 2 * reach * u / 0.65, 0.0
    k = (u - 0.65) / 0.35
    return -reach + 2 * reach * ease(k), math.sin(k * math.pi) * 24
FISH = (("rise", 1.1), ("wait", 1.5), ("catch", 0.5), ("lift", 0.6), ("chew", 2.6),
        ("sink", 1.0))             # the fishing trip, phase by phase (seconds)


def fish_phase(t):
    """(the phase of the fishing trip at t seconds, how far through it 0..1)."""
    for name, dur in FISH:
        if t < dur:
            return name, t / dur
        t -= dur
    return "done", 1.0


class Salmon:
    """A salmon on the GPU picture: swims in from one side along the bottom (the top of
    the graph below it), leaps to the bear's waiting paw, and is eaten in three bites."""

    FILL, LINE = "#e07a5f", "#ffb4a2"
    BODY = ((-0.5, 0), (-0.25, -0.18), (0.15, -0.2), (0.42, -0.08), (0.5, 0), (0.42, 0.08),
            (0.15, 0.2), (-0.25, 0.18))
    TAIL = ((-0.45, 0), (-0.72, -0.22), (-0.64, 0), (-0.72, 0.22))

    def __init__(self, canvas, to_x, from_left):
        self.c, self.to_x, self.dir = canvas, to_x, 1 if from_left else -1
        w, h = canvas.winfo_width(), canvas.winfo_height()
        self.size = max(24, h * 0.14)
        self.start = -self.size if from_left else w + self.size
        self.x, self.y, self.angle = self.start, h - self.size * 0.3, 0.0
        self.bites = 0

    def swim(self, k, t):
        """k: 0..1 of the way to where it leaps; it wiggles as it goes."""
        h = self.c.winfo_height()
        self.x = self.start + (self.to_x - self.start) * k
        self.y = h - self.size * 0.3 + math.sin(t * 9) * 1.5
        self.angle = math.sin(t * 9) * 0.08

    def draw(self):
        self.c.delete("salmon")
        if self.bites >= 3:
            return
        length = self.size * (1 - 0.28 * self.bites)
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        pts = lambda shape: [v for x, y in shape for v in (
            self.x + (x * self.dir * ca - y * sa) * length, self.y + (x * self.dir * sa + y * ca) * length)]
        self.c.create_polygon(pts(self.TAIL), fill=self.FILL, outline=self.LINE, tags="salmon")
        self.c.create_polygon(pts(self.BODY), fill=self.FILL, outline=self.LINE, tags="salmon")
        ex, ey = pts(((0.3, -0.05),))
        self.c.create_oval(ex - 1.5, ey - 1.5, ex + 1.5, ey + 1.5, fill="#2a1410", outline="",
                           tags="salmon")


class Bear:
    """Orthros the bear. Its den is the left third of the chat card (a canvas of its
    own, `den`); the GPU picture's canvas (`stream`) is where salmon swim.

    It is away, hidden behind the chat box, until you come to the chat: then it walks
    out (waving, the first time), stays while you talk, and walks back behind the box
    after DEN_QUIET seconds without a word. Now and then, while nobody is chatting, a
    salmon swims along the bottom of the GPU picture and the bear climbs up out of the
    chat card to catch it, eats it, and goes back. While you chat it goes fishing only
    when asked (fish(), from a [do: ...] cue or your own words).

    The window calls summon() on any sign of you, heard(), typing(), thinking() and
    answered(), and sets energy (how busy the card is, 0 to 1) each frame of the picture."""

    def __init__(self, den, stream=None, line="#e8f1ff", fill="#0d1524", visible=None):
        self.den, self.stream, self.c = den, stream, den
        self.line, self.fill = line, fill
        self.visible = visible or (lambda: True)
        self.clock = time.monotonic                   # (the tests run it on a clock of their own)
        self.rig = Rig()
        self.items, self.fills = {}, {}               # face number -> polygon, and its colours
        self.palette, self.placed = {}, {}            # colours worked out; where each face is
        self.val, self.vel = {}, {}
        self.drawn, self.order, self.o = None, [], None
        self.energy, self.glow = 0.0, 0.0
        self.where, self.since = "away", self.clock()  # away coming here going up fishing down
        self.walk_x, self.lift, self.greeted = 0.0, 0.0, False
        self.fours_want, self.gait, self.way = 0.0, 0.0, -1     # on all fours, its walk
        self.salmon, self.fish_x, self.then_fish, self.fish_side = None, 0.0, False, "L"
        now = self.clock()
        self.active_at = -1e9
        self.next_salmon = now + random.uniform(*SALMON_EVERY)
        self.reset()
        self.job = None
        self.tick()

    def reset(self):
        now = self.clock()
        self.thinking_on, self.typed_at, self.heard_at, self.answered_at = False, -1e9, -1e9, -1e9
        self.action = self.mood = self.then = None
        self.next_action = now + random.uniform(5, 9)
        self.cool = {}
        self.look = {"what": "viewer", "until": 0, "pt": None}
        self.blink_at, self.blink_until = now + random.uniform(1.5, 4), 0
        self.flick, self.flick_at = None, now + random.uniform(4, 9)
        self.shift = {"roll": 0, "x": 0, "sroll": 0, "at": now + random.uniform(3, 6)}
        self.breath = [0.0, 4.2]
        self.feet = {"L": {"x": 0, "step": None}, "R": {"x": 0, "step": None}}
        self.emote = None
        self.last = now

    # ---- what the window tells it

    def summon(self):
        """You are at the chat: it comes out, or stays a while longer."""
        self.active_at = self.clock()
        if self.where in ("away", "going"):
            self.set("coming")

    def heard(self):
        self.summon()
        self.heard_at = self.clock()
        if not self.mood and self.where == "here":
            self.start("nod")

    def typing(self):
        self.summon()
        self.typed_at = self.clock()
        if self.action and self.action.name == "stretch":
            self.action.stop_at = min(self.action.stop_at, self.action.t + 1.2)

    def thinking(self, on):
        self.thinking_on = bool(on)
        if on:
            self.summon()
            self.next_action = min(self.next_action, self.clock() + random.uniform(1.2, 2.5))

    def answered(self, mood=None, acts=()):
        """Orthros answered: a move it cued, then its mood (one of MOODS); or a nod. A
        salmon asked for comes after."""
        self.summon()
        self.answered_at = self.clock()
        self.look["until"] = 0
        acts = list(acts or ())
        self.then_fish = self.then_fish or "fish" in acts
        mood = mood if mood in MOOD else None
        act = next((a for a in acts if a in ACTIONS), None)
        if act:
            self.start(act)
            self.then = mood
        elif mood:
            self.feel(mood)
        elif not self.then_fish:
            self.start("nod")

    def fish(self):
        """Up out of the chat card to the GPU picture, to catch a salmon."""
        if self.where in ("up", "fishing") or not self.stream:
            return
        self.set("fishing" if self.where == "away" else "up")

    # ---- where it is

    def set(self, where):
        now, self.since, was = self.clock(), self.clock(), self.where
        self.where = where
        self.fours_want = 1.0 if where in ("coming", "going") else 0.0
        if where == "coming":
            if was != "going":                       # from behind the box, at its edge
                self.home()
                self.walk_x, self.way, self.gait = self.offstage(), -1, 0.0
                self.val["fours"], self.vel["fours"] = 1.0, 0.0     # already on all fours
                for f in self.feet.values():
                    f["x"], f["step"] = self.walk_x, None
        elif where == "fishing":
            self.home(self.stream)
            w = self.stream.winfo_width()
            self.fish_x = random.uniform(0.25, 0.75) * w
            self.fish_side = random.choice("LR")      # the paw that catches, on the salmon's side
            self.salmon = Salmon(self.stream, 0, self.fish_side == "L")
            self.walk_x, self.lift = 0.0, 0.0
            for f in self.feet.values():
                f["x"], f["step"] = 0.0, None
        elif where == "down":
            self.home()
            self.walk_x = 0.0
            for f in self.feet.values():
                f["x"], f["step"] = 0.0, None
        elif where == "away":
            self.home()
            self.next_salmon = now + random.uniform(*SALMON_EVERY)

    def home(self, canvas=None):
        """Draw on the den (or `canvas`) from now on: what it drew elsewhere goes."""
        self.c.delete("bear", "extra", "salmon")
        self.items, self.fills, self.placed, self.order, self.drawn = {}, {}, {}, [], None
        self.c, self.o = canvas or self.den, None

    def offstage(self):
        """How far right (drawing px) it stands when hidden behind the chat box."""
        w, h = self.den.winfo_width(), self.den.winfo_height()
        scale = self.den_scale(w, h)
        return (w / 2 + 0.5 * ART_TALL * scale + 8) / scale     # (wider on all fours)

    @staticmethod
    def den_scale(w, h):
        return max(0.05, min(h * 0.86 / ART_TALL, w * 0.8 / ART_W))

    def spot(self, w, h):
        """(x of its feet's middle, y of its feet, scale) on the canvas it is on now."""
        if self.c is self.stream:
            scale = h * 0.85 / ART_TALL
            return self.fish_x, h + self.lift, scale
        return w / 2, h - 3 + self.lift, self.den_scale(w, h)

    def interactive(self, now):
        return self.thinking_on or now - self.active_at < DEN_QUIET

    # ---- starting things

    def start(self, name, side=None):
        dur, run = ACTIONS[name]
        if self.action:
            self.action.stop_at = min(self.action.stop_at, self.action.t + 0.35)
        self.action = Clip(name, dur, run, side or random.choice("LR"))
        self.cool[name] = self.clock()
        return True

    def feel(self, name):
        dur, glyph, run = MOOD[name]
        if self.action:
            self.action.stop_at = min(self.action.stop_at, self.action.t + 0.4)
        self.mood = Clip(name, dur, run, "R")       # the chat is to its right
        self.mood.t = -0.25
        if glyph:
            self.emote = {"glyph": glyph, "at": self.clock() + 0.15}
        return True

    def decide(self, now):
        """Pick what to do next, now and then, from what's going on."""
        if self.where != "here" or self.action or self.mood:
            return
        if self.then_fish:
            self.then_fish = False
            return self.fish()
        if not self.interactive(now):
            return self.set("going")
        if now < self.next_action:
            return
        self.next_action = now + random.uniform(12, 25)     # a calm bear is a cheap one
        if now - self.typed_at < 5 or now - self.heard_at < 2.5 or now - self.answered_at < 4:
            return
        ok = lambda name, secs: now - self.cool.get(name, -1e9) > secs
        weights = ({"ponder": 2 * ok("ponder", 45), "sway": 3 * ok("sway", 12),
                    "sniff": 2 * ok("sniff", 20)}
                   if self.thinking_on else
                   {"scratch_face": 0.8 * ok("scratch_face", 180), "sniff": 2 * ok("sniff", 30),
                    "stretch": 1 * ok("stretch", 200), "sway": 1 * ok("sway", 25)})
        pick = [(k, w) for k, w in weights.items() if w > 0]
        if pick:
            r = random.uniform(0, sum(w for _, w in pick))
            for k, w in pick:
                r -= w
                if r <= 0:
                    return self.start(k)
            self.start(pick[-1][0])

    # ---- one frame

    def spring(self, key, target, dt, omega):
        x, v = self.val.get(key, target), self.vel.get(key, 0)
        steps = math.ceil(dt * omega / 0.5) or 1
        h = dt / steps                   # small steps keep quick springs stable
        for _ in range(steps):
            v += (omega * omega * (target - x) - 2 * 0.86 * omega * v) * h
            x += v * h
        self.val[key], self.vel[key] = x, v
        return x

    def lively(self, now):
        """Is it doing something, or is the chat going? Else it only stands and breathes."""
        return bool(self.where != "here" or self.action or self.mood or self.emote or
                    self.thinking_on or now - max(self.typed_at, self.heard_at, self.answered_at) < 6)

    def tick(self):
        now = self.clock()
        rate = 1 if self.where == "away" else FPS if self.lively(now) else IDLE_FPS
        self.job = self.c.after(1000 // rate, self.tick)
        if not self.visible():
            self.last = now
            return
        if self.where == "away":                 # behind the chat box: nothing to draw
            self.last = now
            if self.stream and now > self.next_salmon and not self.interactive(now):
                self.fish()
            return
        try:
            self.step(now)
        except Exception:                # a bear must never take the window down
            self.c.after_cancel(self.job)
            self.c.delete("bear", "extra", "salmon")

    def scene(self, fr, now, dt):
        """Where it is going, laid over everything else: walking in or out, climbing up
        out of the den or back down into it, or the fishing trip."""
        t = now - self.since
        w, h = self.c.winfo_width(), self.c.winfo_height()
        o = self.o = self.o or self.spot(w, h)       # (none yet on a canvas it just came to)
        tall = ART_TALL * o[2]
        if self.where in ("coming", "going"):
            # On all fours, turned towards where it is going, with a bear's four-beat walk
            # (see gait()); down before it sets off, up again once it is there.
            goal = 0.0 if self.where == "coming" else self.offstage()
            way = self.way = 1 if goal > self.walk_x else -1 if goal < self.walk_x else self.way
            down = self.val.get("fours", 0)
            arrived = self.walk_x == goal
            self.fours_want = 0.0 if arrived and self.where == "coming" else 1.0
            if not arrived and down > 0.6:
                step = way * min(WALK * dt * ease((down - 0.6) / 0.3), abs(goal - self.walk_x))
                self.walk_x += step
                self.gait += abs(step) / STRIDE
            fr.add("root.yaw", way * 70 * down)          # near side-on: it reads as a walk
            fr.look = ((self.walk_x + way * 600 + ART_MID, 700, 400), 0.8)   # where it is going
            if arrived and self.where == "going":
                self.set("away")
            elif arrived and down < 0.08:
                self.where = "here"
                if not self.greeted:              # its first time out this session
                    self.greeted = True
                    self.start("greet", "R")
        elif self.where == "up":                  # paw over paw, up out of the den's top
            k = min(1.0, t / 1.4)
            self.lift = -(h + tall * 0.1) * ease(k)
            self.climb(fr, t)
            if k >= 1:
                self.set("fishing")
        elif self.where == "down":                # back into the den from its top
            k = min(1.0, t / 1.2)
            self.lift = -(h + tall * 0.1) * (1 - ease(k))
            self.climb(fr, t, 1 - k)
            if k >= 1:
                self.lift, self.where = 0.0, "here"
        elif self.where == "fishing":
            self.fishing(fr, t, tall)

    def climb(self, fr, t, k=1.0):
        """Reaching up paw over paw."""
        for s, ph in (("L", 0), ("R", 0.5)):
            reach = 0.5 + 0.5 * math.sin((t * 2.2 + ph) * math.pi * 2)
            fr.arms[s].append((add(self.rig.anchor("up" + s), (0, -60 * reach - 40, 10)), None, k, 12))
        fr.add("head.pitch", -14 * k), fr.add("spine.pitch", -4 * k)
        fr.add("root.roll", math.sin(t * 2.2 * math.pi * 2) * 3 * k)

    def fishing(self, fr, t, tall):
        """Up from below the GPU picture's bottom edge: wait, catch the leaping salmon,
        eat it in three bites, and sink back down."""
        fish, h = self.salmon, self.stream.winfo_height()
        phase, k = fish_phase(t)
        s = self.fish_side
        o = self.o or self.spot(self.stream.winfo_width(), h)
        paw = self.rig.project(self.rig.joint("paw" + s), o)
        out = -1 if s == "L" else 1
        self.lift = tall * (1.05 - 0.6 * ease(k) if phase == "rise" else 0.45 + 0.6 * ease(k)
                            if phase == "sink" else 1.05 if phase == "done" else 0.45)
        ready = add(self.rig.anchor("up" + s), (out * 40, 60, 40))
        if phase in ("rise", "wait"):
            fish.to_x = paw[0] + out * fish.size
            fish.swim(min(1.0, t / (FISH[0][1] + FISH[1][1])), t)
            fr.arms[s].append((ready, None, ease(min(1.0, t / 1.4)), 8))
            fr.look = (self.to_art(fish.x, fish.y, 200), 0.9)
            fr.add("earL.pitch", 12), fr.add("earR.pitch", 12)
        elif phase == "catch":                    # it leaps, and the paw comes down on it
            arc = math.sin(k * math.pi) * h * 0.18
            fish.x = fish.to_x + (paw[0] - fish.to_x) * k
            fish.y = h - fish.size * 0.3 + (paw[1] - h) * k - arc
            fish.angle = -out * (0.8 - 1.6 * k)
            grab = self.to_art(fish.x, fish.y, 60)
            fr.arms[s].append((lerp3(ready, grab, ease(k)), None, 1, 16))
            fr.look = (grab, 1)
        else:
            if phase in ("lift", "chew"):        # paw to muzzle, and eat
                mouth = self.rig.anchor("muzzle" + s)
                fr.arms[s].append((add(mouth, (out * 30, 10, 30)), None,
                                   ease(k) if phase == "lift" else 1, 10))
                fish.x, fish.y = paw
                fish.angle = math.pi / 2 * out
                if phase == "chew":
                    fr.jaw = max(fr.jaw, 0.25 + 0.45 * max(0, math.sin(t * 7)))
                    fr.face["blink"] = max(fr.face["blink"], 0.5)
                    fish.bites = min(3, int(k * 3.4))
                    fr.add("head.pitch", 6)
            if phase in ("sink", "done"):
                fish.bites = 3
            if phase == "chew" and k > 0.9 and not self.emote:
                self.emote = {"glyph": "♥", "at": self.clock()}
        if phase == "done":
            self.salmon = None
            self.c.delete("salmon")
            self.set("down" if self.interactive(self.clock()) else "away")

    def to_art(self, x, y, z=0.0):
        ox, feet, scale = self.o
        return (ART_MID + (x - ox) / scale, ART_FEET + (y - feet) / scale, z)

    def step(self, now):
        dt = clamp(now - self.last, 0, 0.25)
        self.last = now
        t = now
        self.glow += (self.energy - self.glow) * min(1, dt / 1.5)
        self.decide(now)
        fr = Frame()
        self.scene(fr, now, dt)
        if self.where == "away":
            return
        # posture: down on all fours, the back level and towards you, the head up and ahead
        down = self.spring("fours", self.fours_want, dt, 2.4)
        if down > 0.001:
            beat = math.sin(self.gait * math.pi * 4)          # twice a cycle, a paw lands
            fr.add("spine.pitch", 70 * down), fr.add("chest.pitch", 6 * down)
            fr.add("root.y", (72 - 4 * abs(beat)) * down), fr.add("root.z", -30 * down)
            fr.add("neck.pitch", -42 * down), fr.add("head.pitch", -26 * down)
            fr.add("earL.pitch", -6 * down), fr.add("earR.pitch", -6 * down)
            fr.add("spine.roll", math.sin(self.gait * math.pi * 2) * 3 * down)
            fr.add("head.roll", -math.sin(self.gait * math.pi * 2) * 2 * down)
        # life: breathing at a varying rhythm, slow weight shifts with stillness between
        self.breath[0] += dt / self.breath[1]
        if self.breath[0] >= 1:
            self.breath = [self.breath[0] - 1, random.uniform(3.6, 4.8)]
        breath = math.sin(self.breath[0] * math.pi * 2)
        fr.add("breathe", breath * (1.1 if self.thinking_on else 0.8))
        fr.add("root.y", -breath * 1.2)
        if now > self.shift["at"]:
            still = random.random() < 0.4
            self.shift = {"roll": 0 if still else random.uniform(-2, 2), "x": 0 if still else random.uniform(-6, 6),
                          "sroll": 0 if still else random.uniform(-1.2, 1.2), "at": now + random.uniform(5, 12)}
        fr.add("root.roll", self.shift["roll"]), fr.add("root.x", self.shift["x"])
        fr.add("spine.roll", self.shift["sroll"])
        fr.omegas.update({"root.roll": 1.5, "root.x": 1.5, "spine.roll": 1.5})
        fr.add("spine.pitch", 2.5), fr.add("earL.pitch", 6), fr.add("earR.pitch", 6)   # attentive
        fr.add("head.yaw", (osc(t, 0.071) + osc(t, 0.113, 0.3)) * 1.4)
        fr.add("head.pitch", osc(t, 0.093, 0.6) * 1.2)
        # blinks (now and then a double), ear flicks
        if now > self.blink_at:
            self.blink_until = now + 0.11
            self.blink_at = now + (0.24 if random.random() < 0.15 else random.uniform(2.5, 6.5))
        if now < self.blink_until:
            fr.face["blink"] = 1
        if now > self.flick_at:
            self.flick = (random.choice(("earL", "earR")), now + 0.2)
            self.flick_at = now + random.uniform(6, 15)
        if self.flick and now < self.flick[1]:
            fr.add(self.flick[0] + ".pitch", -26)
        for which in ("action", "mood"):
            clip = getattr(self, which)
            if not clip:
                continue
            clip.t += dt
            if clip.t >= 0:
                clip.frame = fr
                clip.run(clip)
            if clip.t >= clip.stop_at:
                setattr(self, which, None)
                if which == "action":
                    self.next_action = max(self.next_action, now + random.uniform(8, 15))
                    if self.then:                    # the mood that came with a cued move
                        self.feel(self.then)
                        self.then = None
        # where it looks: the chat beside it, you, or off somewhere
        head = self.rig.joint("head")
        look = self.look_target(now, head)
        if fr.look:
            look = lerp3(look, fr.look[0], fr.look[1])
        lk = 1 - fr.mutes.get("look", 0)
        d = sub(look, head)
        yaw = clamp(math.degrees(math.atan2(d[0], d[2])), -36, 36) - self.val.get("root.yaw", 0)
        pitch = clamp(math.degrees(math.atan2(d[1], math.hypot(d[0], d[2]))), -22, 28)
        fr.add("neck.yaw", yaw * 0.35 * lk), fr.add("head.yaw", yaw * 0.65 * lk)
        fr.add("head.pitch", pitch * 0.7 * lk)
        # springs for every part
        pose = {"face": {}}
        keys = set(fr.T) | {k for k in self.val if "." in k and not k.endswith("@")} | {"breathe"}
        for key in keys:
            omega = fr.omegas.get(key) or omega_of(key) * (0.6 if self.mood and self.mood.name in SLOW else 1)
            v = self.spring(key, fr.T.get(key, 0), dt, omega)
            if key == "breathe":
                pose["breathe"] = v
                continue
            part, axis = key.split(".")
            pose.setdefault(part, {})[axis] = v
        pose.setdefault("root", {})["x"] = pose.get("root", {}).get("x", 0) + self.walk_x
        pose["face"]["blink"] = self.spring("blink", fr.face["blink"], dt, OMEGA["blink"])
        pose["face"]["twitch"] = self.spring("twitch", fr.face["twitch"], dt, OMEGA["twitch"])
        pose["jaw"] = self.spring("jaw", fr.jaw, dt, OMEGA["jaw"])
        self.rig.set_pose(pose)              # body first: the paws reach from where it now is
        # On all fours each paw is on the ground under its hip or shoulder, planted or swung
        # forward by the gait; standing, the feet stay planted, and when the hips move far
        # enough over a foot steps after them.
        root_x = self.val.get("root.x", 0) + self.walk_x
        ground = {}
        for limb, off in PAWS:
            ahead, up = gait((self.gait + off) % 1)
            s = limb[-1]
            if limb.startswith("leg"):
                hip, rest = self.rig.joint("thigh" + s), self.rig.rest("foot" + s)
                ground[limb] = (hip[0] + self.way * ahead, rest[1] - up, hip[2] + 10)
            else:
                sh = self.rig.joint("upper" + s)
                ground[limb] = (sh[0] + (-6 if s == "L" else 6) + self.way * ahead,
                                ART_FEET - 52 - up, sh[2] + 8)
        for s in "LR":
            ft, other = self.feet[s], self.feet["R" if s == "L" else "L"]
            if down > 0.5:
                ft["x"], ft["step"] = root_x, None          # (no step to take on getting up)
            if not ft["step"] and not other["step"] and abs(root_x - ft["x"]) > 18:
                ft["step"] = [ft["x"], root_x, 0.0]
            lift = 0
            if ft["step"]:
                ft["step"][2] += dt / 0.32
                k = ease(ft["step"][2])
                ft["x"] = ft["step"][0] + (ft["step"][1] - ft["step"][0]) * k
                lift = math.sin(min(1, ft["step"][2]) * math.pi) * 16
                if ft["step"][2] >= 1:
                    ft["step"] = None
            rest = self.rig.rest("foot" + s)
            pose["leg" + s] = lerp3((rest[0] + ft["x"], rest[1] - lift, rest[2]), ground["leg" + s],
                                    ease(down))
        # paws: hanging, or wherever a move reaches, or on the ground
        for s in "LR":
            goal, omega = self.rig.anchor("rest" + s), 9
            for g, off, w, om in fr.arms[s]:
                g = add(self.rig.anchor(g), off or (0, 0, 0)) if isinstance(g, str) else g
                goal = lerp3(goal, g, clamp(w, 0, 1))
                if w > 0.3:
                    omega = om or omega
            if down > 0.001:
                goal, omega = lerp3(goal, ground["arm" + s], ease(down)), max(omega, 14)
            pose["arm" + s] = tuple(self.spring("paw%s.%s@" % (s, ax), goal[i], dt, omega)
                                    for i, ax in enumerate("xyz"))
        self.rig.set_pose(pose)
        self.draw(now)
        if self.salmon:
            self.salmon.draw()

    def look_target(self, now, head):
        w, h = self.c.winfo_width(), self.c.winfo_height()
        chat = self.to_art(w * 1.8, h * 0.5, 380) if self.o else (ART_MID + 900, 500, 380)
        if now - self.typed_at < 3.5:
            return self.to_art(w * 1.6, h * 1.05, 380) if self.o else chat   # the box you type in
        if now > self.look["until"]:
            weights = {"chat": 8 if now - self.answered_at < 8 else 3, "viewer": 2.5, "away": 1}
            r, what = random.uniform(0, sum(weights.values())), "viewer"
            for what, wt in weights.items():
                r -= wt
                if r <= 0:
                    break
            self.look = {"what": what, "until": now + random.uniform(2.5, 7.5),
                         "pt": (random.uniform(-300, 300), random.uniform(-260, 40), 900)}
        what = self.look["what"]
        if what == "chat":
            return chat
        if what == "away":
            return add(head, self.look["pt"])
        return (head[0], head[1] + 40, VIEWER)

    # ---- drawing

    def colours(self, lit):
        """A face's fill and its lines, lit from within as the card gets busy (and only
        faintly: no glow spills outside the bear). Tenths of each, worked out once."""
        key = (round(lit, 1), round(self.glow, 1))
        if key not in self.palette:
            lit, g = key
            self.palette[key] = (mix(mix(self.fill, self.line, 0.03 + 0.09 * lit), GLOW, 0.03 + 0.10 * g),
                                 mix(self.line, GLOW, 0.12 + 0.4 * g))
        return self.palette[key]

    def draw(self, now):
        """Draw the body if it moved enough to see (or its glow changed). True if drawn."""
        w, h = self.c.winfo_width(), self.c.winfo_height()
        if w < 20 or h < 40:
            return False
        o = self.o = self.spot(w, h)
        emote = self.emote_at(now, o)
        glow = round(self.glow * 10)
        if self.drawn and (emote, glow, o) == self.drawn[0]:
            # Drawing is the expensive part (tkinter), so slow movement -- breathing,
            # a drifting head -- is drawn now and then, and movement at full rate.
            moved = max(max(abs(p[0] - q[0]), abs(p[1] - q[1]))
                        for p, q in zip(self.rig.out, self.drawn[2])) * o[2]
            # (2026-10-21: while it moved, small moves were drawn only every 0.4 s, so a
            # slow turn of the head played at two or three frames a second and looked jerky)
            if self.lively(now) and moved < 0.4 or not self.lively(now) and (
                    moved < 1.0 or moved < 1.5 and now - self.drawn[1] < 1.0):
                return False
        shapes = self.rig.shapes(o)
        self.drawn = ((emote, glow, o), now, [p[:] for p in self.rig.out])
        order = [key for key, _, _, _ in shapes]
        for key, n, flat, lit in shapes:
            item = self.items.get(key)
            fill, line = self.colours(lit)
            face = self.rig.faces[n]
            if face.get("back") and face["feature"]:
                line = fill                  # the inside of the face: no eyes drawn on it
            if item is None:
                self.items[key] = self.c.create_polygon(flat, fill=fill, outline=line, width=1,
                                                        joinstyle="round", tags="bear")
                self.fills[key], self.placed[key] = (fill, line), flat
                continue
            # tkinter repaints whatever lies under a changed item: only what moved is
            # changed, so a blink repaints the eyes and not the whole bear
            was = self.placed[key]
            if len(flat) != len(was) or max(abs(a - b) for a, b in zip(flat, was)) > 0.35:
                self.c.coords(item, flat)
                self.placed[key] = flat
            if self.fills.get(key) != (fill, line):
                self.c.itemconfigure(item, fill=fill, outline=line)
                self.fills[key] = (fill, line)
            if key not in self.order:
                self.c.itemconfigure(item, state="normal")
        if order != self.order:              # restacked only when the order changes
            for n in order:
                self.c.tag_raise(self.items[n])
            for n in set(self.items) - set(order):
                self.c.itemconfigure(self.items[n], state="hidden")
            self.order = order
        self.c.delete("extra")
        mouth = self.val.get("jaw", 0)
        if mouth > 0.05:                     # an open mouth: a dark gap under the nose
            m = self.rig.project(lerp3(self.rig.anchor("chinL"), self.rig.anchor("chinR"), 0.5), o)
            nz = self.rig.project(self.rig.anchor("nose"), o)
            cx, cy = (m[0] + nz[0]) / 2, nz[1] + (m[1] - nz[1]) * 0.62
            rx, ry = 11 * o[2], 14 * mouth * o[2]
            self.c.create_oval(cx - rx, cy - ry, cx + rx, cy + ry, fill=self.line, outline="",
                               tags="extra")
        if emote:                            # a small sign over its head for a mood
            x, y, glyph = emote
            r = 13
            self.c.create_oval(x - r, y - r, x + r, y + r, fill=self.fill, outline=self.line,
                               width=1.5, tags="extra")
            self.c.create_text(x, y + 1, text=glyph, fill="#ff6b9a" if glyph in "♥♡" else self.line,
                               font=("Segoe UI", 9 if len(glyph) > 1 else 12, "bold"), tags="extra")
        return True

    def emote_at(self, now, o):
        e = self.emote
        if not e:
            return None
        age = now - e["at"]
        if age < 0:
            return None
        if age > 2.4:
            self.emote = None
            return None
        top = self.rig.project(self.rig.anchor("top"), o)
        return (round(top[0] + 30), round(max(15, top[1] - 14 - age * 8)), e["glyph"])
