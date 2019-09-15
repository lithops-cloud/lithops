import os
import ssl
import json
import time
import base64
import yaml 
import logging
import requests
import http.client
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from urllib.parse import urlparse
from pywren_ibm_cloud.version import __version__
from . import config as kconfig

#Monkey patch for issue: https://github.com/kubernetes-client/python/issues/895
from kubernetes.client.models.v1_container_image import V1ContainerImage
def names(self, names):
    self._names = names
V1ContainerImage.names = V1ContainerImage.names.setter(names)

logger = logging.getLogger(__name__)


class ComputeBackend:
    """
    A wrap-up around Knative Serving APIs.
    """

    def __init__(self, knative_config):
        self.log_level = os.getenv('PYWREN_LOG_LEVEL')
        self.name = 'knative'
        self.knative_config = knative_config
        self.endpoint = self.knative_config.get('endpoint')
        self.serving_host = self.knative_config.get('host')
        self.service_name = self.knative_config.get('service_name')
        # generate kube-config.yml file and set env variable KUBECONFIG=<path-to-kube-confg>        
        config.load_kube_config()
        self.api = client.CustomObjectsApi()
        self.v1 = client.CoreV1Api()
        try:
            ingress = self.v1.read_namespaced_service('istio-ingressgateway', 'istio-system')
            if ingress.status.load_balancer.ingress is not None:
                # get loadbalancer ip
                self.endpoint = ingress.status.load_balancer.ingress[0].ip
            else:
                # for minikube or a baremetal cluster that has no external load balancer
                node = self.v1.list_node()
                node_port = list(filter(lambda port: port.port == 80, ingress.spec.ports))[0].node_port
                self.endpoint = node.items[0].status.addresses[0].address + ":" + str(node_port)
        except ApiException as e:
            print("Exception when calling read_namespaced_service")
        
        print(self.endpoint)
        service_name = self._format_action_name(self.knative_config['service_name'])
        
        #basically for the domain host - but if endpoint still None then read it from the ksvc resource
        if self.endpoint is None or self.serving_host is None:
            try:
                pywren_svc = self.api.get_namespaced_custom_object(
                    group="serving.knative.dev",
                    version="v1alpha1",
                    name=service_name,
                    namespace="default",
                    plural="services"
                )
                if pywren_svc is not None:
                    svc_url = pywren_svc['status']['url']
                    if self.endpoint is None:
                        self.endpoint = svc_url[7:]
                    if self.serving_host is None:
                        self.serving_host = svc_url[7:]
            except Exception as e:
                if json.loads(e.body)['code'] == 404:
                    log_msg = 'ksvc resource: {} Not Found'.format(service_name)
                    logger.debug(log_msg)

        
        self.headers = {
            'content-type': 'application/json',
            'Host': self.serving_host
        }

        log_msg = 'PyWren v{} init for Knative Serving - IP: {} - Service: {}'.format(__version__, self.endpoint, self.serving_host)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)
        logger.debug('Knative init for host: {}'.format(self.endpoint))
        logger.debug('Knative init for service: {}'.format(self.endpoint))

    def _format_action_name(self, runtime_name):
        runtime_name = runtime_name.replace('/', '--').replace(':', '--')
        return runtime_name

    def _unformat_action_name(self, runtime_name):
        image_name = runtime_name.replace('_', '/', 1)
        image_name = image_name.replace('_', ':', -1)
        return image_name

    def _get_default_runtime_image_name(self):
        image_name = kconfig.RUNTIME_DEFAULT
        return image_name
   
    def _create_account_resources(self):
        string_data = {'username': self.knative_config['docker_user'], 
                       'password': self.knative_config['docker_password']}
        secret_res = yaml.load(kconfig.secret_res, Loader=yaml.FullLoader)
        secret_res['stringData'] = string_data
        if self.knative_config['docker_repo'] != kconfig.DOCKER_REPO_DEFAULT:
            secret_res['metadata']['annotations']['tekton.dev/docker-0'] = self.knative_config['docker_repo']
        account_res = yaml.load(kconfig.account_res, Loader=yaml.FullLoader)
        secret_res_name = secret_res['metadata']['name']
        account_res_name = account_res['metadata']['name']
        try:
            self.v1.delete_namespaced_secret(secret_res_name, 'default')
            self.v1.delete_namespaced_service_account(account_res_name,'default')
        except Exception as e:
            if json.loads(e.body)['code'] == 404:
                log_msg = 'account resource Not Found - Not deleted'
                logger.debug(log_msg)
        self.v1.create_namespaced_secret('default', secret_res)
        self.v1.create_namespaced_service_account('default', account_res)

    def _create_build_resources(self):
        
        git_res = yaml.load(kconfig.git_res, Loader=yaml.FullLoader)
        task = yaml.load(kconfig.task_def, Loader=yaml.FullLoader)
        task_name = task['metadata']['name']
        git_res_name = git_res['metadata']['name']
        
        git_url_param = {'name': 'url', 'value': kconfig.GIT_URL_DEFAULT}
        git_rev_param = {'name': 'revision', 'value': kconfig.GIT_REV_DEFAULT}
        params = [git_url_param, git_rev_param]
        
        git_res['spec']['params'] = params
        
        try:
            self.api.delete_namespaced_custom_object(
                group="tekton.dev",
                version="v1alpha1",
                name=task_name,
                namespace="default",
                plural="tasks",
                body=client.V1DeleteOptions()
            )
        except Exception as e:
            if json.loads(e.body)['code'] == 404:
                log_msg = 'ksvc resource: {} Not Found'.format(task_name)
                logger.debug(log_msg)

        try:
            self.api.delete_namespaced_custom_object(
                group="tekton.dev",
                version="v1alpha1",
                name=git_res_name,
                namespace="default",
                plural="pipelineresources",
                body=client.V1DeleteOptions()
            )
        except Exception as e:
            if json.loads(e.body)['code'] == 404:
                log_msg = 'ksvc resource: {} Not Found'.format(git_res_name)
                logger.debug(log_msg)

        git_res_obj = self.api.create_namespaced_custom_object(
            group="tekton.dev",
            version="v1alpha1",
            namespace="default",
            plural="pipelineresources",
            body=git_res
        )

        task_obj = self.api.create_namespaced_custom_object(
            group="tekton.dev",
            version="v1alpha1",
            namespace="default",
            plural="tasks",
            body=task
        )

    def _create_task_run(self, docker_image_name, dockerfile=None):
        task_run = yaml.load(kconfig.task_run, Loader=yaml.FullLoader)
        image_param = {'name': 'imageUrl', 'value': self.knative_config['docker_repo'] + '/' + docker_image_name}
        if dockerfile is None:
            docker_file = kconfig.DOCKERFILE_DEFAULT
        docker_file_param = {'name': 'pathToDockerFile', 'value': docker_file}
        task_run['spec']['inputs']['params'].append(image_param)
        return task_run

    def create_image(self, docker_image_name, taskrun):
        # create the resource
        taskrun_obj = self.api.create_namespaced_custom_object(
            group="tekton.dev",
            version="v1alpha1",
            namespace="default",
            plural="taskruns",
            body=taskrun
        )

        lnk = taskrun_obj['metadata']['selfLink']

        idx = lnk.rfind('/')

        taskname = lnk[idx + 1:]

        pod_name = None

        w = watch.Watch()
        for event in w.stream(self.api.list_namespaced_custom_object, namespace='default',
                              group="tekton.dev", version="v1alpha1", plural="taskruns",
                              field_selector="metadata.name={0}".format(taskname), _request_timeout=10):
            if event['object'].get('status') is not None:
                pod_name = event['object']['status']['podName']
                w.stop()

        w = watch.Watch()
        for event in w.stream(self.v1.list_namespaced_pod, namespace='default',
                              field_selector="metadata.name={0}".format(pod_name), _request_timeout=120):
            if event['object'].status.phase == "Succeeded":
                w.stop()
            if event['object'].status.phase == "Failed":
                w.stop()
                #TODO raise exception

        log_msg = 'Image created'
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)
        
    def create_service(self, docker_image_name):
        # custom resource as Dict
        svc_res = yaml.load(kconfig.service_res, Loader=yaml.FullLoader)
        svc_res['spec']['runLatest']['configuration']['revisionTemplate']['spec']['container']['image'] = \
            self.knative_config['docker_repo'] + '/' + docker_image_name
        service_name = self._format_action_name(docker_image_name) 
        svc_res['metadata']['name'] = service_name
     
        try:
            self.api.delete_namespaced_custom_object(
                group="serving.knative.dev",
                version="v1alpha1",
                name=service_name,
                namespace="default",
                plural="services",
                body=client.V1DeleteOptions()
            )
        except Exception as e:
            if json.loads(e.body)['code'] == 404:
                log_msg = 'ksvc resource: {} Not Found'.format(service_name)
                logger.debug(log_msg)
        # create the resource
        ksvcobj = self.api.create_namespaced_custom_object(
            group="serving.knative.dev",
            version="v1alpha1",
            namespace="default",
            plural="services",
            body=svc_res
        )
        lnk = ksvcobj['metadata']['selfLink']

        idx = lnk.rfind('/')

        ksvcname = lnk[idx + 1:]

        w = watch.Watch()
        for event in w.stream(self.api.list_namespaced_custom_object, namespace='default', 
                              group="serving.knative.dev", version="v1alpha1", plural="services", 
                              field_selector="metadata.name={0}".format(ksvcname), _request_timeout=60):
            #print("Event: %s %s" % (event['type'], event['object'].get('status')))
            #print("\n-----------------------------------")
            conditions = None
            if event['object'].get('status') is not None:
                conditions = event['object']['status']['conditions']
                if event['object']['status'].get('url') is not None:
                    url = event['object']['status']['url']
            if conditions and conditions[0]['status'] == 'True' and conditions[1]['status'] == 'True' and conditions[2]['status'] == 'True':
                w.stop()
        
        log_msg = 'Service resource created - URL: {}'.format(url)
        logger.info(log_msg)
        if not self.log_level:
            print(log_msg)
        return url

    def build_runtime(self, docker_image_name, dockerfile):
        """
        Builds a new runtime from a Docker file and pushes it to the Docker hub
        """
        logger.info('Creating a new docker image from Dockerfile')
        logger.info('Docker image name: {}'.format(docker_image_name))

        self.create_runtime(docker_image_name, dockerfile)


    def create_runtime(self, docker_image_name, memory, code=None, is_binary=True, timeout=300000):
        #TODO check options such as if image exists or not..
        # create image not needed in all cases (if it exists)
        if docker_image_name == 'default':
            docker_image_name = self._get_default_runtime_image_name()

        self._create_account_resources()
        self._create_build_resources()
        taskrun = self._create_task_run(docker_image_name)

        self.create_image(docker_image_name, taskrun)
        service_url = self.create_service(docker_image_name)

        if self.endpoint is None:
            self.endpoint = service_url[7:]
        self.headers['Host'] = service_url[7:]

    def delete_runtime(self, docker_image_name, memory):
        service_name = self._format_action_name(docker_image_name) 
        try:
            self.api.delete_namespaced_custom_object(
                group="serving.knative.dev",
                version="v1alpha1",
                name=service_name,
                namespace="default",
                plural="services",
                body=client.V1DeleteOptions()
            )
            print("Resource deleted")
        except Exception as e:
            if json.loads(e.body)['code'] == 404:
                log_msg = 'ksvc resource: {} Not Found'.format(service_name)
                logger.debug(log_msg)

    def delete_all_runtimes(self):
        #TODO
        pass

    def list_runtimes(self, docker_image_name='all'):
        """
        List all the runtimes deployed in the IBM CF service
        return: list of tuples [docker_image_name, memory]
        """
        #TODO
        runtimes = [[docker_image_name, 0]]
        return runtimes

    def invoke(self, runtime_name, runtime_memory, payload):
        """
        Invoke -- return information about this invocation
        """
        exec_id = payload.get('executor_id', '')
        call_id = payload.get('call_id', '')
        job_id = payload.get('job_id', '')
        route = payload.get("service_route")
        start = time.time()
        try:
            conn = http.client.HTTPConnection(self.endpoint, timeout=300)
            conn.request("POST", route,
                         body=json.dumps(payload),
                         headers=self.headers)
            resp = conn.getresponse()
            resp_status = resp.status
            data = json.loads(resp.read().decode("utf-8"))
            conn.close()
            return exec_id + job_id + call_id, data
        except Exception as e:
            conn.close()
            log_msg = ('ExecutorID {} - Function {} invocation failed: {}'.format(exec_id, call_id, str(e)))
            logger.debug(log_msg)

        roundtrip = time.time() - start
        resp_time = format(round(roundtrip, 3), '.3f')
        if resp_status == 200:
            log_msg = ('ExecutorID {} - Function {} invocation done! ({}s) '
                       .format(exec_id, call_id, resp_time))
            logger.debug(log_msg)
            return exec_id + job_id + call_id
        else:
            #logger.debug(data)
            if resp_status == 401:
                raise Exception('Unauthorized - Invalid API Key')
            elif resp_status == 404:
                raise Exception('Not Found')
            elif resp_status == 503:
                # service overloaded
                return None
            else:
                raise Exception(resp_status)

    def invoke_with_result(self, runtime_name, runtime_memory, payload={}):
        """
        Invoke waiting for a result -- return information about this invocation
        """
        return self.invoke(runtime_name, runtime_memory, payload)

    def get_runtime_key(self, runtime_name, runtime_memory):
        """
        Method that creates and returns the runtime key.
        Runtime keys are used to uniquely identify runtimes within the storage,
        in order to know which runtimes are installed and which not.
        """
        #TODO: knative service memory
        #action_name = self._format_action_name(runtime_name, runtime_memory)
        #os.path.join(self.name, self.region, self.namespace, action_name)
        runtime_key = runtime_name

        return runtime_key
    
    def generate_runtime_meta(self, docker_image_name):

        """
        Extract installed Python modules from docker image
        """
        payload = {}

        payload['service_route'] = "/preinstalls"
        
        self.create_runtime(docker_image_name, memory=0)
        
        logger.debug("Extracting Python modules list from: {}".format(docker_image_name))
        try:
            _, runtime_meta = self.invoke_with_result(docker_image_name, 0, payload)
        except Exception:
            raise("Unable to invoke 'modules' action")

        if not runtime_meta or 'preinstalls' not in runtime_meta:
            raise Exception(runtime_meta)

        return runtime_meta
