# Deployment Checklist

## Before Committing to GitHub

### 1. Remove Sensitive Data

- [ ] Remove hardcoded credentials from all files
- [ ] Replace database credentials with environment variables
- [ ] Replace NanoMDM API keys with environment variables
- [ ] Remove any production URLs or IP addresses
- [ ] Check for any `/path/to/` placeholders

### 2. Files to Update

#### `opt/nanohub/backend_api/mdm-flask-api_wrappper.py`
```python
# Lines 9-10: Replace with environment variables
DEVICES_JSON_PATH = os.getenv('DEVICES_JSON_PATH', '/opt/nanohub/data/devices.json')
WEBHOOK_LOG_PATH = os.getenv('WEBHOOK_LOG_PATH', '/var/log/nanohub/webhook.log')
```

#### All command scripts in `opt/nanohub/tools/api/commands/`
Replace hardcoded credentials:
```bash
# OLD (example - replace with your actual value):
-u "nanohub:YOUR_API_KEY_HERE"

# NEW:
-u "${NANOMDM_USER}:${NANOMDM_API_KEY}"
```

#### `opt/nanohub/tools/api/commands/mdm_analyzer`
```bash
# Replace with environment variables
DB_HOST="${DB_HOST:-localhost}"
DB_USER="${DB_USER}"
DB_PASS="${DB_PASS}"
DB_NAME="${DB_NAME}"
```

#### `opt/nanohub/backend_api/cfg-get-cert-expiry.sh`
```bash
# Replace hardcoded path
CERTDIR="${CERTS_DIR:-/opt/nanohub/certs}"
```

#### `etc/systemd/system/mdm-flask-api.service`
```ini
# Update all /path/to/ placeholders
User=nanohub
WorkingDirectory=/opt/nanohub/backend_api
EnvironmentFile=/opt/nanohub/backend_api/mdm_flask_api_environment
ExecStart=/opt/nanohub/backend_api/venv/bin/python3 /opt/nanohub/backend_api/mdm-flask-api_wrappper.py
```

### 3. Add Missing Endpoint

Add to `mdm-flask-api_wrappper.py`:
```python
@app.route('/api/devices.json')
def devices_json():
    try:
        with open(DEVICES_JSON_PATH, "r") as f:
            devices = json.load(f)
        return jsonify(devices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

### 4. Create Example Configuration

Create `opt/nanohub/backend_api/mdm_flask_api_environment.example`:
```bash
# NanoHUB Configuration
DEVICES_JSON_PATH="/opt/nanohub/data/devices.json"
WEBHOOK_LOG_PATH="/var/log/nanohub/webhook.log"

# NanoMDM Configuration
NANOMDM_URL="http://localhost:9004"
NANOMDM_USER="nanohub"
NANOMDM_API_KEY="your_api_key_here"

# Database Configuration
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="nanohub"
DB_PASSWORD="your_password_here"
DB_NAME="nanohub_mdm"

# Paths
CERTS_DIR="/opt/nanohub/certs"
DEP_DIR="/opt/nanohub/dep"
```

### 5. Documentation

- [ ] Complete README.md with installation steps
- [ ] Add configuration examples
- [ ] Document all API endpoints
- [ ] Add troubleshooting section
- [ ] Create CONTRIBUTING.md guidelines

### 6. Testing

- [ ] Test all API endpoints locally
- [ ] Verify environment variables work
- [ ] Test with fresh installation
- [ ] Check all command scripts execute
- [ ] Verify frontend connects to backend

### 7. Git Preparation

```bash
# Initialize git (if not done)
git init

# Add files
git add .

# Create .gitignore
git add .gitignore

# First commit
git commit -m "Initial commit: NanoHUB MDM Dashboard"

# Add remote
git remote add origin https://github.com/yourusername/nanohub-mdm-dashboard.git

# Push
git push -u origin main
```

## Post-Deployment

### 1. Server Setup

- [ ] Install Python 3.8+
- [ ] Install MySQL/MariaDB
- [ ] Install Nginx
- [ ] Create service user
- [ ] Set up log rotation

### 2. Security Hardening

- [ ] Set proper file permissions (600 for env file)
- [ ] Enable HTTPS with SSL certificate
- [ ] Configure firewall rules
- [ ] Add authentication to dashboard
- [ ] Use read-only database user for queries
- [ ] Restrict Flask API to localhost

### 3. Monitoring

- [ ] Set up log monitoring
- [ ] Configure certificate expiry alerts
- [ ] Monitor service health
- [ ] Set up backup for database

## File Permissions

```bash
# Backend API
sudo chmod 755 /opt/nanohub/backend_api/mdm-flask-api_wrappper.py
sudo chmod 600 /opt/nanohub/backend_api/mdm_flask_api_environment

# Command scripts
sudo chmod 755 /opt/nanohub/tools/api/commands/*
sudo chmod 755 /opt/nanohub/backend_api/cfg-get-cert-expiry.sh

# Web files
sudo chmod 644 /var/www/mdm-web/index.html
sudo chmod 644 /var/www/mdm-web/static/dashboard.css

# Systemd service
sudo chmod 644 /etc/systemd/system/mdm-flask-api.service
```

## Environment Variables Check

Ensure all these are set in production:
- `DEVICES_JSON_PATH`
- `WEBHOOK_LOG_PATH`
- `NANOMDM_URL`
- `NANOMDM_API_KEY`
- `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `CERTS_DIR`
