### Build and Installation (Minikube as example)

Install [Knative on Minikube](https://github.com/knative/docs/blob/master/docs/install/Knative-with-Minikube.md)

Install [PyWren](https://github.com/pywren/pywren-ibm-cloud)

Create knative runtime:

	cp -r ../../pywren_ibm_cloud .
	docker build .

add the image to service.yaml file
pre-built image: **sadek/kpywren**

Create the Knative service:

	kubectl apply --filename service.yaml

Getting Istio URL in Minikube:

	ISTIO=$(minikube ip):$(kubectl get svc knative-ingressgateway -n istio-system -o 'jsonpath={.spec.ports[?(@.port==80)].nodePort}')

Getting the knative service Domain in Minikube:

	kubectl get ksvc <kpywren> --output=custom-columns=NAME:.metadata.name,DOMAIN:.status.domain

Use Istio URL as endpoint and Domain as "host" in the knative config section see [example] (../examples/knative.py)

### Usage
Configure [knative map example](../examples/knative.py) and run:

	python3 ../examples/knative.py

### Cleanup
Delete the service by:

	kubectl delete --filename service.yaml
