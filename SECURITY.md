# Security policy

Deskhand lets an AI agent see and control a desktop, so its safety checks are the core of the project.
Reports about ways around them are very welcome.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.10.x  | yes (latest release and `main`) |
| 0.6.x to 0.9.x | no, update to 0.10.x (these were never published as releases) |
| 0.5.x and older | no |

Version 0.5.4 and older contain an MCP `open_app(args)` hole that could run commands without approval
(closed in 0.6.0); do not keep running them.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Report it privately through GitHub:
<https://github.com/sobelendimm/deskhand/security/advisories/new>

Include the Deskhand version (`deskhand status`), your desktop (Plasma/KWin version), and the steps that
reproduce the problem. Deskhand is a one-person project; reports are answered as soon as possible and the
fix is credited to the reporter unless they prefer otherwise.

## What counts

- Input reaching a window, tab or screen other than the checked target (title/class lock, active-window
  check, cursor check).
- A sensitive action (payment, authorisation, account deletion, Enter/space on a payment page) going
  through without the user's approval.
- Input sent while the STOP switch is on, or to the user's screen while they are in a game or watching a
  film.
- Another local program reading or driving the invisible background desktop or its signed-in app copies.
- The session bridge copying credentials it is meant to leave out, or writing into the user's real
  profile.
- The activity log recording text typed with `--secret`.

Problems that need an attacker who already controls the user's account or session are generally out of
scope, but hardening ideas are still welcome as normal issues.

## Security model

Deskhand protects against an agent's **mistakes** and against a **confused or deceived agent** (prompt
injection, wrong targets, runaway loops). Approvals, STOP, forbidden windows and the busy checks exist for
that case: the agent has no tool or command that approves its own request or lifts the user's STOP.

It is **not a sandbox**. Known design limits, which are not vulnerabilities in themselves:

- A malicious process running under the **same user account** can act like the panel: the panel is recognised
  by process identity (socket peer, start time, executable, command line, working directory), which stops a
  misbehaving agent, not another program that runs as the user. The settings that only the panel may
  loosen (forbidden windows, access levels, approval scope "card payments only", account sessions,
  persistent sessions, your STOP) are anchored in a record the panel signs and keeps in the user's Secret
  Service (KDE Wallet): loosening needs the user's Yes in the panel. Code running as the user that
  deliberately reads or changes that wallet item (KDE Wallet has no per-application access control), or
  deletes it while the wallet is open (which looks like a first start), is in the same class.
- `secret=true` text never touches the clipboard and is left out of results, log and panel, but it is not
  protected after the fact: a separate `observe` or screenshot can show a window title that contains it,
  the focus check before an Enter has a gap of a few milliseconds, and nothing is checked after the submit key.
- An agent that can run arbitrary shell commands as the user can edit files, kill the panel or drive the
  desktop without Deskhand.

See "Security model" in the [README](README.md#security-model) for the full text. Getting around the checks
listed under "What counts" through Deskhand's own tools, without already running as the user, is still a
vulnerability.
