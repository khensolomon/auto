# Secrets Management Guide

**Tools:** `secrets.conf` · `secrets.py` · `gh` (GitHub CLI)

This guide covers the complete setup and ongoing management of the GitHub Actions secrets required by `deploy.yml`. All secrets are managed from a single local file and pushed to GitHub with one command.

---

## Table of Contents

1. [How it works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites)
3. [First-time setup](#3-first-time-setup)
4. [Filling in secrets.conf](#4-filling-in-secretsconf)
5. [Pushing secrets to GitHub](#5-pushing-secrets-to-github)
6. [Verifying the result](#6-verifying-the-result)
7. [Day-to-day operations](#7-day-to-day-operations)
8. [Secret reference](#8-secret-reference)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. How it works

```
secrets.conf  (local, never committed)
     │
     │  KEY=inline value
     │  KEY=@~/path/to/file   ← file contents read at push time
     │
     ▼
secrets.py
     │  1. Checks gh is installed and authenticated
     │  2. Parses and validates secrets.conf
     │  3. Resolves @file references
     │  4. Calls: gh secret set KEY --repo org/repo  (once per secret)
     │            └── gh handles encryption and the GitHub API
     ▼
GitHub Repository Secrets
     └── consumed by deploy.yml at workflow runtime
```

**File references** (`@~/path/to/file`) allow secrets with large or multi-line values — SSH private keys, application `.env` files — to stay in their own files. The script reads the file at that path and passes its contents to `gh` automatically.

**`gh` handles all crypto.** There is no encryption code in `secrets.py`. GitHub CLI encrypts each value with the repository's public key (libsodium sealed box) before it leaves the local machine. This is maintained by GitHub and is always up to date.

---

## 2. Prerequisites

### Install gh (GitHub CLI)

`gh` is a native system package — no pip, no venv.

**Ubuntu / Debian:**
```bash
sudo apt install gh
```
> If `gh` is not found, add the official GitHub repository first:
> ```bash
> curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
>   | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
> echo "deb [arch=$(dpkg --print-architecture) \
>   signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
>   https://cli.github.com/packages stable main" \
>   | sudo tee /etc/apt/sources.list.d/github-cli.list
> sudo apt update && sudo apt install gh
> ```

**macOS:**
```bash
brew install gh
```

**Windows:**
```bash
winget install --id GitHub.cli
```

**All platforms:** [cli.github.com](https://cli.github.com)

### Authenticate gh

After installation, authenticate once. This stores credentials in the system keychain — no token management needed afterwards.

```bash
gh auth login
```

Follow the prompts:
- Select **GitHub.com**
- Select **HTTPS** as the preferred protocol
- Select **Login with a web browser** (or paste a token)

Verify it worked:
```bash
gh auth status
```

### Verify everything is ready

```bash
python3 secrets.py --check
```

Expected output:
```
  Checking gh CLI...

  gh version  : gh version 2.x.x (...)
  gh auth     : Logged in to github.com account <username> (...)
```

---

## 3. First-time setup

### Create a working directory

Keep all deployment-related files in one place, away from any repository:

```bash
mkdir -p ~/deploy
cd ~/deploy
```

### Copy the files into place

```bash
cp /path/to/secrets.conf  ~/deploy/secrets.conf
cp /path/to/secrets.py    ~/deploy/secrets.py
chmod 600 ~/deploy/secrets.conf
```

### Add to .gitignore

If the working directory is inside a repository, ensure these files are never committed:

```bash
echo "secrets.conf" >> .gitignore
echo "*.env"        >> .gitignore
```

### Create the application .env file

`deploy.yml` recreates the server `.env` on every deployment from the `ENV_FILE_CONTENT` secret. The source is a local `.env` file referenced in `secrets.conf`.

Create it at the path set in `secrets.conf` (default: `~/deploy/myordbok.env`):

```bash
touch ~/deploy/myordbok.env
chmod 600 ~/deploy/myordbok.env
```

Populate it with all variables the Django application needs at runtime:

```bash
# ~/deploy/myordbok.env
SECRET_KEY=your-django-secret-key
DEBUG=False
ALLOWED_HOSTS=myordbok.com,www.myordbok.com
DB_NAME=myordbok
DB_USER=myordbok_user
DB_PASSWORD=strong-database-password
DB_HOST=db
DB_PORT=3306
MYSQL_ROOT_PASSWORD=strong-root-password
MYSQL_DATABASE=myordbok
MYSQL_USER=myordbok_user
MYSQL_PASSWORD=strong-database-password
```

---

## 4. Filling in secrets.conf

Open `~/deploy/secrets.conf` and fill in each value. The sections below explain exactly where to get each one.

### Section 1 — Server access

**`SERVER_HOSTNAME`**

The hostname the GitHub Actions runner connects to when deploying remotely.

- For `deploy_via_tunnel`: the `ssh` subdomain configured in Cloudflare Zero Trust, e.g. `ssh.admin.com`
- For `deploy_via_ssh`: the server's public IP address or DNS hostname

```ini
SERVER_HOSTNAME=ssh.admin.com
```

**`SERVER_USER`**

The SSH login user on the production server. Typically `root` on a fresh VPS.

```ini
SERVER_USER=root
```

**`SSH_PRIVATE_KEY`**

The private key used to authenticate SSH from GitHub Actions.

Generate a dedicated deploy key:

```bash
ssh-keygen -t ed25519 -C "prod-deploy" -f ~/.ssh/prod_server -N ""
```

Add the public key to the server:

```bash
ssh-copy-id -i ~/.ssh/prod_server.pub root@<server-ip>
```

Point `secrets.conf` at the private key file using the `@` file reference:

```ini
SSH_PRIVATE_KEY=@~/.ssh/prod_server
```

The `@` prefix means the file contents are read and pushed — not the path string itself.

---

### Section 2 — GitHub runner status

**`VM_RUNNER_STATUS_PAT`**

Used by `check_local_vm_runner` in `deploy.yml` to poll the GitHub API and detect whether the self-hosted runner is online.

**Where to create:**

1. GitHub → **Settings** (account level) → **Developer settings**
2. **Personal access tokens → Fine-grained tokens → Generate new token**
3. Repository access: select the deployment repository
4. Permission: **Actions → Read-only**
5. Generate and copy the token

```ini
VM_RUNNER_STATUS_PAT=github_pat_xxxx
```

---

### Section 3 — Application environment

**`ENV_FILE_CONTENT`**

Full contents of the application `.env` file. Pushed once, recreated on the server on every deploy.

```ini
ENV_FILE_CONTENT=@~/deploy/myordbok.env
```

---

### Section 4 — Cloudflare tunnel authentication

Used by `deploy_via_tunnel` to authenticate the GitHub-hosted runner through Cloudflare Zero Trust without port 22 being open.

**Where to create:**

1. [dash.cloudflare.com](https://dash.cloudflare.com) → **Zero Trust**
2. **Access → Service Auth → Service Tokens → Create Service Token**
3. Name it `github-actions-deploy`
4. Set an expiry (1 year recommended — set a calendar reminder)
5. Copy the **Client ID** and **Client Secret**

> The Client Secret is shown **once only** at creation. If lost, the token must be deleted and recreated.

```ini
CF_SERVICE_TOKEN_ID=xxxx.access
CF_SERVICE_TOKEN_SECRET=xxxx
```

---

## 5. Pushing secrets to GitHub

### Validate first (dry-run)

Always validate before pushing to catch missing files, unfilled placeholders, or format errors:

```bash
cd ~/deploy
python3 secrets.py --config secrets.conf --repo org/reponame --dry-run
```

Expected output:

```
SECRET                    VALUE PREVIEW              ACTION
------------------------  -------------------------  ----------
CF_SERVICE_TOKEN_ID       xxxx.ac******************  would push
CF_SERVICE_TOKEN_SECRET   xxxxxx****************     would push
ENV_FILE_CONTENT          [42 lines]                 would push
SERVER_HOSTNAME           ssh.admin.com              would push
SERVER_USER               root                       would push
SSH_PRIVATE_KEY           [38 lines]                 would push
VM_RUNNER_STATUS_PAT      github_p******************  would push

  Dry-run complete. 7 secret(s) validated. Nothing was pushed.
```

### Push all secrets

```bash
python3 secrets.py --config secrets.conf --repo org/reponame
```

Expected output:

```
  Repository : org/reponame
  Secrets    : 7

SECRET                    VALUE PREVIEW              RESULT
------------------------  -------------------------  ----------
CF_SERVICE_TOKEN_ID       xxxx.ac******************  OK  pushed
CF_SERVICE_TOKEN_SECRET   xxxxxx****************     OK  pushed
ENV_FILE_CONTENT          [42 lines]                 OK  pushed
SERVER_HOSTNAME           ssh.admin.com              OK  pushed
SERVER_USER               root                       OK  pushed
SSH_PRIVATE_KEY           [38 lines]                 OK  pushed
VM_RUNNER_STATUS_PAT      github_p******************  OK  pushed

  Total : 7  |  Success : 7  |  Failed : 0

  All 7 secret(s) pushed successfully.
```

---

## 6. Verifying the result

### Via secrets.py

```bash
python3 secrets.py --config secrets.conf --repo org/reponame --list
```

Calls `gh secret list` and prints all secret names currently set on the repository. Values are never shown — only names.

### Via the GitHub UI

1. Repository → **Settings → Secrets and variables → Actions**
2. All 7 secret names should appear in the list

Secrets cannot be read back — only names are visible. This is expected.

### Via a test deployment

Trigger a deployment and confirm all jobs complete without authentication errors:

```bash
git commit --allow-empty -m "deploy: test secrets configuration"
git push origin master
```

Watch the run under **Actions** in the repository.

---

## 7. Day-to-day operations

### Rotate a single secret

Edit the value in `secrets.conf` (or update the referenced file), then push only that secret:

```bash
python3 secrets.py --config secrets.conf --repo org/reponame --only CF_SERVICE_TOKEN_SECRET
```

### Update the application .env

Edit `~/deploy/myordbok.env`, then push:

```bash
python3 secrets.py --config secrets.conf --repo org/reponame --only ENV_FILE_CONTENT
```

The new value takes effect on the next deployment run.

### Rotate the SSH key

```bash
# 1. Generate a new key
ssh-keygen -t ed25519 -C "prod-deploy-rotated" -f ~/.ssh/prod_server_new -N ""

# 2. Add to the server (keep the old key active during transition)
ssh-copy-id -i ~/.ssh/prod_server_new.pub root@<server-hostname>

# 3. Update secrets.conf to point at the new key
#    SSH_PRIVATE_KEY=@~/.ssh/prod_server_new

# 4. Push the updated key
python3 secrets.py --config secrets.conf --repo org/reponame --only SSH_PRIVATE_KEY

# 5. Test a deployment — confirm it works with the new key
# 6. Remove the old key from the server's authorized_keys
```

### Renew an expired Cloudflare Service Token

1. Cloudflare → **Zero Trust → Access → Service Auth → Service Tokens**
2. Delete the expired `github-actions-deploy` token
3. Create a new one with the same name
4. Update `secrets.conf` with the new ID and secret
5. Push both:

```bash
python3 secrets.py --config secrets.conf --repo org/reponame --only CF_SERVICE_TOKEN_ID
python3 secrets.py --config secrets.conf --repo org/reponame --only CF_SERVICE_TOKEN_SECRET
```

### Add a new secret

1. Add the new `KEY=value` line to `secrets.conf`
2. Run a dry-run to validate
3. Push all (re-pushing existing secrets is safe — they are updated, not duplicated):

```bash
python3 secrets.py --config secrets.conf --repo org/reponame
```

### Re-authenticate gh after credential expiry

```bash
gh auth refresh
# or start fresh
gh auth login
```

---

## 8. Secret reference

Full reference of every secret consumed by `deploy.yml`.

| Secret | Section in conf | Used by | Notes |
|---|---|---|---|
| `ENV_FILE_CONTENT` | Section 3 | All deploy paths | Full app `.env` — recreated on server each deploy |
| `SSH_PRIVATE_KEY` | Section 1 | `deploy_via_tunnel`, `deploy_via_ssh` | Ed25519 private key |
| `SERVER_HOSTNAME` | Section 1 | `deploy_via_tunnel`, `deploy_via_ssh` | Tunnel hostname or server IP |
| `SERVER_USER` | Section 1 | `deploy_via_tunnel`, `deploy_via_ssh` | SSH login user |
| `VM_RUNNER_STATUS_PAT` | Section 2 | `check_local_vm_runner` | PAT with Actions read-only scope |
| `CF_SERVICE_TOKEN_ID` | Section 4 | `deploy_via_tunnel` | Cloudflare service token Client ID |
| `CF_SERVICE_TOKEN_SECRET` | Section 4 | `deploy_via_tunnel` | Cloudflare service token Client Secret |
| `GITHUB_TOKEN` | — | Build phase | Auto-provided by GitHub Actions — never push manually |

### GitHub environments

`deploy_via_tunnel` and `deploy_via_ssh` are scoped to named GitHub environments. Create these before the first deployment:

**Repository → Settings → Environments → New environment**

| Environment name | Used by |
|---|---|
| `production-tunnel` | `deploy_via_tunnel` |
| `production-ssh` | `deploy_via_ssh` |

Environments support additional deployment gates — required reviewers, wait timers, and environment-scoped secrets.

---

## 9. Troubleshooting

### `gh is not installed or not on PATH`

Install `gh` for the current platform and re-run `python3 secrets.py --check`:

```bash
# Ubuntu/Debian
sudo apt install gh

# macOS
brew install gh

# Windows
winget install --id GitHub.cli
```

---

### `gh is installed but not authenticated`

Run the one-time login:

```bash
gh auth login
```

Then verify:

```bash
gh auth status
```

---

### `REPLACE_ME placeholder` error

A value in `secrets.conf` still has the default placeholder. Open the file, find the key listed in the error, and replace the value with the real one. Then re-run `--dry-run` to confirm.

---

### `file reference not found`

The path after `@` does not exist on the local machine. Verify the file exists at the expected path:

```bash
ls -la ~/deploy/myordbok.env
ls -la ~/.ssh/prod_server
```

Ensure the `~` in the path expands correctly for the current user.

---

### `ERR` row in the results table

`gh secret set` returned a non-zero exit code for that secret. Common causes:

- The `--repo` argument does not match the repository exactly (case-sensitive).
- The authenticated `gh` account does not have write access to the repository.
- The repository does not exist or has been renamed.

Run `gh auth status` to confirm the correct account is active, and `gh repo view org/reponame` to confirm repository access.

---

### Secret pushed but deploy still fails with auth error

GitHub Actions caches secrets for the duration of a run. A secret updated mid-run is not visible until the next run. Re-trigger the deployment after pushing.

If the issue persists, confirm the secret name in `secrets.conf` exactly matches the name referenced in `deploy.yml` — secret names are case-sensitive.

---

### `deploy_via_tunnel` fails — authentication error at SSH step

The Cloudflare Service Token has likely expired. Check at:

**Cloudflare → Zero Trust → Access → Service Auth → Service Tokens**

If expired, follow the renewal procedure in Section 7.

---

### Re-running secrets.py on a new machine

`secrets.py` and `secrets.conf` are the only files needed. On the new machine:

```bash
# 1. Install gh
sudo apt install gh          # or brew / winget

# 2. Authenticate
gh auth login

# 3. Copy secrets.conf and referenced files to the new machine
#    (e.g. ~/.ssh/prod_server, ~/deploy/myordbok.env)

# 4. Verify
python3 secrets.py --check
python3 secrets.py --config secrets.conf --repo org/reponame --dry-run
```
