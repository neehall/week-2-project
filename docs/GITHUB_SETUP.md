# Connecting this project to GitHub

I can't create repos or push on your behalf from here, so run these once in
VS Code's integrated terminal, opened at this project folder.

## 1. Create the repo

**If you have the GitHub CLI (`gh`) installed and logged in:**

```bash
gh repo create graphrag-org-knowledge --private --source=. --remote=origin
```

**Otherwise:** go to https://github.com/new, name it (e.g.
`graphrag-org-knowledge`), leave it empty (no README/license/gitignore —
this project already has them), and create it. Copy the URL it gives you.

## 2. Init git and make the first commit

```bash
cd "/Users/neehal/Desktop/Neehal/Gen AI Academy/Week 2 Project"
git init
git add .
git commit -m "Scaffold: architecture plan, docs, and module skeletons for GraphRAG vs vector-RAG"
```

## 3. Connect to GitHub and push

Skip this if `gh repo create` already did it for you in step 1.

```bash
git branch -M main
git remote add origin <the URL you copied>
git push -u origin main
```

## Going forward — versioning discipline

- Every meaningful change gets a commit with a message that says what and
  why, not just "update."
- Log what changed in `CHANGELOG.md` (top of the file, under
  `[Unreleased]`) alongside the commit — that's the running record of
  project history independent of git log.
- `docs/PLAN.md` and `docs/SCOPE.md` are living design docs — when a design
  decision changes (chunk size, threshold, query set), update the doc and
  the code in the same commit so they never drift apart.
- Push after each working milestone (ingestion done, vector arm done,
  graph arm done, eval harness done) rather than batching everything into
  one commit at the deadline — the commit history becomes part of your
  "iterations you tried" story for the final project documentation.
