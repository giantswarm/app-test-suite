# Test-Time Controllers Bootstrap Contract

> Status: draft · Scope: tool-independent contract
>
> **The authoritative, harness-neutral contract now lives in the Giant Swarm
> [app-testing contract RFC](https://github.com/giantswarm/rfc/pull/153)**
> (`app-testing-contract/README.md`, section "Prerequisite controllers"). This page is a
> summary and pointer; it will be reduced to a bare link once that RFC merges. For how
> app-test-suite implements the contract, see
> [ATS Test-Time Controllers](./ats-test-time-controllers.md).

## Summary

A chart's test suite declares, explicitly, the controllers it needs so that any conforming test
harness (app-test-suite, apptest-framework) bootstraps them on the target cluster before the chart
under test is deployed. There is no auto-detection — declaring is the opt-in. Controllers are
named, version-ranged, installed in declared order, reused when already present at a compatible
version, and never uninstalled. The declaration is shared across harnesses; the provider code that
installs a named controller is each harness's own.

The declaration lives in the shared `.apptest/config.yaml`:

```yaml
controllers:
  - name: flux
    semver: ">=2.0.0 <3.0.0"
    harness:                       # optional per-harness install values files
      - name: ats                  # ATS reads its own entry
        valuesFile: flux-small.yaml
      - name: atf                  # apptest-framework reads its own entry
        valuesFile: flux-full.yaml
  - name: external-secrets
    semver: "0.x"
```

- `name` (required) — harness-neutral controller id; unknown to the running harness → hard error.
- `semver` (required) — a version range with Masterminds/semver v3 semantics (as used by Flux
  `OCIRepository` and Helm `--version`), resolved to the highest satisfying version.
- `harness[]` (optional) — per-harness install values files, listed by harness `name` (not keyed
  by it). Each `valuesFile` ends in `.yaml`, resolves next to `config.yaml` under `.apptest/`, and
  layers over the controller's defaults. No entry for the running harness → chart defaults; a named
  file that is missing or not `.yaml` → hard error.

Presence policy: absent → install; present-and-satisfies-`semver` → reuse; present-but-out-of-range
→ hard error (a conforming harness never upgrades, downgrades, or removes a controller it finds).

The normative definition of the schema, version semantics, install ordering, presence policy,
lifecycle, runner flow, and error handling is the
[RFC](https://github.com/giantswarm/rfc/pull/153). The app-test-suite specifics are in the
[ATS implementation spec](./ats-test-time-controllers.md).
