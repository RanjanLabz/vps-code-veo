provider "oci" {
  config_file_profile = var.config_file_profile
  tenancy_ocid        = var.tenancy_ocid
  user_ocid           = var.user_ocid
  fingerprint         = var.fingerprint
  private_key_path    = var.private_key_path
  region              = var.region
}

data "oci_identity_availability_domains" "this" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu" {
  compartment_id           = local.compartment_id
  operating_system         = var.image_operating_system
  operating_system_version = var.image_operating_system_version
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

locals {
  availability_domain = var.availability_domain != "" ? var.availability_domain : data.oci_identity_availability_domains.this.availability_domains[0].name
  compartment_id      = coalesce(var.compartment_ocid, var.compartment_id)
  image_id            = data.oci_core_images.ubuntu.images[0].id
  instance_memory_gb  = coalesce(var.instance_memory_gb, var.instance_memory_gbs, 16)
  api_allowed_cidr    = coalesce(var.api_allowed_cidr, var.app_allowed_cidr, "0.0.0.0/0")
  ssh_authorized_keys = var.ssh_public_key != null ? var.ssh_public_key : file(var.ssh_public_key_path)
  ssh_user            = var.image_operating_system == "Oracle Linux" ? "opc" : "ubuntu"
  cloud_init = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    repo_url               = var.repo_url
    repo_raw_install_url   = var.repo_raw_install_url
    repo_branch            = var.repo_branch
    app_dir                = var.app_dir
    vnc_password           = var.vnc_password
    redis_url              = var.redis_url
    orchestrator_redis_url = coalesce(var.orchestrator_redis_url, var.redis_url)
  })
}

resource "oci_core_vcn" "this" {
  compartment_id = local.compartment_id
  cidr_block     = var.vcn_cidr
  display_name   = "${var.name_prefix}-vcn"
  dns_label      = "flowworker"
}

resource "oci_core_internet_gateway" "this" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${var.name_prefix}-igw"
  enabled        = true
}

resource "oci_core_route_table" "public" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${var.name_prefix}-public-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.this.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.this.id
  display_name   = "${var.name_prefix}-public-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    protocol = "6"
    source   = var.ssh_allowed_cidr

    tcp_options {
      min = 22
      max = 22
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = local.api_allowed_cidr

    tcp_options {
      min = 80
      max = 80
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = local.api_allowed_cidr

    tcp_options {
      min = 8080
      max = 8080
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = local.api_allowed_cidr

    tcp_options {
      min = 8090
      max = 8090
    }
  }

  ingress_security_rules {
    protocol = "6"
    source   = local.api_allowed_cidr

    tcp_options {
      min = 6080
      max = 6579
    }
  }

  dynamic "ingress_security_rules" {
    for_each = var.vnc_allowed_cidr == "" ? [] : [var.vnc_allowed_cidr]

    content {
      protocol = "6"
      source   = ingress_security_rules.value

      tcp_options {
        min = 5901
        max = 5999
      }
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = local.compartment_id
  vcn_id                     = oci_core_vcn.this.id
  cidr_block                 = var.subnet_cidr
  display_name               = "${var.name_prefix}-public-subnet"
  dns_label                  = "public"
  prohibit_public_ip_on_vnic = false
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.public.id]
}

resource "oci_core_instance" "worker" {
  availability_domain = local.availability_domain
  compartment_id      = local.compartment_id
  display_name        = "${var.name_prefix}-vps"
  shape               = var.instance_shape

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = local.instance_memory_gb
  }

  create_vnic_details {
    assign_public_ip = true
    display_name     = "${var.name_prefix}-vnic"
    hostname_label   = "flow-worker"
    subnet_id        = oci_core_subnet.public.id
  }

  source_details {
    source_type             = "image"
    source_id               = local.image_id
    boot_volume_size_in_gbs = var.boot_volume_size_gb
  }

  metadata = {
    ssh_authorized_keys = local.ssh_authorized_keys
    user_data           = base64encode(local.cloud_init)
  }

  lifecycle {
    ignore_changes = [
      metadata["user_data"],
    ]
  }
}
