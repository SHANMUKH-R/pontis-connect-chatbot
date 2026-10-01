# Contributing — Team Pontis (Connect ChatBot)

How we work in this repo. Keep `main` always working. All changes go through PRs.

## Branching
- **`main`** is protected and always deployable. **No direct commits to `main`.**
- Branch off `main` for every change:
  - `feature/<short-desc>` — new functionality (e.g. `feature/question-logging`)
  - `fix/<short-desc>` — bug fixes
  - `docs/<short-desc>` — docs / scope / contract
  - `chore/<short-desc>` — tooling, deps, cleanup
- Keep branches small and short-lived. Rebase or merge `main` in before opening a PR.

## Pull request rules
1. **Every change is a PR into `main`.** No pushing to `main` directly.
2. **≥1 approving review required** before merge. For changes to core bot logic
   (`src/`), the **tech lead** reviews.
3. **You don't merge your own PR** until it has an approval. The **approving reviewer
   or the tech lead merges** — this keeps a second set of eyes on everything.
4. **Squash-merge** into `main` (one clean commit per PR). Delete the branch after.
5. Link every PR to its **kanban card**.
6. Resolve all review comments before merging. CI (once added) must be green.

## Roles for review/merge _(confirm with team)_
| Role | Who | Responsibility |
|------|-----|----------------|
| Tech lead (merge authority) | _[__]_ | reviews `src/`, final merge, protects `main` |
| Reviewer | any teammate | reviews PRs, approves |
| Docs owner | _[__]_ | contract / prep / scope docs |

> If the tech lead is the PR author, a different teammate reviews and merges.

## PR title style (Conventional Commits)
`type: short imperative summary` — e.g. `feat: log member questions to store`

Types: `feat` · `fix` · `docs` · `refactor` · `chore` · `test`

## PR description
Use the template in `.github/pull_request_template.md`:
- **What** changed and **why**
- **How tested**
- **Kanban card** link
- Screenshots if UI

## Commit hygiene
- Small, focused commits; present-tense messages (`add question logger`).
- Never commit client data or secrets — see `.gitignore` (`data/` is ignored).
  Client identity stays **out of the repo** (confidential).
