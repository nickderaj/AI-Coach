## What

<!-- One paragraph: the change and why it is needed. -->

## How it was verified

<!-- Tests added, what `./scripts/ci.sh` ran, any manual check on the phone. -->

## Checklist

- [ ] Title is a Conventional Commit (`feat(api): ...`); it becomes the squash commit subject
- [ ] New behaviour has tests; rules in `trainer.domain` that decide training load are marked `# coverage-critical`
- [ ] No suppression without a `# why:` / `-- reason` justification
- [ ] Docs updated if behaviour, setup or a decision in `docs/PLAN.md` changed
