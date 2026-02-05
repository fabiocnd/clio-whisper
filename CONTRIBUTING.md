# Contributing to Clio Whisper

## Branch Structure

This project follows GitFlow-inspired branching strategy:

### Main Branches
- **master**: Production-ready code, protected branch
- **develop**: Integration branch for next release

### Feature Branches
```
feature/<feature-name>
```
For new features and enhancements.
Examples: `feature/audio-config`, `feature/ui-redesign`

### Bugfix Branches
```
fix/<issue-description>
```
For bug fixes and patches.
Examples: `fix/text-deduplication`, `fix/memory-leak`

### Hotfix Branches
```
hotfix/<urgent-fix>
```
For urgent production fixes.
Created from `master`, merged back to both `master` and `develop`.

### Release Branches
```
release/v<major>.<minor>.<patch>
```
For release preparation.
Created from `develop`.

## Workflow

### Starting a New Feature
```bash
git checkout develop
git checkout -b feature/my-new-feature
# Make changes and commit
git push -u origin feature/my-new-feature
```

### Creating a Release
```bash
git checkout develop
git checkout -b release/v1.1.0
# Final testing and version bumps
git checkout master
git merge --no-ff release/v1.1.0 -m "Release v1.1.0"
git tag v1.1.0
git push origin master --tags
```

### Creating a Hotfix
```bash
git checkout master
git checkout -b hotfix/critical-bug
# Fix the bug
git checkout master
git merge --no-ff hotfix/critical-bug -m "Hotfix: critical bug description"
git push origin master --tags
```

## Code Review
All changes must be reviewed via Pull Requests before merging to `master`.

## Commit Messages
Follow [Conventional Commits](https://www.conventionalcommits.org/):
- `feat: Add new transcription feature`
- `fix: Resolve audio capture issue`
- `docs: Update API documentation`
- `refactor: Improve transcript aggregation logic`

## Testing
All features must include appropriate tests before merging.
