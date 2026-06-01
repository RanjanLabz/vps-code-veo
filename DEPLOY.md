# Deploying To VPS

This repo is designed so every new Ubuntu VPS can be created from GitHub with one command.

## Option A: Oracle VPS With Terraform

Terraform files are in `terraform/`. They create an Oracle Cloud Infrastructure VPS, then cloud-init runs this repo's installer from GitHub.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` with your OCI tenancy OCID, compartment OCID, and SSH public key. By default Terraform uses your local `~/.oci/config` `DEFAULT` profile for user, key, fingerprint, and region.

Then run:

```bash
terraform init
terraform plan
terraform apply
```

After apply:

```bash
terraform output health_url
terraform output ssh_command
```

The default Terraform shape is `VM.Standard.E4.Flex` because this worker installs amd64 Google Chrome. Do not use an ARM/Ampere shape unless the worker image is changed to support ARM Chromium.

## Option B: Manual VPS Install

### 1. Push This Repo To GitHub

From your local machine:

```bash
git init
git add .
git commit -m "Initial Flow worker appliance"
git branch -M main
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

If the GitHub repo already exists locally, only run:

```bash
git add .
git commit -m "Update Flow worker appliance"
git push
```

### 2. Install On A Fresh VPS

SSH into the VPS and run:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | REPO_URL=https://github.com/<owner>/<repo>.git bash
```

To register or update this VPS in the remote orchestrator database during install:

```bash
ORCHESTRATOR_URL="https://flowkit-global-orchestrator.onrender.com" \
ORCHESTRATOR_API_KEY="<orchestrator-api-key>" \
WORKER_ID="vps-1" \
WORKER_PUBLIC_URL="http://<oracle-public-ip>:8080" \
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | \
  REPO_URL=https://github.com/<owner>/<repo>.git bash
```

The orchestrator stores `WORKER_PUBLIC_URL` in MongoDB/PostgreSQL through
`POST /workers`. It is not written into YAML. If Oracle changes the IP later,
run:

```bash
cd /opt/flow-worker
ORCHESTRATOR_URL="https://flowkit-global-orchestrator.onrender.com" \
ORCHESTRATOR_API_KEY="<orchestrator-api-key>" \
WORKER_PUBLIC_URL="http://<new-oracle-public-ip>:8080" \
bash scripts/register-worker.sh
```

Optional overrides:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | \
  APP_DIR=/opt/flow-worker \
  BRANCH=main \
  REPO_URL=https://github.com/<owner>/<repo>.git \
  bash
```

### 3. Update Existing VPS

```bash
cd /opt/flow-worker
sudo bash ./scripts/update.sh
```

### 4. Check Worker

```bash
curl http://127.0.0.1:8080/health
docker compose ps
```

### 5. Add Account

```bash
curl -X POST http://127.0.0.1:8080/accounts \
  -H 'content-type: application/json' \
  -d '{"id":"acc-1"}'
```

Then connect to VNC port `5902` for `acc-1`, sign in to Google Flow once, and the profile persists under `/opt/flow-worker/chrome-profiles/acc-1`.
