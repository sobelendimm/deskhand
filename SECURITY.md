# Security policy

Deskhand lets an AI agent see and control a desktop, so its safety checks are the core of the project.
Reports about ways around them are very welcome.

## Supported versions

Only the latest release (and `main`) receives security fixes.

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
