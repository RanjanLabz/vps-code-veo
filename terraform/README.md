# Oracle Cloud Terraform Deploy

This Terraform creates an Oracle Cloud Infrastructure VPS and bootstraps the worker from GitHub:

`https://github.com/RanjanLabz/vps-code-veo`

It creates:

- VCN, public subnet, internet gateway, route table, and security list.
- Ubuntu 22.04 amd64 compute instance.
- Cloud-init startup script that runs the repo `install.sh`.
- Outputs for SSH, health check, and FastAPI docs.

## Why amd64

The worker installs `google-chrome-stable` from Google's amd64 Linux repository, and the Dockerfile also uses the amd64 Chrome apt repo. Use an x86_64 OCI shape unless the app is changed to support ARM Chromium.

## Usage

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your tenancy OCID, compartment OCID, and SSH public key. By default the OCI provider uses your local `~/.oci/config` `DEFAULT` profile for user, key, fingerprint, and region.

If you do not want to use `~/.oci/config`, set `config_file_profile = null` and provide `user_ocid`, `fingerprint`, `private_key_path`, and `region` directly.

Then run:

```bash
terraform init
terraform plan
terraform apply
```

After apply finishes, use:

```bash
terraform output health_url
terraform output ssh_command
```

The first boot can take several minutes because Docker, Chrome, FlowKit, and the worker image are installed and built on the VPS.

## Ports

- `22`: SSH
- `8080`: worker API
- `5901-5999`: VNC, disabled publicly by default

Before production use, change `ssh_allowed_cidr` and `api_allowed_cidr` from `0.0.0.0/0` to your own IP/CIDR. Set `vnc_allowed_cidr` only when you need direct VNC access.
