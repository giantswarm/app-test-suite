# Spec: Test-Time Controllers in app-test-suite (ATS)

> Status: draft · Scope: app-test-suite implementation
>
> This document specifies how app-test-suite (ATS) implements the tool-independent
> [Test-Time Controllers Bootstrap Contract](./test-time-controllers-contract.md). It defines
> ATS-specific behaviour: configuration surface, the provider framework, pipeline placement, and
> testing. Everything about the shared `.apptest/config.yaml` schema, version semantics, ordering,
> presence policy, and lifecycle is defined by the contract and only *applied* here — this
> document does not redefine it.
>
> ATS is the consuming harness with id **`ats`**, so it reads its own entry (the one with
> `name: ats`) in each controller's `harness[]` list.

## Problem Statement

ATS tests a Helm chart on a Kubernetes cluster the user provides. Some charts under test create
custom resources (a Flux `Kustomization`, an Argo CD `Application`, an `ExternalSecret`, …) that
are inert unless a matching controller is running on the test cluster to reconcile them. Today
ATS only applies a static bundle of **CRDs** to the cluster (via `--cluster-crds`); it never runs
any controller. So for these charts the CRs are accepted but never processed, the chart never
becomes functional, and the tests cannot validate real behaviour.

At the same time, controllers are expensive to deploy, and only some charts need any given one.
ATS must not deploy controllers a chart does not need, and must not try to guess which ones a
chart needs.

## Solution

ATS implements the [contract](./test-time-controllers-contract.md): it reads the chart test
suite's `.apptest/config.yaml`, and during cluster preparation it ensures each declared
controller is present on the target cluster at a version satisfying the declared `semver`,
before the chart under test is deployed.

ATS provides a small **provider framework**: a `Controller` base class plus a registry, so a
controller is added by writing a short provider class and registering it — without touching the
manager, pipeline, or any other provider. A `ControllerManager` (mirroring the existing
`ClusterManager`) validates the declaration up front and performs the bootstrap once per run.

This first deliverable ships the **framework only** — no concrete providers. Concrete providers
already exist elsewhere and will be synced into ATS later; until then, a suite that declares a
controller fails fast with an "unknown controller" error, which is the contract-specified
behaviour for an unregistered name.

## Relationship to the existing CRD bootstrap

