# Design rules

Read-only. Apply these to anything a person will look at.

## Readable first
- Text must never overlap other text or UI. Give each element its own space.
- Contrast: light text on dark, or dark on light. Never mid-tone on mid-tone.
  If text sits on busy art, put a dark panel or a 1-2 px outline behind it.
- One font size per role: title, label, body. No more than three sizes.

## Hierarchy
- The most important thing on screen is the largest or brightest. Only one.
- Group related things; separate unrelated ones with space, not lines.
- Align to edges. Same margin everywhere (8, 16 or 24 px). No stray offsets.

## Colour
- 3-5 colours total, plus neutrals. Pick them once, name them, reuse them.
- Saturated colour only for what the player must notice. Everything else muted.
- Anything interactive or important gets an outline or shadow to separate it
  from the background. Pale on pale disappears.

## Space and shape
- Leave empty space. A crowded screen reads as broken.
- Rounded corners and soft shadows read as finished; hard raw rectangles read
  as placeholder.
- Keep things inside the screen with a margin. Nothing touching the edge.

## Motion and feedback
- Every action gets a visible response within a frame: a flash, a shake, a
  change of colour.
- Ease movement in and out. Nothing starts or stops instantly.

## Check your work
- Squint at it: can you still tell what matters most? If not, fix hierarchy.
- One whole surface per layer. A gradient or background drawn in halves leaves
  a visible seam.
