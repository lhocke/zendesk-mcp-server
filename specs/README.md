# Specs

One subdirectory per feature. Each subdirectory holds the spec, test strategy, and implementation plan that produced the merged feature.

## Structure

```
specs/
  <feature>/
    spec.md                  # always
    test-strategy.md         # optional, for non-trivial features
    implementation-plan.md   # optional, for non-trivial features
```

`spec.md` is the durable record. `test-strategy.md` and `implementation-plan.md` are added only when scope warrants — small additions (a tool or two with thin surface area) usually don't need either. Names are flat: no `-lean`, `-v2`, or other suffixes. If a spec is rewritten mid-flight, edit it in place.

## Cross-machine workflow

Specs are authored on the personal machine; implementation happens on the work machine where prod Zendesk credentials live and the feature can be validated end-to-end. The handoff is mediated by:

1. A feature branch `feat/<name>` cut from `main` and pushed from the spec-authoring machine.
2. A `HANDOFF.md` at the repo root on that branch (copy from `specs/HANDOFF-TEMPLATE.md`).
3. The work machine pulls the branch, reads `HANDOFF.md`, validates the spec, then implements.
4. On merge to `main`, `HANDOFF.md` is deleted. The `specs/<feature>/` directory stays as the durable record.

## Historical specs at root

`oauth-spec-lean.md`, `oauth-test-strategy-lean.md`, and `oauth-implementation-plan-lean.md` predate this convention and remain at the repo root. New features follow the structure above.