ATS already bootstraps a static bundle of CRDs to the cluster via `--cluster-crds`
(`kubectl apply --server-side`), applied once per run. This feature is **additive**: it does not
change or remove that CRD bundle. The `Controller` base class is, however, designed so a provider
*could* own the CRDs it needs (a controller's Helm chart typically installs its own CRDs), with
an eye toward eventually shrinking or retiring the unconditional CRD bundle in favour of
per-need providers. That convergence is **out of scope** here.

Ordering in the cluster-preparation phase is: apply the `--cluster-crds` bundle → bootstrap
controllers → deploy the chart under test.

## Configuration surface

- **Declaration file discovery.** ATS reads the single `.apptest/config.yaml` relative to the
  current working directory.
- **Override.** `--controllers-config-file` (env `ATS_CONTROLLERS_CONFIG_FILE`) overrides the
  path to the declaration file.
- **Skip.** `--skip-controllers` (env `ATS_SKIP_CONTROLLERS`, store-true) bootstraps no
  controllers even if the file exists (ATS logs that it is skipping). Useful when the target
  cluster is already fully provisioned, or for debugging.
- **Per-harness values.** ATS uses its own `harness[]` entry (the one with `name: ats`) of each
  controller (per the contract). Its `valuesFile` is resolved relative to the declaration file's
  directory and passed to Helm as `--values`, layering over the chart's defaults.
- **No file / no `controllers` / empty list** → ATS bootstraps nothing and proceeds exactly as
  today (full backward compatibility for the many charts with no `.apptest/config.yaml`).

## Provider framework

### `Controller` base class

A data-driven base class in `app_test_suite/controllers/` implements the generic
bootstrap logic once; a concrete controller is mostly declaration. Expected surface (final names
settled in implementation):

- **Declarative attributes:** `name` (tool-neutral identifier, also the registry key),
  `chart_ref` (a Giant Swarm catalog OCI chart reference, e.g.
  `oci://gsoci.azurecr.io/giantswarm/<chart>`), `namespace`, `release_name`, and an
  `install_timeout` default of `10m`.
- **Overridable hooks (default implementations provided):**
  - `pre_install(cluster)` — arbitrary setup before install (e.g. create a `Role`/`RoleBinding`,
    apply prerequisite manifests). Default: no-op.
  - `post_install(cluster)` — extra work / readiness after install (e.g. wait for a webhook or a
    CRD to become established). Default: no-op.
  - controller **detection** — returns the installed chart version on the cluster, or "absent".
    Default implementation reads Helm release metadata (`helm list -o json`, filtered to the
    provider's namespace/release). Overridable for controller-aware detection (e.g. a controller
    the cluster came with, installed by other means).
  - `values(...)` / readiness — overridable for the odd controller.

Adding a controller is therefore roughly: subclass `Controller`, set `name` / `chart_ref` /
`namespace` / `release_name`, optionally override a hook — about six lines plus registration.

### Registration

The base class registers every subclass into a name-keyed registry via `__init_subclass__`.
Built-in providers live under `app_test_suite/controllers/providers/` and are made active by an
explicit one-line import in that package. Adding a provider does not require changes to the
manager, the registry, or the pipeline. (No filesystem auto-discovery and no external
entry-point plugins in this iteration.)

### Install mechanics

Controllers install via the Helm binary already bundled in the ATS container (no `flux`/`argo`
CLIs are added):

- `helm upgrade --install <release_name> <chart_ref> --version "<semver>" --namespace
  <namespace> --create-namespace --wait --timeout <install_timeout>`, plus `--values <file>`
  when ATS's `harness[]` entry names a `valuesFile`, run with `KUBECONFIG` pointed at the
  target cluster.
- Passing `semver` straight to Helm's `--version` gives version selection identical to the
  contract's Flux/Masterminds semantics (Helm uses Masterminds/semver v3), with no
  reimplementation of range matching in Python.
- Charts are pulled from the **Giant Swarm charts catalog**.

### `ControllerManager`

A dedicated `ControllerManager`, constructed in the entry point and wired into the scenarios the
same way `ClusterManager` is:

- **`pre_run`** — parse and validate `.apptest/config.yaml`: resolve the declaration, reject
  unknown controller names against the registry, reject entries missing `name`/`semver`, and
  reject an ATS `harness` entry whose `valuesFile` is missing or not `.yaml`. All of this happens
  before any cluster mutation, so a misconfigured suite fails fast (mirrors how other ATS config
  is validated in `pre_run`).
- **`run` / bootstrap** — for each declared controller, in list order: detect, then either
  install (with `pre_install`/`post_install` and `--wait`) when absent, skip when
  present-and-satisfies, or hard-error when present-and-violates. Sequential, each ready before
  the next.

## Pipeline placement and lifecycle

- Bootstrap is invoked from the scenario cluster-preparation path (`SimpleTestScenario.run`),
  **after** the `--cluster-crds` apply (`_ensure_cluster_prerequisites`) and **before** the
  chart-under-test deploy.
- Bootstrap runs **once per ATS run**, shared across the smoke → functional → upgrade scenarios.
  This is guarded by a new flag on the shared `ClusterInfo` (analogous to the existing
  `dependency_crds_ready`), so later scenarios do not re-run detection or install.
- Controllers are **never uninstalled** by ATS (like the CRD bundle). Both CRDs and controllers
  are left on the cluster so subsequent runs on the same cluster are faster.
- A failed controller bootstrap (install, `--wait` timeout, or a provider hook) fails the run and
  is routed through the existing `_collect_failure_diagnostics` so it dumps pod/event/log
  diagnostics like a failed app deploy does.

## User Stories

1. As an ATS user testing a chart that creates Flux resources, I want ATS to run Flux on my test
   cluster, so that the chart reaches a functional state and my tests are meaningful.
2. As an ATS user, I want to declare the controllers my chart needs in `.apptest/config.yaml`, so
   that ATS bootstraps exactly those and nothing else.
3. As an ATS user, I want charts with no `.apptest/config.yaml` to behave exactly as before, so
   that this feature does not disrupt existing suites.
4. As an ATS user, I want to provide ATS-specific install values via my `harness` entry, so that
   a controller is tuned for the kind of cluster ATS runs against.
5. As an ATS user, I want a controller with no ATS `harness` entry to install with chart
   defaults, so that I only write values when I need to.
6. As an ATS user, I want my `harness`-entry values layered over the chart defaults, so that I
   override only what I need.
7. As an ATS user, I want a clear pre-run error if I reference a missing or misnamed values file,
   so that I fail before my cluster is touched.
8. As an ATS user, I want a clear pre-run error if I declare a controller ATS does not know, so
   that I understand ATS cannot yet satisfy my suite.
9. As an ATS user, I want ATS to reuse a controller already present at a compatible version, so
   that repeated runs on the same cluster skip the install cost.
10. As an ATS user, I want the run to fail if a present controller's version does not satisfy my
    `semver`, so that I am not testing against the wrong version.
11. As an ATS user, I want ATS never to change or remove a controller already on my cluster, so
    that a shared cluster's controllers are undisturbed.
12. As an ATS user, I want controllers declared in a specific order to be installed in that
    order, so that dependencies between them are respected.
13. As an ATS user, I want a `--skip-controllers` switch, so that I can bypass bootstrap on an
    already-provisioned cluster or while debugging.
14. As an ATS user, I want a `--controllers-config-file` override, so that I can point ATS at a
    declaration file in a non-default location.
15. As an ATS user, I want controllers bootstrapped only once per run across
    smoke/functional/upgrade phases, so that I do not pay the cost repeatedly.
16. As an ATS user, I want a failed controller bootstrap to emit cluster diagnostics, so that I
    can debug why it did not come up.
17. As a controller-provider author, I want to add a provider by writing a short class and
    registering it, so that I do not touch the manager, pipeline, or other providers.
18. As a controller-provider author, I want pre-install and post-install hooks, so that I can
    create RBAC or wait for webhooks/CRDs around the install.
19. As a controller-provider author, I want a default helm-release detection I can override, so
    that the common case is free but I can implement controller-aware detection when needed.
20. As an ATS maintainer, I want the framework shipped without concrete providers, so that we can
    land it now and sync the existing providers in later.
21. As an ATS maintainer, I want this feature to leave the existing `--cluster-crds` bundle
    untouched, so that the change is additive and low-risk.

## Implementation Decisions

- New package `app_test_suite/controllers/` containing: the `Controller` base class, a
  name-keyed registry (populated via `__init_subclass__`), a `providers/` subpackage (empty of
  real providers in v1, populated by explicit imports later), and a `ControllerManager`.
- `ControllerManager` mirrors `ClusterManager`: constructed in the entry point, wired into the
  scenarios, validating in `pre_run`, bootstrapping (once) in `run`.
- ATS reads its own `harness[]` entry (`name: ats`); the harness id `ats` is allocated in the
  [RFC](https://github.com/giantswarm/rfc/pull/153).
- Declaration discovery: single `.apptest/config.yaml` relative to CWD; overridable via
  `--controllers-config-file` / `ATS_CONTROLLERS_CONFIG_FILE`; bootstrap skippable via
  `--skip-controllers` / `ATS_SKIP_CONTROLLERS`.
- Install via the bundled Helm binary: `helm upgrade --install ... --version "<semver>" --wait
  --timeout <10m default> [--values <ATS harness valuesFile>]`, charts from the Giant Swarm catalog.
- `semver` is passed to Helm `--version` for Masterminds-parity range resolution.
- Default presence detection reads Helm release metadata and returns the installed chart version;
  overridable per provider. Version comparison basis is the chart version at both detect and
  install time.
- Presence policy per the contract: absent → install; present-and-satisfies → skip;
  present-and-violates → hard error (no upgrade/downgrade/replace).
- Per-provider `install_timeout` (default `10m`); no global timeout knob in v1.
- Bootstrap runs once per run, guarded by a new flag on `ClusterInfo` (parallel to
  `dependency_crds_ready`); pipeline order is CRD bundle → controllers → app deploy.
- Controllers are install-only (no teardown). Install failures route through
  `_collect_failure_diagnostics`.
- The existing `--cluster-crds` bundle is unchanged (additive design).
- No `flux`/`argo` CLIs added to the container; Helm-only.

## Testing Decisions

Tests follow the existing repo pattern (`tests/helpers.py`, `tests/scenarios/`), asserting on
external behaviour — what gets installed, in what order, with what configuration, and which
errors are raised — not on provider internals. Confirmed seams:

- **Primary seam — `run_and_log`** in the controllers module. All `helm`/`kubectl` calls
  (install with `--version <semver> --wait`, helm-release detection via `helm list -o json`,
  `kubectl apply` for `pre_install` manifests) route through the same `run_and_log` the scenario
  tests already mock. Tests assert on the argv and simulate cluster state (absent /
  present-in-range / present-out-of-range) via mocked `run_and_log` return values.
- **Config validation** — drive `ControllerManager.pre_run` against a real `.apptest/config.yaml`
  written into a `tmp_path` (as `tests/test_executor_detection.py` does), asserting parse results
  and validation errors (unknown name, missing `name`/`semver`, missing/mis-extensioned ATS
  `harness` values file).
- **Registry** — register a **fake `Controller` subclass** in the test to exercise the base class
  and manager, since v1 ships no real providers.

Cases to cover: no-file/empty no-op; unknown-name error; missing/bad `harness` values-file errors; order
preservation; detect→install vs detect→skip vs out-of-range→error; values-file layering present
vs absent; once-per-run across scenarios; skip flag; config-file override.

## Out of Scope

- Shipping concrete providers (flux, argo, external-secrets, …) — synced in a later change.
- Sharing provider *code* with apptest-framework (only the declaration file is shared).
- Changing, reducing, or retiring the existing `--cluster-crds` bundle.
- Upgrading/downgrading or uninstalling controllers.
- A global install-timeout option, filesystem provider auto-discovery, or external
  entry-point plugins.
- Per-cluster-type selection among multiple ATS values sets (single ATS `valuesFile` per
  controller in v1).

## Further Notes

- Because the framework ships without providers, the first user-visible effect is that a suite
  declaring any controller fails with an "unknown controller" error until providers are synced —
  this is the intended, contract-specified behaviour.
- The design intentionally keeps the door open (via provider-owned CRDs and `pre_install`) to
  later folding CRD-only needs into providers and shrinking the `--cluster-crds` bundle.
- See the [app-testing contract RFC](https://github.com/giantswarm/rfc/pull/153) (and its local
  [summary](./test-time-controllers-contract.md)) for the authoritative definition of the
  declaration schema, version semantics, ordering, presence policy, and lifecycle this applies.
