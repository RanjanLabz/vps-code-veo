output "public_ip" {
  description = "Public IPv4 address of the worker VPS."
  value       = oci_core_instance.worker.public_ip
}

output "ssh_command" {
  description = "SSH command for the instance."
  value       = "ssh ${local.ssh_user}@${oci_core_instance.worker.public_ip}"
}

output "health_url" {
  description = "Worker API health endpoint."
  value       = "http://${oci_core_instance.worker.public_ip}:8080/health"
}

output "worker_api_docs_url" {
  description = "FastAPI docs URL."
  value       = "http://${oci_core_instance.worker.public_ip}:8080/docs"
}

output "orchestrator_health_url" {
  description = "Global orchestrator health endpoint."
  value       = "http://${oci_core_instance.worker.public_ip}:8090/health"
}

output "orchestrator_api_docs_url" {
  description = "Global orchestrator FastAPI docs URL."
  value       = "http://${oci_core_instance.worker.public_ip}:8090/docs"
}
