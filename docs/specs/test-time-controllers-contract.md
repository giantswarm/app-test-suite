# Spec: Test-Time Controllers Bootstrap Contract

> Status: draft · Scope: tool-independent contract
>
> This document defines a **tool-independent** contract for declaring and bootstrapping
> the Kubernetes controllers a chart's test suite needs at test time. It is written to be
> implemented by more than one test tool. It deliberately contains **no** concepts, option
> names, file layouts, or behaviours specific to any single tool.
>
> For the concrete application of this contract to app-test-suite (ATS), see the companion
> spec: [ATS Test-Time Controllers](./ats-test-time-controllers.md).

## Problem Statement

A Helm chart under test frequently creates custom resources (CRs) — for example a Flux
`Kustomization`, an Argo CD `Application`, or an `ExternalSecret` — that only become
meaningful when a matching **controller** is running on the test cluster to reconcile them.
Without that controller, the API server may accept the CR (if its CRD is present) but nothing
acts on it, so the chart never reaches a functional state and the tests cannot validate real
behaviour.

Which controllers a chart needs is specific to that chart. Only a subset of charts need any
given controller, and deploying controllers is expensive (time and cluster resources).
Deploying every possible controller for every chart is wasteful; guessing which ones a chart
needs from its contents is fragile and flaky.

Different test tools consume the same chart test suites. A chart declares its controller needs
once; every tool that runs that suite must be able to read the same declaration and bootstrap
the same set of controllers, even though each tool targets a different kind of cluster and may
need different install-time configuration.

## Solution

A chart's test suite declares, **explicitly**, the exact set of controllers it needs, in a
single well-known file that is part of the test suite. Any conforming test tool reads that file
and, during its cluster-preparation phase, ensures each declared controller is present on the
target cluster at an acceptable version before the chart is deployed and tested.

- Declaration is **opt-in and explicit** — no auto-detection. A chart that declares nothing
  gets nothing bootstrapped.
- The declaration is **tool-neutral**: it names controllers and version ranges, and it carries
  per-tool install configuration under tool-namespaced keys, so multiple tools can share one
  file.
- Each conforming tool owns its own **controller provider** implementations (how a named
  controller is installed, detected, and made ready). The file is the shared contract; the
  provider code is not.
- A tool installs only the declared controllers, in declared order, and reuses controllers that
  are already present.

## Terminology

- **Controller** — a Kubernetes workload (and its CRDs/RBAC) that reconciles a class of custom
  resources (e.g. Flux, Argo CD, External Secrets).
- **Controller name** — the stable, tool-neutral identifier of a controller (e.g. `flux`,
  `argo`, `external-secrets`) used in the declaration and to look up a provider.
- **Provider** — a tool-side implementation that knows how to detect, install, and ready a
  particular controller. Providers are owned by each tool, not by this contract.
