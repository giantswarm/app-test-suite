#!/bin/bash

echo "Running upgrade hook for stage $1 for app $2 when upgrading from $3 to $4."
echo "I can connect to the cluster using this kube.config: $5."
echo "App is deployed in the namespace $6."
