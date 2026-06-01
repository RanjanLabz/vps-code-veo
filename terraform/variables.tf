variable "tenancy_ocid" {
  description = "OCI tenancy OCID."
  type        = string
}

variable "config_file_profile" {
  description = "OCI CLI config profile to use. Set to null to provide user_ocid, fingerprint, private_key_path, and region directly."
  type        = string
  default     = "DEFAULT"
}

variable "user_ocid" {
  description = "OCI user OCID for API key authentication. Optional when config_file_profile is set."
  type        = string
  default     = null
}

variable "fingerprint" {
  description = "Fingerprint for the OCI API signing key. Optional when config_file_profile is set."
  type        = string
  default     = null
}

variable "private_key_path" {
  description = "Path to the OCI API private key PEM file. Optional when config_file_profile is set."
  type        = string
  default     = null
}

variable "region" {
  description = "OCI region, for example us-ashburn-1. Optional when config_file_profile is set."
  type        = string
  default     = null
}

variable "compartment_ocid" {
  description = "Compartment OCID where resources will be created."
  type        = string
  default     = null
}

variable "compartment_id" {
  description = "Alias for compartment_ocid."
  type        = string
  default     = null
}

variable "availability_domain" {
  description = "Optional availability domain name. Defaults to the first AD in the tenancy."
  type        = string
  default     = ""
}

variable "ssh_public_key_path" {
  description = "Path to the public SSH key added to the instance user."
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "ssh_public_key" {
  description = "Inline public SSH key added to the instance user. Takes precedence over ssh_public_key_path."
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Prefix used for OCI resource names."
  type        = string
  default     = "flow-worker"
}

variable "repo_url" {
  description = "Git repository cloned by the VPS installer."
  type        = string
  default     = "https://github.com/RanjanLabz/vps-code-veo.git"
}

variable "repo_raw_install_url" {
  description = "Raw GitHub URL for install.sh."
  type        = string
  default     = "https://raw.githubusercontent.com/RanjanLabz/vps-code-veo/main/install.sh"
}

variable "repo_branch" {
  description = "Git branch to deploy."
  type        = string
  default     = "main"
}

variable "app_dir" {
  description = "Directory where the worker repo is installed on the VPS."
  type        = string
  default     = "/opt/flow-worker"
}

variable "instance_shape" {
  description = "OCI compute shape. Keep this amd64 unless the app image supports ARM."
  type        = string
  default     = "VM.Standard.E4.Flex"
}

variable "image_operating_system" {
  description = "OCI image operating system name."
  type        = string
  default     = "Canonical Ubuntu"
}

variable "image_operating_system_version" {
  description = "OCI image operating system version."
  type        = string
  default     = "22.04"
}

variable "instance_ocpus" {
  description = "OCPUs for flexible shapes."
  type        = number
  default     = 2
}

variable "instance_memory_gb" {
  description = "Memory in GB for flexible shapes."
  type        = number
  default     = null
}

variable "instance_memory_gbs" {
  description = "Alias for instance_memory_gb."
  type        = number
  default     = null
}

variable "boot_volume_size_gb" {
  description = "Boot volume size in GB."
  type        = number
  default     = 100
}

variable "vcn_cidr" {
  description = "CIDR block for the VCN."
  type        = string
  default     = "10.42.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block for the public subnet."
  type        = string
  default     = "10.42.1.0/24"
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to SSH to the VPS."
  type        = string
  default     = "0.0.0.0/0"
}

variable "api_allowed_cidr" {
  description = "CIDR allowed to access the worker API on port 8080."
  type        = string
  default     = null
}

variable "app_allowed_cidr" {
  description = "Alias for api_allowed_cidr."
  type        = string
  default     = null
}

variable "vnc_allowed_cidr" {
  description = "CIDR allowed to access VNC ports 5901-5999. Leave empty to keep VNC closed publicly."
  type        = string
  default     = ""
}

variable "vnc_password" {
  description = "Optional VNC password passed to the worker service."
  type        = string
  default     = ""
  sensitive   = true
}

variable "redis_url" {
  description = "External Redis connection URL used by the worker and orchestrator queues."
  type        = string
  sensitive   = true
}

variable "orchestrator_redis_url" {
  description = "External Redis connection URL used by the orchestrator queue. Defaults to redis_url."
  type        = string
  default     = null
  sensitive   = true
}

variable "admin_password" {
  description = "Reserved for images or apps that need an admin password. Not used by this Linux worker."
  type        = string
  default     = null
  sensitive   = true
}

variable "api_key" {
  description = "Reserved for app-level API protection if added later. Not currently used by this worker."
  type        = string
  default     = null
  sensitive   = true
}
