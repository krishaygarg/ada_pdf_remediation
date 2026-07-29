# Summary

<!-- What changes and why. Link the issue or the spec under docs/planning/ if there is one. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Conformance rule
- [ ] Research (see `docs/planning/`)
- [ ] Documentation
- [ ] Build, CI or tooling

## Accessibility impact

<!--
Name the standard this touches, for example "Matterhorn 09-004", "WCAG 1.4.3"
or "ISO 32000-1 14.7.4.4". Write "none" if the change cannot affect output
documents.
-->

## Verification

- [ ] `pytest` passes locally
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] New behaviour has a test that fails without the change
- [ ] Remediated a document end to end and checked the result:
      `remediate-pdf samples/physics/physics.pdf /tmp/out.pdf && check-compliance /tmp/out.pdf`

<!--
If the change affects produced PDFs, paste the veraPDF verdict before and
after. The local auditor alone is not sufficient evidence.
-->

## Notes for reviewers

<!-- Anything deliberately left out, follow-up work, or areas that need a closer look. -->
