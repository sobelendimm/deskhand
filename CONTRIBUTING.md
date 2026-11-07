# Contributing

Thanks for helping! Bug reports, test reports from other distros and Plasma versions,
translations and new sensitive-button wording (other languages) are the most useful
contributions right now.

## Reporting a bug

Please include:

- the Health tab of the panel (or the output of `./install.sh --dry-run`) and `deskhand durum`
- distro, Plasma version, Wayland or X11, which desktop (your screen or the background one)
- what you expected vs. what happened, with the relevant lines of the activity log
  (`~/.local/state/deskhand/`)

**Check logs and screenshots before you post them.** They can contain window titles, typed
text and parts of your screen. Remove anything personal.

Security problems (a way for an agent to approve its own request, lift the user's STOP,
reach a forbidden window or send input to the real screen from the background desktop):
please report them privately through GitHub's *Report a vulnerability* button instead of a
public issue.

## Pull requests

- Run the tests before sending: `for t in tests/test_*.py; do python3 "$t" || break; done`.
  They redirect every Deskhand directory to a temporary folder and never send input to your
  screen. `test_sanal` and `test_mcp` start their own invisible desktop.
- The suites in `tests/ekranli/` drive your **real** screen. Run them only when you are not
  using the computer, and say in the PR whether you ran them.
- Raw input tools (`dotool`, `xdotool`) are called only inside `deskhand/arka_uc/`. Every new
  input path must go through the safety checks (forbidden windows, sensitive actions, title
  lock, STOP, human priority); a test checks for stray calls.
- Safety checks must stay on the tool side and must not depend on the agent's cooperation.
  Do not add a way for the agent to answer an approval.
- Code identifiers and comments are mostly Turkish; keep the style of the file you edit.
  Panel texts live in `deskhand/gui/metinler.py`.
- No personal data in code, tests or sample images (names, paths, accounts, real screenshots).
- One topic per pull request, please.

## Licensing of contributions

Deskhand is licensed under GPL-3.0-or-later. By submitting a contribution you confirm that
you wrote it (or have the right to submit it), and you agree that:

1. your contribution is licensed under GPL-3.0-or-later, **and**
2. the project owner may also distribute your contribution under other license terms,
   including commercial ones.

Point 2 keeps the project able to offer things like a paid edition or a commercial license
in the future without having to track down every contributor. The GPL-3.0 version stays
available.
