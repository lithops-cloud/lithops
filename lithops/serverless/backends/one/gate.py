import os
import time

import requests


class OneGateError(Exception):
    """General exception for OneGate-related errors."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class OneGateClient:
    def __init__(self, max_retries=3, retry_backoff=1.0):
        self.endpoint = os.getenv(
            "ONEGATE_ENDPOINT", self.get_config("ONEGATE_ENDPOINT")
        )
        self.token = self.read_file("/mnt/context/token.txt")
        self.vm_id = self.get_config("VMID")
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    @staticmethod
    def read_file(filepath):
        with open(filepath, "r") as file:
            return file.read().strip()

    @staticmethod
    def get_config(param, filepath="/mnt/context/context.sh"):
        with open(filepath, "r") as file:
            for line in file:
                if line.startswith(f"{param}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        return None

    def _retry_request(self, request_func, *args, **kwargs):
        """
        Retry a request with exponential backoff.
        
        Args:
            request_func: The function to call (e.g., requests.get, requests.put)
            *args, **kwargs: Arguments to pass to the request function
            
        Returns:
            Response object
            
        Raises:
            OneGateError: If all retries are exhausted
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                response = request_func(*args, **kwargs)
                response.raise_for_status()
                return response
            except (requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s, etc.
                    wait_time = self.retry_backoff * (2 ** attempt)
                    time.sleep(wait_time)
                    continue
                # Last attempt failed, raise the exception
                raise
            except requests.exceptions.RequestException as e:
                # For other errors (e.g., 4xx, 5xx), don't retry
                raise

        # Should not reach here, but just in case
        raise last_exception

    def get(self, path):
        """
        Make a GET request to OneGate API and return the JSON response.
        """
        url = f"{self.endpoint}/{path}"
        headers = {"X-ONEGATE-TOKEN": self.token, "X-ONEGATE-VMID": self.vm_id}

        try:
            response = self._retry_request(requests.get, url, headers=headers)
            return response.json()
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else None
            raise OneGateError(f"GET request to {url} failed: {e}", status_code)
        except ValueError as e:
            raise OneGateError(f"Failed to parse JSON response: {e}")

    def scale(self, cardinality, role="worker"):
        """
        Make a PUT request to OneGate API.
        """
        url = f"{self.endpoint}/service/role/{role}"
        headers = {
            "X-ONEGATE-TOKEN": self.token,
            "X-ONEGATE-VMID": self.vm_id,
            "Content-Type": "application/json",
        }
        data = {"cardinality": cardinality}
        try:
            response = self._retry_request(requests.put, url, headers=headers, json=data)
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if hasattr(e, 'response') and e.response else None
            raise OneGateError(f"PUT request to {url} failed: {e}", status_code)
