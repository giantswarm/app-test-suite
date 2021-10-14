//go:build smoke
// +build smoke

package main

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/giantswarm/backoff"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

func TestHelloWorld(t *testing.T) {
	var err error

	ctx := context.Background()

	var restConfig *rest.Config
	{
		kubeConfigPath := os.Getenv("ATS_KUBE_CONFIG_PATH")
		restConfig, err = clientcmd.BuildConfigFromFlags("", kubeConfigPath)
		if err != nil {
			t.Fatalf("failed to create REST config from %#q %#v", kubeConfigPath, err)
		}
	}

	var k8sClient kubernetes.Interface
	{
		c := rest.CopyConfig(restConfig)

		k8sClient, err = kubernetes.NewForConfig(c)
		if err != nil {
			t.Fatalf("failed to create k8s client %#v", err)
		}
	}

	service := "hello-world-app-service"

	o := func() error {
		svc, err := k8sClient.CoreV1().Services(metav1.NamespaceDefault).Get(ctx, service, metav1.GetOptions{})
		if err != nil {
			return err
		}

		t.Logf("found service '%s'", svc.Name)
		return nil
	}

	n := func(err error, d time.Duration) {
		t.Logf("waiting for service for %s: %#v", d, err)
	}
	err = backoff.RetryNotify(o, backoff.NewConstant(3*time.Minute, 10*time.Second), n)
	if err != nil {
		t.Fatalf("failed to wait for service: %#v", err)
	}
}
