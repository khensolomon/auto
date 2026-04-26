# Production Deployment Guide

**Stack:** Django · MySQL · Nginx · Docker Swarm · Nginx Proxy Manager · Cloudflare Tunnel · GitHub Actions

This guide covers the complete setup of a production server from a fresh Ubuntu/Debian droplet to a fully automated deployment pipeline. Follow each section in order on a first-time setup.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Server Provisioning](#2-server-provisioning)
3. [Running the Setup Script](#3-running-the-setup-script)
4. [Directory Structure](#4-directory-structure)
5. [Cloudflare Zero Trust Configuration](#5-cloudflare-zero-trust-configuration)
   - [5.1 Domain active on Cloudflare](#51-prerequisites--domain-must-be-active-on-cloudflare)
   - [5.2 Get the tunnel token](#52-get-the-tunnel-token-first-time-setup-only)
   - [5.3 Add public hostnames](#53-add-public-hostnames-to-the-tunnel)
   - [5.4 Protect NPM with Access policy](#54-protect-the-npm-admin-ui-with-an-access-policy)
   - [5.5 Create a Service Token](#55-create-a-service-token-for-github-actions-tunnel-deployment)
   - [5.6 Check tunnel status](#56-check-tunnel-status)
6. [Nginx Proxy Manager Configuration](#6-nginx-proxy-manager-configuration)
   - [6.1 First login](#61-first-login)
   - [6.2 Create proxy host for Django](#62-create-a-proxy-host-for-the-django-application)
   - [6.3 Test SSH through the tunnel](#63-test-ssh-through-the-tunnel-before-closing-port-22)
   - [6.4 Close port 22](#64-close-port-22)
   - [6.5 SSL for additional hosts](#65-configure-ssl-for-additional-proxy-hosts)
7. [GitHub Actions Self-Hosted Runner](#7-github-actions-self-hosted-runner)
8. [GitHub Repository Secrets](#8-github-repository-secrets)
9. [Triggering a Deployment](#9-triggering-a-deployment)
10. [Deployment Methods Explained](#10-deployment-methods-explained)
11. [Monitoring & Logs](#11-monitoring--logs)
12. [Rollback Procedure](#12-rollback-procedure)
13. [Emergency Server Access](#13-emergency-server-access)
14. [Firewall Reference](#14-firewall-reference)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Prerequisites

### Accounts and services required

| Service | Purpose | Where to create |
|---|---|---|
| DigitalOcean (or any VPS) | Production server | [digitalocean.com](https://digitalocean.com) |
| GitHub | Repository + Actions runner + GHCR image registry | [github.com](https://github.com) |
| Cloudflare | DNS + Zero Trust tunnel | [cloudflare.com](https://cloudflare.com) |

### Local machine requirements

- `ssh` and `ssh-keygen` available in the terminal
- `git` installed
- A domain pointed to Cloudflare nameservers

---

## 2. Server Provisioning

### Create the droplet

Provision a fresh **Ubuntu 22.04 LTS** or **Debian 12** server. Minimum recommended specs:

| Resource | Minimum | Recommended |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 1 GB | 2 GB |
| Disk | 25 GB SSD | 50 GB SSD |

### Generate an SSH key pair

On the local machine:

```bash
ssh-keygen -t ed25519 -C "prod-server-deploy" -f ~/.ssh/prod_server
```

This produces two files:
- `~/.ssh/prod_server` — **private key** (never shared, added to GitHub secrets later)
- `~/.ssh/prod_server.pub` — **public key** (added to the server)

### Add the public key to the server

When provisioning through DigitalOcean, paste the contents of `~/.ssh/prod_server.pub` into the SSH key field. Alternatively, after the server is running:

```bash
ssh-copy-id -i ~/.ssh/prod_server.pub root@<server-ip>
```

### Verify SSH access

```bash
ssh -i ~/.ssh/prod_server root@<server-ip>
```

---

## 3. Running the Setup Script

`setup.py` bootstraps the entire server. It installs Docker, configures UFW, creates application directories, and brings up Nginx Proxy Manager with an optional Cloudflare Tunnel.

### Transfer the script to the server

```bash
scp -i ~/.ssh/prod_server setup.py root@<server-ip>:/root/setup.py
```

### Run options

**Standard install (no tunnel):**
```bash
sudo python3 setup.py
```

**With Cloudflare Tunnel (recommended for production):**
```bash
sudo python3 setup.py --cloudflare-token <TOKEN_FROM_ZERO_TRUST>
```
See [Section 5](#5-cloudflare-zero-trust-configuration) for where to get the token.

**Custom swap size:**
```bash
sudo python3 setup.py --cloudflare-token <TOKEN> --swap 4G
```

**Dry-run (preview all actions without making changes):**
```bash
sudo python3 setup.py --dry-run
```

**Force reinstall (overwrites existing config):**
```bash
sudo python3 setup.py --cloudflare-token <TOKEN> --force
```

### What the script installs

| Step | What happens |
|---|---|
| Python alias | Links `python3` → `python` |
| Swap | Allocates a 2 GB swap file at `/swapfile` (configurable) |
| Security | Installs `fail2ban`, `unattended-upgrades`, `jq` |
| Firewall | Configures UFW: allows SSH, 80, 443. Port 81 is intentionally closed |
| Directories | Creates `/opt/bucket`, `/opt/myordbok`, `/opt/django/media`, `/opt/mysql/data` |
| Docker CE | Installs Docker Engine + Compose plugin + Buildx |
| Docker Swarm | Initialises a single-node swarm |
| NPM + Tunnel | Deploys Nginx Proxy Manager and Cloudflare Tunnel via Docker Compose |

### Verify the install completed

```bash
docker info
docker compose version
docker service ls
ufw status
```

Setup logs are written to `/var/log/setup.log`.

---

## 4. Directory Structure

```
/opt/
├── nginx-proxy-manager/       # NPM stack (docker-compose.yml + data)
│   ├── docker-compose.yml
│   ├── .env                   # Cloudflare tunnel token (chmod 600)
│   ├── data/
│   └── letsencrypt/
│
├── myordbok/                  # Application deployment directory
│   ├── docker.production.yml  # Copied here by deploy.yml on each deploy
│   └── .env                   # Recreated from GitHub secret on each deploy
│
├── bucket/                    # Shared persistent storage for the application
│
├── django/
│   └── media/                 # Django media file uploads
│
└── mysql/
    └── data/                  # MySQL data directory (owned by uid 999)
```

> `/opt/myordbok/.env` is **not** a manually managed file. It is recreated from the `ENV_FILE_CONTENT` GitHub secret on every deployment run.

---

## 5. Cloudflare Zero Trust Configuration

### 5.1 Prerequisites — domain must be active on Cloudflare

The domain must be added to Cloudflare and its nameservers must be pointing to Cloudflare before any tunnel hostnames will work.

**To verify:**
1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Click the domain name
3. The status badge at the top must read **Active**

If the domain is not yet added, go to **Add a Site**, enter the domain, choose a plan (Free is sufficient), and update the nameservers at the domain registrar as instructed.

---

### 5.2 Get the tunnel token (first-time setup only)

> If `setup.py` has already been run successfully with `--cloudflare-token` and the tunnel shows as **Healthy**, skip to [5.3](#53-add-public-hostnames-to-the-tunnel).

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Navigate to **Zero Trust → Networks → Tunnels**
3. Click **Create a tunnel** → choose **Cloudflared**
4. Name the tunnel (e.g. `prod-server`)
5. Copy the tunnel token — this is the value passed to `setup.py --cloudflare-token`

> The token is stored in `/opt/nginx-proxy-manager/.env` with permissions `600`. It is never written into any Docker command string or visible in `docker inspect`.

---

### 5.3 Add public hostnames to the tunnel

The tunnel is already running. Now routes need to be added so traffic for each hostname is forwarded to the right internal service.

1. Go to **Zero Trust → Networks → Tunnels**
2. Find the tunnel — it should show **Healthy**
3. Click the tunnel name → click **Edit**
4. Click the **Public Hostname** tab
5. Add each hostname below using **Add a public hostname**

---

#### `example.com` — Django application

| Field | Value |
|---|---|
| Subdomain | *(leave blank)* |
| Domain | `example.com` |
| Path | *(leave blank)* |
| Type | `HTTP` |
| URL | `localhost:80` |

Click **Save hostname**.

> The tunnel container runs with `network_mode: host` — it shares the host network stack directly. `localhost` inside the tunnel container is the Docker host itself, so `localhost:80` correctly reaches NPM which is listening on port 80 of the host.

---

#### `npm.example.com` — NPM admin UI

| Field | Value |
|---|---|
| Subdomain | `npm` |
| Domain | `example.com` |
| Path | *(leave blank)* |
| Type | `HTTP` |
| URL | `localhost:81` |

Click **Save hostname**.

> Port 81 is bound to `127.0.0.1` on the host and is not reachable from the internet directly. The tunnel reaches it via `localhost:81` because `network_mode: host` gives the tunnel container direct access to the host network stack.

---

#### `ssh.example.com` — Server SSH access

| Field | Value |
|---|---|
| Subdomain | `ssh` |
| Domain | `example.com` |
| Path | *(leave blank)* |
| Type | `SSH` |
| URL | `localhost:22` |

Click **Save hostname**.

> The service type **must** be set to `SSH`, not `HTTP` or `Browser SSH`. Using `HTTP` causes a silent `bad handshake` error. Using `Browser SSH` works only from a browser — native SSH clients and the GitHub Actions tunnel deploy will fail with `websocket: bad handshake`.
>
> `localhost:22` works because the tunnel container uses `network_mode: host`, giving it direct access to the host's `sshd` without any special hostnames or IP addresses.

---

### 5.4 Protect the NPM admin UI with an Access policy

Without an Access policy, anyone who discovers `npm.example.com` could reach the NPM login page. An Access policy adds a Cloudflare-enforced authentication gate in front of it.

1. Go to **Zero Trust → Access → Applications**
2. Click **Add an application** → choose **Self-hosted**
3. Fill in:
   - **Application name:** `NPM Admin`
   - **Application domain:** `npm.example.com`
4. Click **Next**
5. Under **Policies**, click **Add a policy**:
   - **Policy name:** `owner-only`
   - **Action:** `Allow`
   - Under **Add rules**, set selector to `Emails` and enter the Cloudflare account email address
6. Click **Save policy** → **Next** → **Add application**

From this point, visiting `npm.example.com` will show a Cloudflare Access login screen that emails a one-time PIN to the address above. Only after that PIN is entered will the NPM login page appear.

---

### 5.5 Create a Service Token (for GitHub Actions tunnel deployment)

The `deploy_via_tunnel` job in `deploy.yml` authenticates to the tunnel programmatically using a Service Token — no browser or interactive login involved.

1. Go to **Zero Trust → Access → Service Auth → Service Tokens**
2. Click **Create Service Token**
3. Name it `github-actions-deploy`
4. Set an expiry (recommend 1 year, note the date)
5. Copy the **Client ID** → this becomes `CF_SERVICE_TOKEN_ID` in GitHub secrets
6. Copy the **Client Secret** → this becomes `CF_SERVICE_TOKEN_SECRET` in GitHub secrets

> Service tokens expire. Set a calendar reminder to rotate them before the expiry date. An expired token causes `deploy_via_tunnel` to fail at the SSH connection step.

---

### 5.6 Check tunnel status

From the server:

```bash
docker logs -f cloudflare-tunnel
docker exec cloudflare-tunnel cloudflared tunnel info
```

From the Cloudflare dashboard:
**Zero Trust → Networks → Tunnels** — the tunnel should show as **Healthy** and the three public hostnames added above should be listed under the **Public Hostname** tab.

---

## 6. Nginx Proxy Manager Configuration

Port 81 is bound to `127.0.0.1` only and is not reachable from the public internet. Access the NPM admin UI exclusively through the `npm.example.com` Cloudflare Tunnel hostname configured in Section 5.

---

### 6.1 First login

> **If the tunnel hostnames in Section 5 are not yet configured**, use an SSH port-forward from the local machine to access NPM directly for the first time:
> ```bash
> ssh -i ~/.ssh/prod_server -L 8181:127.0.0.1:81 root@<server-ip>
> ```
> Then open `http://localhost:8181` in the browser. Once the tunnel hostnames are working, this port-forward is no longer needed.

Once `npm.example.com` is configured and the Access policy is in place:

1. Open `https://npm.example.com`
2. Cloudflare Access will prompt for an email — enter the address set in the Access policy
3. Check that email for a one-time PIN and enter it
4. The NPM login screen appears

Default credentials:
```
Email:    admin@example.com
Password: changeme
```

**Change both immediately after first login.**

---

### 6.2 Create a proxy host for the Django application

The tunnel routes `example.com` traffic to NPM on port 80. NPM then forwards that traffic to the Django application running inside the Docker Swarm stack.

1. In NPM, go to **Hosts → Proxy Hosts → Add Proxy Host**
2. Fill in the **Details** tab:

| Field | Value |
|---|---|
| Domain names | `example.com` |
| Scheme | `http` |
| Forward hostname / IP | Django swarm service name (e.g. `myordbok_web`) |
| Forward port | Django/Gunicorn internal port (typically `8000`) |
| Block common exploits | ✅ enabled |
| Websockets support | enable if the app uses websockets |

3. Click the **SSL** tab:
   - Select **Request a new SSL Certificate**
   - Enable **Force SSL**
   - Enable **HTTP/2 Support**
   - Enable **HSTS Enabled** for production

4. Click **Save**

> To find the exact service name, run `docker service ls` on the server. The web service will appear in the `NAME` column.

---

### 6.3 Test SSH through the tunnel (before closing port 22)

Install `cloudflared` on the **local machine** (not the server):

```bash
# macOS
brew install cloudflared

# Linux (Debian/Ubuntu)
wget -q https://github.com/cloudflare/cloudflared/releases/download/2025.4.0/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Windows — download the installer from:
# https://github.com/cloudflare/cloudflared/releases
```

Add this block to `~/.ssh/config` on the local machine (create the file if it does not exist):

```
Host ssh.example.com
    ProxyCommand cloudflared access ssh --hostname %h
    User root
    IdentityFile ~/.ssh/prod_server
```

Test the connection while port 22 is still open:

```bash
ssh ssh.example.com
```

Cloudflare will open a browser window the first time to authenticate. After authentication the terminal connects to the server. If this works correctly, proceed to close port 22.

---

### 6.4 Close port 22

> Only close port 22 after the `ssh ssh.example.com` test above succeeds from the local machine.

Run the following **from an active SSH session** on the server:

```bash
sudo ufw delete allow ssh
sudo ufw status
```

Port 22 is now closed. All future terminal access is via `ssh ssh.example.com` through the Cloudflare Tunnel. The DigitalOcean web console remains available as an emergency fallback (see Section 13).

---

### 6.5 Configure SSL for additional proxy hosts

For any additional domains or subdomains routed through NPM, follow the same SSL pattern:

1. Go to **SSL** tab when creating or editing a proxy host
2. Select **Request a new SSL Certificate**
3. Enable **Force SSL** and **HTTP/2 Support**
4. Enable **HSTS** for production hostnames

---

## 7. GitHub Actions Self-Hosted Runner

The `deploy_local_vm` job in `deploy.yml` runs directly on the production server using a self-hosted runner. This runner is **not installed by `setup.py`** and must be registered manually.

### Register the runner

1. Go to the GitHub repository → **Settings → Actions → Runners**
2. Click **New self-hosted runner**
3. Select **Linux** and **x64**
4. Follow the displayed commands on the production server — they look like:

```bash
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.x.x.tar.gz -L https://github.com/actions/runner/releases/download/...
tar xzf ./actions-runner-linux-x64-2.x.x.tar.gz
./config.sh --url https://github.com/<org>/<repo> --token <RUNNER_TOKEN>
```

### Install as a system service

After configuration, install the runner as a service so it starts on reboot:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

### Check runner status

```bash
sudo ./svc.sh status
```

Or check in GitHub: **Settings → Actions → Runners** — the runner should show as **Idle**.

### Create the PAT for runner status checks

The `check_local_vm_runner` job polls the GitHub API to detect whether the runner is online before attempting a local deploy. This requires a Personal Access Token.

**Where to create it:**
1. GitHub → **Settings (account level) → Developer settings → Personal access tokens → Fine-grained tokens**
2. Set repository access to the deployment repository
3. Grant **read-only** permission for **Actions**
4. Copy the token → this becomes `VM_RUNNER_STATUS_PAT` in GitHub secrets

---

## 8. GitHub Repository Secrets

Secrets are managed through two companion files — `secrets.conf` and `secrets.py` — rather than manually through the GitHub UI. See **SECRETS_GUIDE.md** for the full walkthrough.

The short version:

```bash
# Install dependencies (once)
pip install requests PyNaCl

# Set the push token
export GITHUB_TOKEN=github_pat_xxxx

# Fill in secrets.conf, then validate
python3 secrets.py --config secrets.conf --repo org/reponame --dry-run

# Push all secrets to GitHub
python3 secrets.py --config secrets.conf --repo org/reponame
```

### Required secrets

| Secret | Source | Used by |
|---|---|---|
| `ENV_FILE_CONTENT` | Local app `.env` file | All deploy paths |
| `SSH_PRIVATE_KEY` | `~/.ssh/prod_server` (private key file) | `deploy_via_tunnel`, `deploy_via_ssh` |
| `SERVER_HOSTNAME` | Cloudflare tunnel hostname or server IP | `deploy_via_tunnel`, `deploy_via_ssh` |
| `SERVER_USER` | SSH login user on the server | `deploy_via_tunnel`, `deploy_via_ssh` |
| `VM_RUNNER_STATUS_PAT` | GitHub fine-grained PAT, Actions read-only | `check_local_vm_runner` |
| `CF_SERVICE_TOKEN_ID` | Cloudflare Zero Trust → Service Tokens | `deploy_via_tunnel` |
| `CF_SERVICE_TOKEN_SECRET` | Cloudflare Zero Trust → Service Tokens | `deploy_via_tunnel` |
| `GITHUB_TOKEN` | Auto-provided by GitHub Actions | Build phase — never set manually |

### GitHub environments

The tunnel and SSH deploy jobs are scoped to named environments. Create these before the first deployment:

**Repository → Settings → Environments → New environment**

| Environment name | Used by |
|---|---|
| `production-tunnel` | `deploy_via_tunnel` |
| `production-ssh` | `deploy_via_ssh` |

Environments support additional deployment gates — required reviewers, wait timers, and environment-scoped secrets.

### Verify secrets are set

```bash
python3 secrets.py --config secrets.conf --repo org/reponame --list
```

This calls the GitHub API and prints all secret names currently on the repository. Values are never shown — only names.

---

## 9. Triggering a Deployment

Deployments are triggered by pushing to the `master` branch with a commit message that begins with `deploy:`.

### Commit message format

```
deploy: <description> [optional-tag]
```

### Deployment method selection

The commit message tag controls which remote deployment method fires.

| Commit message | What runs |
|---|---|
| `deploy: fix login bug` | Local VM runner only (if online) |
| `deploy: fix login bug [tunnel]` | Local VM runner (if online) + Cloudflare Tunnel deploy |
| `deploy: fix login bug [ssh]` | Local VM runner (if online) + Native SSH deploy |
| `deploy: fix login bug [tunnel] [ssh]` | `[tunnel]` wins, `[ssh]` is suppressed |

> `[tunnel]` and `[ssh]` are **mutually exclusive**. If both appear in the same commit message, `[tunnel]` takes priority and `[ssh]` is ignored. This prevents two methods from deploying to the same server simultaneously.

### Example workflow

```bash
git add .
git commit -m "deploy: update homepage layout [tunnel]"
git push origin master
```

### Watch the pipeline

1. Go to the repository → **Actions** tab
2. Find the most recent workflow run
3. Click into it to see job progress in real time
4. On success, each job writes a summary showing the method, commit SHA, and timestamp

---

## 10. Deployment Methods Explained

### Method 1 — Local VM (self-hosted runner)

**When it runs:** Automatically, whenever the self-hosted runner is detected as online. No commit tag needed.

**How it works:** The GitHub Actions runner process running on the production server executes the deployment steps locally. No SSH or network tunnelling is involved — Docker commands run directly on the host.

**Best for:** Day-to-day deployments when the server is on the same local network or accessible.

### Method 2 — Cloudflare Tunnel (`[tunnel]`)

**When it runs:** When `[tunnel]` appears in the commit message and `[ssh]` does not.

**How it works:** The GitHub-hosted runner (ubuntu-latest) downloads and caches `cloudflared`, establishes an authenticated SSH session through Cloudflare Zero Trust, copies the compose file and `.env` over SCP, then executes the deployment over that tunnel. Port 22 does not need to be open to the internet.

**Cloudflared version:** Pinned to `2025.4.0` and cached via `actions/cache`. The binary is only re-downloaded when the cache key changes. To upgrade, update the version string in both the cache key and the download URL in `deploy.yml`.

**Best for:** Remote servers where direct SSH is unavailable or port 22 is closed.

### Method 3 — Native SSH (`[ssh]`)

**When it runs:** When `[ssh]` appears in the commit message and `[tunnel]` does not.

**How it works:** Uses `appleboy/scp-action` and `appleboy/ssh-action` to copy files and execute the deployment over a standard SSH connection. Requires port 22 to be accessible from GitHub Actions IP ranges.

**Best for:** Environments where Cloudflare Tunnel is not available, or during initial setup before the tunnel is configured.

### Docker image tagging

Every build pushes two tags per image:

```
ghcr.io/<repo>/django-app:latest
ghcr.io/<repo>/django-app:<commit-sha>
```

The `:latest` tag is what the running stack uses. The SHA tag is kept in the registry for rollback purposes.

---

## 11. Monitoring & Logs

### GitHub Actions deployment summary

After each successful deployment, a summary is written to the GitHub Actions job page:

```
Actions → <workflow run> → <job name> → Summary
```

It shows the deployment method, commit SHA, and timestamp.

### Docker service status

```bash
# All services in the stack
docker service ls

# Replica count for the web service
docker service ls --filter name=myordbok_web

# Live task status
docker service ps myordbok_web
```

### Application logs

```bash
# Stream web service logs
docker service logs myordbok_web --follow

# Stream Nginx logs
docker service logs myordbok_nginx --follow

# Stream database logs
docker service logs myordbok_db --follow

# Last 100 lines only
docker service logs myordbok_web --tail 100
```

### Cloudflare Tunnel logs

```bash
docker logs -f cloudflare-tunnel
docker exec cloudflare-tunnel cloudflared tunnel info
```

### System resource usage

```bash
# Memory and swap usage
free -h

# Disk usage
df -h

# Docker image and volume disk usage
docker system df
```

---

## 12. Rollback Procedure

Every build tags images with the commit SHA. To roll back to a previous version:

### 1. Find the target SHA

Check the GitHub Actions deployment summary for the commit SHA of the last known good deployment, or:

```bash
git log --oneline
```

### 2. Pull the tagged image on the server

```bash
docker pull ghcr.io/<repo>/django-app:<target-sha>
```

### 3. Update the stack to use the pinned tag

Edit `/opt/myordbok/docker.production.yml` to replace `:latest` with `:<target-sha>` for the Django app service, then redeploy:

```bash
cd /opt/myordbok
docker stack deploy -c docker.production.yml --with-registry-auth --detach=false myordbok
```

### 4. Verify the rollback

```bash
docker service ls --filter name=myordbok_web
docker service logs myordbok_web --tail 50
```

---

## 13. Emergency Server Access

### Via Cloudflare Tunnel SSH (primary remote method)

The SSH config entry added in [Section 6.3](#63-test-ssh-through-the-tunnel-before-closing-port-22) handles all future access. To connect:

```bash
ssh ssh.example.com
```

If the `~/.ssh/config` entry has not been added yet, connect directly with:

```bash
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" root@ssh.example.com -i ~/.ssh/prod_server
```

Cloudflare will open a browser window on first use to authenticate. After that, connections are established without further prompts.

### Via DigitalOcean Web Console (fallback — no network required)

The DigitalOcean Recovery Console connects directly through the hypervisor layer. It bypasses UFW, closed ports, and broken networking entirely. Use this if SSH and the Cloudflare Tunnel are both unreachable.

**How to access:**
1. Log in to [cloud.digitalocean.com](https://cloud.digitalocean.com)
2. Navigate to **Droplets → [droplet name] → Access**
3. Click **Launch Droplet Console**

> This console is keyboard and display access to the actual machine. No SSH key, no network, no tunnel is required.

### Re-opening port 22 if needed

If access is completely lost and only the DigitalOcean console is available:

```bash
sudo ufw allow ssh
sudo ufw status
```

This re-opens port 22 temporarily while the tunnel issue is diagnosed and resolved.

---

## 14. Firewall Reference

UFW is configured by `setup.py`. The following rules are in effect after setup:

| Port | Protocol | Status | Reason |
|---|---|---|---|
| 22 | TCP | Open (initially) | SSH access — close after tunnel is verified |
| 80 | TCP | Open | NPM HTTP + Let's Encrypt certificate renewal |
| 443 | TCP | Open | NPM HTTPS |
| 81 | TCP | **Closed** | NPM admin — accessible only via Cloudflare Tunnel |

### Check current rules

```bash
sudo ufw status verbose
```

### Modify rules

```bash
# Allow a port
sudo ufw allow <port>/tcp

# Remove a rule
sudo ufw delete allow <port>/tcp

# Reload after changes
sudo ufw reload
```

---

## 15. Troubleshooting

### Build job does not start

**Check:** The commit message must start with `deploy:` (lowercase, colon, space). The `build` job has this condition:

```yaml
if: startsWith(github.event.head_commit.message, 'deploy:')
```

A message like `Deploy: ...` or `deploy ...` (no colon) will not trigger the pipeline.

---

### `check_local_vm_runner` reports runner as offline

**Check 1:** Verify the runner service is running on the server:

```bash
cd ~/actions-runner
sudo ./svc.sh status
```

If stopped:
```bash
sudo ./svc.sh start
```

**Check 2:** Verify the `VM_RUNNER_STATUS_PAT` secret is set and has not expired. A missing or expired token causes the API call to return an error, which the pipeline treats as offline.

---

### Cloudflare Tunnel deploy fails at SSH step

**Check 1:** Confirm the tunnel is healthy in the Cloudflare dashboard under **Zero Trust → Networks → Tunnels**.

**Check 2:** Confirm the Service Token (`CF_SERVICE_TOKEN_ID` and `CF_SERVICE_TOKEN_SECRET`) has not expired.

**Check 3:** On the server, check tunnel logs:

```bash
docker logs --tail 50 cloudflare-tunnel
```

---

### MySQL readiness check times out

The pipeline waits up to 100 seconds (20 attempts × 5 seconds) for MySQL to accept connections. If it times out:

**Check:** Database logs for startup errors:

```bash
docker service logs myordbok_db --tail 100
```

Common causes: incorrect `MYSQL_ROOT_PASSWORD` in `ENV_FILE_CONTENT`, or insufficient disk space at `/opt/mysql/data`.

---

### Deployment health check fails (`Replicas: 0/2` or `1/2`)

**Check:** Web service logs immediately after a failed deploy:

```bash
docker service logs myordbok_web --tail 100
```

The `Dump Service Logs on Failure` step in the pipeline captures these automatically and displays them in the Actions run output.

---

### NPM admin UI is unreachable at `npm.example.com`

**Check 1:** Confirm the Cloudflare Tunnel is healthy (see above).

**Check 2:** In the Cloudflare Tunnel configuration, confirm the public hostname `npm.example.com` is mapped to `http://app:81` — not `http://localhost:81`. The container hostname `app` is used because both NPM and the tunnel container share the `npm_proxy` Docker overlay network.

**Check 3:** Confirm NPM is running:

```bash
docker ps | grep nginx-proxy-manager
```

---

### Cloudflared binary cache miss every run

The cache key is `cloudflared-2025.4.0`. If the binary path `/usr/local/bin/cloudflared` is not being cached correctly, confirm the `Install Cloudflared` step copies to that exact path:

```bash
sudo cp /usr/bin/cloudflared /usr/local/bin/cloudflared
```

The `actions/cache` step caches `/usr/local/bin/cloudflared`, so the binary must land there for the cache to be effective on subsequent runs.
