//go:build k8srequired
// +build k8srequired

package metrics

import (
	"os"
	"testing"

	"github.com/giantswarm/apptest"
	"github.com/giantswarm/micrologger"
)

var (
	appTest apptest.Interface
	logger  micrologger.Logger
)

func init() {
	var err error

	{
		c := micrologger.Config{}
		logger, err = micrologger.New(c)
		if err != nil {
			panic(err.Error())
		}
	}

	{
		c := apptest.Config{
			Logger: logger,

			KubeConfigPath: os.Getenv("E2E_KUBECONFIG"),
		}
		appTest, err = apptest.New(c)
		if err != nil {
			panic(err.Error())
		}
	}
}

// TestMain allows us to have common setup and teardown steps that are run
// once for all the tests https://golang.org/pkg/testing/#hdr-Main.
func TestMain(m *testing.M) {
	os.Exit(m.Run())
}
