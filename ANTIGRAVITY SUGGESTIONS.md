# ANTIGRAVITY SUGGESTIONS

*Ideas for integrating [fstandhartinger/ralph-wiggum](https://github.com/fstandhartinger/ralph-wiggum) open source code to improve OrthrosCode.*

## What is Ralph Wiggum?

Ralph Wiggum (in this flavour) combines Geoffrey Huntley's original iterative bash loop with SpecKit-style specifications for fully autonomous AI-assisted software development.

### Key Features
* 🔄 **Iterative Self-Correction** — Each loop picks ONE task, implements it, verifies, and commits
* 📋 **Spec-Driven Development** — Professional specifications with clear acceptance criteria
* 🎯 **Completion Verification** — Agent only outputs `<promise>DONE</promise>` when criteria are 100% met
* 🧠 **Fresh Context Each Loop** — Every iteration starts with a clean context window
* 📝 **Shared State on Disk** — `IMPLEMENTATION_PLAN.md` persists between loops

## How It Works

Based on [Geoffrey Huntley's methodology](https://github.com/ghuntley/how-to-ralph-wiggum):

```text
┌─────────────────────────────────────────────────────────────┐
│ RALPH LOOP                                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐     │
│  │    Orient    │──▶│  Pick Task   │──▶│  Implement   │     │
│  │  Read specs  │   │  from Plan   │   │    & Test    │     │
│  └──────────────┘   └──────────────┘   └──────────────┘     │
│                                               │             │
│   ┌───────────────────────────────────────────┘             │
│   ▼                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐     │
│  │    Verify    │──▶│    Commit    │──▶│ Output DONE  │     │
│  │   Criteria   │   │    & Push    │   │ (if passed)  │     │
│  └──────────────┘   └──────────────┘   └──────────────┘     │
│                                               │             │
│   ┌───────────────────────────────────────────┘             │
│   ▼                                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │     Bash loop checks for <promise>DONE</promise>     │   │
│  │                                                      │   │
│  │        If found: next iteration | If not: retry      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### The Magic Phrase
The agent outputs `<promise>DONE</promise>` ONLY when:
* All acceptance criteria are verified
* Tests pass
* Changes are committed and pushed
* The shell or PowerShell loop checks for this phrase. If not found, it retries.

### Two Modes
| Mode | Purpose | Command |
|---|---|---|
| **build (default)** | Pick spec/task, implement, test, commit | `./scripts/ralph-loop.sh` |
| **plan (optional)** | Create detailed task breakdown from specs | `./scripts/ralph-loop.sh plan` |

On Windows PowerShell, use the matching `.ps1` scripts, for example `.\scripts\ralph-loop.ps1` or `.\scripts\ralph-loop-codex.ps1 plan`.

**Planning is OPTIONAL**
Most projects work fine directly from specs. The agent simply:
* Looks at `specs/` folder
* Picks the highest priority incomplete spec
* Implements it completely
* Only use plan mode when you want a detailed breakdown of specs into smaller tasks.

*Tip: Delete `IMPLEMENTATION_PLAN.md` to return to working directly from specs.*

## Installation

### For AI Agents (Recommended)
Point your AI agent to this repo and say:
> "Set up Ralph Wiggum in my project using https://github.com/fstandhartinger/ralph-wiggum"

The agent will read [INSTALLATION.md](https://github.com/fstandhartinger/ralph-wiggum/blob/main/INSTALLATION.md) and guide you through a lightweight, pleasant setup:
* **Quick Setup (~1 min)** — Create directories, download scripts
* **Project Interview (~3-5 min)** — Focus on your vision and goals, not technical minutiae
* **Constitution** — Create a guiding document for all future sessions
* **Next Steps** — Clear guidance on creating specs and starting Ralph

The interview prioritizes understanding what you're building and why over interrogating you about tech stack details. For existing projects, the agent can detect your stack automatically.

### Manual Setup
See [INSTALL.md](https://github.com/fstandhartinger/ralph-wiggum/blob/main/INSTALL.md) for step-by-step manual instructions.

## Usage

### 1. Create Specifications
Tell your AI what you want to build, or use `/speckit.specify` in Cursor:
`/speckit.specify Add user authentication with OAuth`

This creates `specs/001-user-auth/spec.md` with:
* Feature requirements
* Clear, testable acceptance criteria (critical!)
* Completion signal section

*The key to good specs:* Each spec needs acceptance criteria that are specific and testable. Not "works correctly" but "user can log in with Google and session persists across page reloads."

### 2. (Optional) Run Planning Mode
`./scripts/ralph-loop.sh plan`
Creates `IMPLEMENTATION_PLAN.md` with detailed task breakdown. This step is optional — most projects work fine directly from specs.

### 3. Run Build Mode
`./scripts/ralph-loop.sh` # Unlimited iterations 
`./scripts/ralph-loop.sh 20` # Max 20 iterations

Each iteration:
* Picks the highest priority task
* Implements it completely
* Verifies acceptance criteria
* Outputs `<promise>DONE</promise>` only if criteria pass
* Bash loop checks for the phrase
* Context cleared, next iteration starts

## Logging (All Output Captured)
Every loop run writes all output to log files in `logs/`:
* Session log: `logs/ralph_*_session_YYYYMMDD_HHMMSS.log` (entire run, including CLI output)
* Iteration logs: `logs/ralph_*_iter_N_YYYYMMDD_HHMMSS.log` (per-iteration CLI output)
* Codex last message: `logs/ralph_codex_output_iter_N_*.txt`

If something gets stuck, these logs contain the full verbose trace.

### NR_OF_TRIES Tracking
Each spec tracks how many times it has been attempted. After 10 attempts without completion, the spec is flagged as "stuck" and should be split into smaller specs.

```bash
# Check stuck specs
source scripts/lib/nr_of_tries.sh
print_stuck_specs_summary
```
The counter is stored as a comment in the spec file: `<!-- NR_OF_TRIES: 5 -->`

## Telegram Notifications (Optional)
Get progress updates via Telegram! See [TELEGRAM_SETUP.md](https://github.com/fstandhartinger/ralph-wiggum/blob/main/TELEGRAM_SETUP.md) for setup.

```bash
# Enable telegram (requires TG_BOT_TOKEN and TG_CHAT_ID)
./scripts/ralph-loop.sh 
# Enable audio notifications (also requires CHUTES_API_KEY)
./scripts/ralph-loop.sh --telegram-audio 
# Disable telegram
./scripts/ralph-loop.sh --no-telegram
```

What you'll get:
🚀 Loop start notifications
✅ Spec completion notifications with mermaid diagrams
⚠️ Warnings for consecutive failures or stuck specs
🏁 Summary when loop finishes

## Completion Logs
On each spec completion, entries are created in `completion_log/`:
* `YYYY-MM-DD--HH-MM-SS--spec-name.md` — Summary and mermaid code
* `YYYY-MM-DD--HH-MM-SS--spec-name.png` — Rendered mermaid diagram
These provide a visual history of what was built.

## Using Codex Instead
`./scripts/ralph-loop-codex.sh plan`
`./scripts/ralph-loop-codex.sh`

PowerShell:
`.\scripts\ralph-loop-codex.ps1 plan`
`.\scripts\ralph-loop-codex.ps1`

## File Structure
```text
project/ 
├── .specify/ 
│ └── memory/ 
│     └── constitution.md     # Single source of truth for all agent behavior 
├── specs/ 
│ └── NNN-feature-name.md     # Feature specifications 
├── scripts/ 
│ ├── ralph-loop.sh           # Claude Code loop 
│ ├── ralph-loop.ps1          # Claude Code loop for PowerShell 
│ ├── ralph-loop-codex.sh     # OpenAI Codex loop 
│ ├── ralph-loop-codex.ps1    # OpenAI Codex loop for PowerShell 
│ ├── ralph-loop-gemini.sh    # Google Gemini loop 
│ ├── ralph-loop-gemini.ps1   # Google Gemini loop for PowerShell 
│ ├── ralph-loop-copilot.sh   # GitHub Copilot loop 
│ ├── ralph-loop-copilot.ps1  # GitHub Copilot loop for PowerShell 
│ └── lib/                    # Shared shell and PowerShell helpers 
├── AGENTS.md                 # Points to constitution 
└── CLAUDE.md                 # Points to constitution
```
The constitution is the single source of truth. Optional features (Telegram, GitHub Issues, completion logs) are configured there — not baked into the scripts.

## Core Principles
1. **Fresh Context Each Loop** — Each iteration gets a clean context window. The agent reads files from disk each time.
2. **Shared State on Disk** — `IMPLEMENTATION_PLAN.md` persists between loops. Agent reads it to pick tasks, updates it with progress.
3. **Backpressure via Tests** — Tests, lints, and builds reject invalid work. Agent must fix issues before the magic phrase.
4. **Completion Verification** — Agent only outputs `<promise>DONE</promise>` when acceptance criteria are 100% verified. The bash loop enforces this.
5. **Let Ralph Ralph** — Trust the AI to self-identify, self-correct, and self-improve. Observe patterns and adjust prompts.

## Alternative Spec Sources
During installation, you can choose:
* **SpecKit Specs (default)** — Markdown files in `specs/`
* **GitHub Issues** — Fetch from a repository
* **Custom Source** — Your own mechanism
The constitution and prompts adapt accordingly.

## Agent Skills Compatibility
Ralph Wiggum follows the [Agent Skills specification](https://agentskills.io/) and is compatible with:
* [Vercel add-skill](https://github.com/vercel-labs/add-skill) `npx add-skill fstandhartinger/ralph-wiggum`
* [OpenSkills](https://github.com/numman-ali/openskills) `openskills install fstandhartinger/ralph-wiggum`
* [Skillset](https://github.com/climax-tools/skillset) `skillset add fstandhartinger/ralph-wiggum`

Works with: Claude Code, Cursor, Codex, Windsurf, Amp, OpenCode, and more.

## Credits
This approach builds upon:
* [Geoffrey Huntley's how-to-ralph-wiggum](https://github.com/ghuntley/how-to-ralph-wiggum) — The original methodology
* [Original Ralph Wiggum technique](https://awesomeclaude.ai/ralph-wiggum) — By the Claude community
* [Claude Code Ralph Wiggum plugin](https://github.com/anthropics/claude-code/tree/main/plugins/ralph-wiggum)
* [SpecKit](https://github.com/github/spec-kit) by GitHub — Spec-driven development

Our contribution: Combining the bash loop approach with SpecKit-style specifications and a smooth AI-driven installation process.