- **Consuming tool** — a test tool that implements this contract (reads the declaration and
  bootstraps controllers). Each consuming tool has a short **tool id** (see
  [Tool ids](#tool-ids)).
- **Target cluster** — the pre-existing cluster the consuming tool prepares and runs tests on.
- **Test suite** — the chart-specific test assets, of which the declaration file is a part.

## The declaration file

### Location

The declaration lives at `.apptest/config.yaml` within the test suite. The `.apptest/`
directory is the shared, tool-neutral home for cross-tool testing declarations; this contract
defines the `controllers` section of `config.yaml`. Other sections may be added by future
contracts and must be ignored by a tool that does not understand them.

How a tool discovers, resolves, or overrides the path to this file is tool-specific and out of
scope for this contract. What is fixed is the filename and the schema below.

### Schema

```yaml
controllers:
  - name: <controller-name>        # required, string
    semver: <version-range>        # required, string (see "Version selection")
    config:                        # optional, mapping of tool id -> values file name
      <tool-id>: <filename.yaml>   # optional per tool id
      ...
  - ...
```

- `controllers` — an ordered list. **Order is significant** (see
  [Install ordering](#install-ordering)).
- `name` — **required**. The tool-neutral controller name. If a consuming tool has no provider
  registered for this name, that is a hard error (see [Error handling](#error-handling)).
- `semver` — **required**. A version range (see [Version selection](#version-selection)).
- `config` — **optional**. A mapping keyed by **tool id**. Each value is the file name of a
  tool-specific install-configuration (values) file for this controller. See
  [Per-tool configuration](#per-tool-configuration).

A missing, empty, or absent `controllers` section means **no controllers are declared** and a
conforming tool bootstraps nothing.

### Tool ids

Each consuming tool has a short, unique **tool id** used as its key under `config`. This keeps
the shared file tool-neutral: a tool reads only its own key and ignores the others.

Tool ids are allocated by this contract to avoid collisions. Currently allocated:

- `ats` — app-test-suite (see [ATS spec](./ats-test-time-controllers.md))
- `atf` — apptest-framework

New consuming tools must allocate a new tool id here before using it.

### Per-tool configuration

The set of controllers a chart needs is tool-neutral, but the *configuration* used to install a
controller often differs per tool, because each tool targets a different kind of cluster (for
example a small local cluster vs. a full production-like cluster). Those install-time values
therefore belong to the tool, not to the shared list of names.

- Per-controller configuration is **optional**. If an entry has no `config` mapping, or no key
  for the current tool's id, the controller is installed with its **default** configuration.
- When present, `config.<tool-id>` names a **values file** authored by the test-suite author
  and shipped inside the test suite (alongside the declaration file).
- Each value **must** be a full file name ending in `.yaml`.
- The named file is resolved relative to the declaration file's directory.
- A conforming tool applies the file as install-time configuration **layered over the
  controller's defaults** (i.e. an overlay, not a full replacement).
- If `config.<tool-id>` names a file that does not exist, or a value that does not end in
  `.yaml`, that is a hard error (see [Error handling](#error-handling)).

Example:

```yaml
controllers:
  - name: flux
    semver: ">=2.0.0 <3.0.0"
    config:
      ats: flux-small.yaml      # used by app-test-suite
      atf: flux-full.yaml       # used by apptest-framework
  - name: external-secrets
    semver: "0.x"
    # no config -> each tool installs with the controller's default configuration
```

## Behaviour

### Version selection

`semver` is a **version range**, interpreted with the same semantics as Flux
`OCIRepository` semver matching and Helm's `--version` constraint — i.e. the
Masterminds/semver v3 range grammar. Examples: `1.2.x`, `>=1.0.0 <2.0.0`, `~1.2.3`, `^1.2.3`,
`*`. Pre-releases are excluded unless the range explicitly names a pre-release. See
<https://fluxcd.io/flux/components/source/ocirepositories/#semver-example>.

A conforming tool resolves the range to the **highest available version that satisfies it** and
installs that version. How available versions are enumerated (registry, chart repository, etc.)
is provider-defined.

### Install ordering

Controllers are bootstrapped **sequentially, in the order they appear** in the `controllers`
list. A controller must be fully installed **and ready** before the next controller in the list
is started. Tools must not reorder or parallelise the list. Authors may therefore rely on order
to express dependencies between controllers.

### Presence detection and version policy

Before installing a controller, a conforming tool must determine whether an acceptable instance
is **already present** on the target cluster, and reuse it rather than reinstalling:

- The provider reports the **installed version** of the controller on the target cluster, or
  reports that it is **absent**. The version reported at detection time and the version selected
  at install time are compared on the **same basis** (the chart version), so they are directly
  comparable.
- **Absent** → the tool installs the controller (resolving `semver` as above), then waits for it
  to be ready.
- **Present and the installed version satisfies `semver`** → the tool reuses it and skips
  installation.
- **Present but the installed version does not satisfy `semver`** → **hard error**. A conforming
  tool must **not** upgrade, downgrade, or replace a controller it finds already present; the
  mismatch fails the run so the operator can resolve it. (The rationale: the target cluster is
  not owned by the tool, and silently changing an existing controller could break other
  workloads.)

### Provider setup hooks

A controller install is not always a single package install. A provider may need to perform
setup **before** installing (for example creating a `Role`/`RoleBinding` or applying prerequisite
manifests) and additional work or readiness checks **after** installing (for example waiting for
a webhook or a freshly-installed CRD to become established). The contract therefore requires that
a provider be able to run arbitrary **pre-install** and **post-install** steps around the install,
in addition to the declarative common case.

### Readiness

"Ready" means the controller's workloads report healthy **and** any provider-defined
post-install readiness checks have passed. A controller is only considered bootstrapped once it
is ready. Because installs are sequential, the readiness of controller *N* is guaranteed before
controller *N+1* begins.

### Idempotency and lifecycle

- Bootstrapping is performed **once per target cluster per run**, shared across all test phases
  in that run.
- Bootstrapped controllers are **installed only — never uninstalled** by the tool. They are
  treated as durable cluster infrastructure. Leaving them in place makes subsequent runs on the
  same cluster faster and avoids removing something another chart or run may depend on.

### Error handling

The following are **hard errors** that must be surfaced clearly:

- A declared `name` has no registered provider in the consuming tool.
- A declaration entry is missing a required field (`name` or `semver`).
- `config.<tool-id>` names a non-existent file or a value not ending in `.yaml`.
- `semver` resolves to no available version.
- A controller is present but its installed version does not satisfy `semver`.
- An install, readiness wait, or provider setup hook fails.

Configuration-level errors (the first three) should be detected as early as possible — before
any cluster changes are made — so a misconfigured suite fails fast. Where exactly a tool
performs this validation is tool-specific.

## User Stories

1. As a chart/test-suite author, I want to declare the controllers my chart needs in one file,
   so that any test tool can bootstrap them consistently.
2. As a chart author, I want to declare a controller by name and version range, so that I get a
   compatible version without pinning an exact release.
3. As a chart author, I want controllers I did not declare to never be installed, so that my
   test runs stay fast and cheap.
4. As a chart author, I want no controller auto-detection, so that my test setup is explicit and
   not flaky.
5. As a chart author, I want to declare controllers in a specific order, so that a controller
   that depends on another is bootstrapped after it.
6. As a chart author, I want to optionally provide per-tool install configuration for a
   controller, so that the same controller can be tuned for a small cluster in one tool and a
   full cluster in another.
7. As a chart author, I want a controller with no per-tool configuration to install with sensible
   defaults, so that I only write configuration when I actually need to override something.
8. As a chart author, I want my per-tool values file to be layered over the controller's
   defaults, so that I only specify the values I want to change.
9. As a chart author, I want a clear, early error if I reference a values file that does not
   exist or is misnamed, so that I catch mistakes before a cluster is touched.
10. As a chart author, I want a clear error if I declare a controller name that the tool does not
    know, so that I learn immediately that the tool cannot satisfy my suite.
11. As a chart author, I want an already-present, compatible controller to be reused, so that
    repeated runs on the same cluster do not pay the install cost again.
12. As an operator, I want the run to fail if a present controller's version does not satisfy the
    declared range, so that I am not silently testing against the wrong controller version.
13. As an operator, I want the tool never to modify or remove a controller it finds already
    installed, so that my shared cluster's controllers are not disrupted.
14. As an operator, I want bootstrapped controllers to remain after the run, so that later runs
    on the same cluster are faster.
15. As a test-tool implementer, I want a precise, tool-neutral contract, so that my tool
    interoperates with the same declaration files other tools use.
16. As a test-tool implementer, I want my own tool-namespaced configuration key, so that my
    install configuration does not collide with other tools' configuration in the shared file.
17. As a test-tool implementer, I want the freedom to implement providers however I like, so that
    I can install controllers in the way that suits my target clusters.
18. As a test-tool implementer, I want the contract to define pre-install and post-install
    extension points, so that controllers needing RBAC or webhook readiness can be supported.
19. As a chart author consuming multiple tools, I want a single declaration file with per-tool
    sections, so that I maintain my controller needs in one place.

## Implementation Decisions

- The shared declaration file is `.apptest/config.yaml`; this contract governs its
  `controllers` section only. Unknown sections are ignored by a conforming tool.
- The `controllers` list is ordered and order is semantically significant.
- Each entry requires `name` (tool-neutral controller identifier) and `semver` (version range).
- `semver` uses Masterminds/semver v3 range grammar (Flux `OCIRepository` / Helm `--version`
  semantics); a tool resolves it to the highest satisfying version.
- Per-controller, per-tool install configuration lives under `config.<tool-id>`; values are
  file names ending in `.yaml`, resolved relative to the declaration file, layered over
  controller defaults, and shipped inside the test suite.
- Tool ids are centrally allocated in this document (`ats`, `atf` currently).
- Providers are tool-owned. This contract does not prescribe a provider code shape, only the
  behaviours a provider must support: report installed version (or absent), install a selected
  version, run pre-install and post-install steps, and report readiness.
- Presence policy: absent → install; present-and-satisfies → reuse; present-and-violates →
  hard error. No upgrade/downgrade/replace of a pre-existing controller.
- Bootstrapping is once-per-cluster-per-run and install-only (no teardown).
- Configuration-level errors are detected before any cluster mutation.

## Testing Decisions

This contract is validated by each consuming tool's own test suite; see the
[ATS spec](./ats-test-time-controllers.md#testing-decisions) for ATS's approach. A conforming
tool should have tests that cover, as external behaviour:

- Parsing and validating the declaration (valid, empty/absent, missing required fields,
  bad/missing per-tool values file).
- Unknown controller name → error.
- Order preservation across the `controllers` list.
- Presence outcomes: absent → install; present-and-satisfies → reuse/skip; present-and-violates
  → error.
- Values file layering when `config.<tool-id>` is present vs. absent.
- Once-per-run bootstrapping across multiple test phases.

Tests should assert on observable behaviour (what gets installed, in what order, with what
configuration, and which errors are raised), not on provider internals.

## Out of Scope

- How a tool discovers, resolves, or overrides the path to the declaration file.
- How a provider is implemented, packaged, or registered within a tool.
- How a provider enumerates available versions or performs the install.
- Sharing provider *code* between tools (only the declaration file is shared).
- Per-chart pinning of exact controller versions beyond what `semver` expresses.
- Bootstrapping anything other than controllers (e.g. standalone CRDs with no controller) —
  though a future section of `.apptest/config.yaml` could add that.
- Uninstalling or upgrading controllers.

## Further Notes

- The `config.<tool-id>` mechanism is intentionally extensible: adding a new consuming tool
  means allocating a tool id and (optionally) authoring a new per-tool values file, without
  changing the shared list of controller names.
- Because pre-existing controllers are never modified, a cluster deliberately pre-provisioned
  with a compatible controller will be reused as-is, which is the fast path for repeated runs.
