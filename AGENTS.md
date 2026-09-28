# Repository agent instructions

## Test conditions

- Use Mahjong Soul friend matches with the `300+0` seconds setting for live functional and regression tests, as requested by the user. Set the operator action deadline explicitly to `300000` ms.
- Record the match settings and results. Keep functional test results separate from ranked win-rate evaluation; success under this time limit does not demonstrate performance under shorter limits.

## Git workflow

- Whenever a task changes repository files, run the relevant checks, commit all task-related changes, and push the commit to the current branch's upstream before reporting completion.
- Do not create empty commits when a task makes no repository changes.
- Do not include unrelated user changes in the commit. If the commit or push cannot be completed, report the exact blocker to the user.
