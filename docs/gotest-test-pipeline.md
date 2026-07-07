# Gotest test pipeline

As well as the [pytest] testing pipeline we support `go test`. So components
written in go can also use this in tests. Otherwise the pipelines are kept
as similar as possible so we can reuse functionality. See
[examples/apps/hello-world-app/tests/ats-gotest](../examples/apps/hello-world-app/tests/ats-gotest)
for a complete usage example (run it with `--tests-dir tests/ats-gotest`).

To make your tests automatically invocable from `ats`, you must adhere to the following rules:

- you must put all the test code in the `tests/ats/` directory relative to where you run `ats` from (the
  working directory); this is decoupled from the `--chart-file` archive location, so the chart `.tgz` can
  live anywhere. Override the location with `--tests-dir` (relative to the working directory, or an
  absolute path),
- the directory must contain a `go.mod` file. `ats` uses it to auto-detect the `gotest` executor, so you
  normally don't need to set `--test-executor` at all (pass `--test-executor gotest` to force it),
- in your test the kubeconfig path can be retrieved from the env var `KUBECONFIG`
- tests must be tagged using Go build tags with one of the supported test types
`smoke`, `functional` or `upgrade`.

```golang
//go:build smoke
// +build smoke
```

The `gotest` pipeline invokes following series of steps:

1. TestInfoProvider: gathers some additional info required for running the tests.
2. GotestSmokeTestRunner: invokes `go test` with `smoke` tag to run smoke tests only.
3. GotestFunctionalTestRunner: invokes `go test` with `functional` tag to run functional tests only.
4. GotestUpgradeTestRunner: deploys your app as specified with `--upgrade-tests-app-catalog-url`
    and `--upgrade-tests-app-version` or directly local chart file `--upgrade-tests-app-file`. Then
    tests are executed on the stable app version using the `upgrade` type, a pre-upgrade hook is executed,
    your app is upgraded to the version under the test, post-upgrade hook is executed and then again test are invoked
    using `upgrade` test type.

## Configuring the test cluster

`ats` does not create or destroy clusters. You always run tests against an existing cluster whose `kubeconfig`
you provide with `--cluster-kubeconfig`; all test scenarios (`smoke`, `functional`, `upgrade`) run against
that single cluster. How you obtain the cluster (a local `kind` cluster, a managed cluster, etc.) is entirely
up to you and outside the scope of `ats`.

The cluster is configured with these options:

- `--cluster-kubeconfig` (required) - path to the `kubeconfig` file of the cluster to run the tests on. In
  your Go tests, the kubeconfig path is available via the `KUBECONFIG` environment variable.
- `--cluster-type` (optional) - a free-text label identifying the cluster type. It's exported to your tests
  as the `ATS_CLUSTER_TYPE` environment variable and saved in upgrade test metadata.
- `--cluster-version` (optional) - a free-text label identifying the cluster/Kubernetes version. It's
  exported to your tests as the `ATS_CLUSTER_VERSION` environment variable and saved in upgrade test metadata.

### Test scenario example

**Info:** Please remember you can save any command line option you use constantly in the `.ats/main.yaml`
file and skip it from command line.

I want to run my tests on an existing K8s 1.19.0 cluster created on EKS:

```bash
# command-line version
# the gotest executor is auto-detected from the go.mod in tests/ats;
# add '--test-executor gotest' if you want to force it explicitly
ats -c my-chart \
  --cluster-kubeconfig kube.config \
  --cluster-type EKS \
  --cluster-version "1.19.0"
```

```yaml
# config file version - content of `.ats/main.yaml`
cluster-kubeconfig: kube.config
cluster-type: EKS
cluster-version: "1.19.0"
```
