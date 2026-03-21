from .base import CredentialSpec

KUBERNETES_CREDENTIALS = {
    "kubernetes": CredentialSpec(
        env_var="KUBECONFIG",
        tools=["kubernetes_list_pods"],
    )
}