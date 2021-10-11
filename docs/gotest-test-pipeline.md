# Gotest test pipeline

As well as the [pytest] testing pipeline we support `go test`. So components
written in go can also use this in tests. Otherwise the pipelines are kept
as similar as possible so we can reuse functionality.

To make your tests automatically invocable from `ats`, you must adhere to the following rules:

- you must put all the test code in `[CHART_TOP_DIR]/tests/ats/` directory,
- you must set `--test-executor` to `gotest`,
- in your test the kubeconfig path can be retrieved from the env var `ATS_KUBE_CONFIG_PATH`
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

## Configuring test scenarios

Each test type ("smoke", "functional") can have its own type and configuration of a Kubernetes cluster it runs on. That
way you can create test scenarios like: "please run my 'smoke' tests on a `kind` cluster; if they succeed, run '
functional' tests on an external cluster I give you `kube.config` for".

The type of cluster used for each type of tests is selected using the `--[TEST_TYPE]-tests-cluster-type`
config option. Additionally, if the cluster provider of given type supports some config files that allow you to tune how
the cluster is created, you can pass a path to that config file using the
`--[TEST_TYPE]-tests-cluster-config-file`.

Currently, the supported cluster types are:

1. `external` - it means the cluster is created out of the scope of control of `ats`. The user must pass a path to
   the `kube.config` file and cluster type and Kubernetes version as command line arguments.
1. `kind` - `ats` automatically create a [`kind`](https://kind.sigs.k8s.io/docs/user/quick-start/)
   cluster for that type of tests. You can additionally pass
   [kind config file](https://kind.sigs.k8s.io/docs/user/quick-start/#configuring-your-kind-cluster)
   to configure the cluster that will be created by `ats`.

### Test scenario example

**Info:** Please remember you can save any command line option you use constantly in the `.ats/main.yaml`
file and skip it from command line.

1. I want to run 'smoke' tests on a kind cluster and 'functional' tests on an external K8s 1.19.0 cluster created on
   EKS:

   ```bash
   # command-line version
   dats.sh -c my-chart --smoke-tests-cluster-type kind \
     --functional-tests-cluster-type external \
     --external-cluster-kubeconfig-path kube.config \
     --external-cluster-type EKS \
     --external-cluster-version "1.19.0" \
     --test-executor gotest
   ```

2. I want to run both `smoke` and `functional` tests on the same `kind` cluster. I want the `kind` cluster to be created
   according to my config file:

   ```yaml
   # config file version - content of `.ats/main.yaml`
   functional-tests-cluster-type: kind
   smoke-tests-cluster-type: kind
   smoke-tests-cluster-config-file: my-chart/kind_config.yaml
   functional-tests-cluster-config-file: my-chart/kind_config.yaml
   ```
