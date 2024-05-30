from ..k8s.k8s import KubernetesBackend

class OpenNebula(KubernetesBackend):
    """
    A wrap-up around OpenNebula backend.
    """
    def __init__(self, one_config, internal_storage):
        # TODO: check One_KE is deployed
        #       (if not) initialize OpenNebula One_KE & wait for it to be ready

        # Overwrite config values
        self.name = 'one'

        super().__init__(one_config, internal_storage)
    

    def invoke(self, docker_image_name, runtime_memory, job_payload):
        super().invoke(docker_image_name, runtime_memory, job_payload)
    
    
    def clear(self, job_keys=None):
        # First, we clean Kubernetes jobs
        super().clear(all)

        # TODO: if all are deteleted -> suspend OneKE VMs (scale down) and
        #       delete them after X minutes
        pass


    def _check_oneke(self):
        # CASE1: client has created their own OneKE cluster
        # CASE2: OneKE cluster was created by lithops (with or without JSON file) 
        pass
    

    def _instantiate_oneke(self):
        # TODO: check OneKE JSON is passed (if not use default)
        
        # TODO: check networks (public/private vnets)
        
        # TODO: instantiate OneKE
        pass


    def _wait_for_oneke(self):
        # TODO: wait for all the VMs
        
        # TODO: look onegate connectivity
        pass