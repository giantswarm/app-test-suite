module github.com/giantswarm/app-test-suite

go 1.16

require (
	github.com/giantswarm/apiextensions/v3 v3.32.0
	github.com/giantswarm/apptest v0.12.0
	github.com/giantswarm/backoff v0.2.0
	github.com/giantswarm/k8sportforward/v2 v2.0.0
	github.com/giantswarm/microerror v0.3.0
	github.com/giantswarm/micrologger v0.5.0
	github.com/json-iterator/go v1.1.11 // indirect
	github.com/stretchr/testify v1.7.0 // indirect
	golang.org/x/sys v0.0.0-20210603081109-ebe580a85c40 // indirect
	google.golang.org/protobuf v1.26.0-rc.1 // indirect
	gopkg.in/yaml.v2 v2.4.0 // indirect
	k8s.io/apimachinery v0.20.10
)

// Use fork of CAPI with Kubernetes 1.18 support.
replace sigs.k8s.io/cluster-api => github.com/giantswarm/cluster-api v0.3.10-gs
