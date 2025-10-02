# NanoHUB MDM Dashboard

Web-based management dashboard for Apple MDM (Mobile Device Management) using NanoHUB backend.

## Features

- **Device Management**: Search devices by UUID, serial number, or hostname
- **Real-time Device Info**: Query device information, OS version, serial numbers
- **MDM Analyzer**: Comprehensive device activity analysis from MDM database
- **OS Updates**: Check available OS updates for devices
- **Profile Management**: List installed configuration profiles
- **Application Inventory**: View installed applications on devices
- **Wake Device**: Remote wake sleeping Mac devices using pmset schedule
- **DEP Integration**: Display DEP server information
- **Certificate Monitoring**: Track certificate expiration dates

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Web Frontend   │────────▶│  Flask API       │────────▶│   NanoHUB       │
│  (HTML/CSS/JS)  │         │  (Python)        │         │   Backend       │
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                     │
                                     ├──────────▶ MySQL Database
                                     │
                                     ├──────────▶ Webhook Log Parser
                                     │
                                     └──────────▶ Custom Agent (mdmagent)
```

## Prerequisites

- Python 3.8+
- NanoHUB server (running)
- MySQL/MariaDB database
- Nginx or Apache (for web frontend)
- systemd (for service management)
- **mdmagent**: Custom agent running on managed macOS devices ([mdmagent repo](https://github.com/kozistan/mdmagent-micromdm))

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/nanohub-mdm-dashboard.git
cd nanohub-mdm-dashboard
```

### 2. Backend Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp opt/nanohub/backend_api/mdm_flask_api_environment.example opt/nanohub/backend_api/mdm_flask_api_environment

# Edit configuration
nano opt/nanohub/backend_api/mdm_flask_api_environment
```

### 3. Configure Paths

Edit `opt/nanohub/backend_api/mdm-flask-api_wrappper.py`:

```python
DEVICES_JSON_PATH = "/opt/nanohub/data/devices.json"
WEBHOOK_LOG_PATH = "/var/log/nanohub/webhook.log"
```

### 4. Configure Command Scripts

Edit authentication in command scripts:
- `opt/nanohub/tools/api/commands/device_information`
- `opt/nanohub/tools/api/commands/available_os_updates`
- `opt/nanohub/tools/api/commands/installed_application_list`
- `opt/nanohub/tools/api/commands/profile_list`

Replace NanoHUB credentials:
```bash
-u "nanohub:YOUR_API_KEY_HERE"
"http://localhost:9004/api/v1/nanomdm/enqueue/$UDID"
```

### 5. Configure MDM Analyzer

Edit `opt/nanohub/tools/api/commands/mdm_analyzer`:

```bash
DB_HOST="your_mysql_host"
DB_USER="your_db_user"
DB_PASS="your_db_password"
DB_NAME="your_db_name"
```

### 6. Install Files

```bash
# Backend API
sudo mkdir -p /opt/nanohub/backend_api
sudo cp opt/nanohub/backend_api/* /opt/nanohub/backend_api/

# Command scripts
sudo mkdir -p /opt/nanohub/tools/api/commands
sudo cp opt/nanohub/tools/api/commands/* /opt/nanohub/tools/api/commands/
sudo chmod +x /opt/nanohub/tools/api/commands/*

# Web frontend
sudo mkdir -p /var/www/mdm-web/static
sudo cp var/www/mdm-web/index.html /var/www/mdm-web/
sudo cp var/www/mdm-web/static/dashboard.css /var/www/mdm-web/static/

# Systemd service
sudo cp etc/systemd/system/mdm-flask-api.service /etc/systemd/system/
sudo nano /etc/systemd/system/mdm-flask-api.service  # Edit paths
```

### 7. Configure Nginx

Copy the example nginx configuration:

```bash
sudo cp etc/nginx/nginx.conf.example /etc/nginx/sites-available/nanohub-mdm
sudo ln -s /etc/nginx/sites-available/nanohub-mdm /etc/nginx/sites-enabled/
```

Edit the configuration:

```bash
sudo nano /etc/nginx/sites-enabled/nanohub-mdm
```

Update these settings:
- `server_name` - your domain or IP
- `listen` - port (default 80, or 8000 for non-privileged)

Test and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

The configuration includes:
- Flask backend proxy (port 9006) for all `/api/*` endpoints
- Static file serving with caching
- Security headers
- Direct file access for `devices.json`
- Logging configuration

### 8. Start Services

```bash
# Enable and start Flask API
sudo systemctl daemon-reload
sudo systemctl enable mdm-flask-api
sudo systemctl start mdm-flask-api

# Check status
sudo systemctl status mdm-flask-api

# Restart Nginx
sudo systemctl restart nginx
```

## Configuration

### Environment Variables

Edit `/opt/nanohub/backend_api/mdm_flask_api_environment`:

```bash
# Database Configuration
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="nanohub"
DB_PASSWORD="your_password"
DB_NAME="nanohub_mdm"

# NanoHUB Configuration
NANOMDM_URL="http://localhost:9004"
NANOMDM_API_KEY="your_api_key"

# Paths
WEBHOOK_LOG_PATH="/var/log/nanohub/webhook.log"
DEVICES_JSON_PATH="/opt/nanohub/data/devices.json"
CERTS_DIR="/opt/nanohub/certs"
```

### Custom Error Messages

Edit error messages in `index.html`, section `ERROR_MESSAGES`:

```javascript
const ERROR_MESSAGES = {
  device_search_empty: "Your custom message",
  device_info_error: "Your custom message",
  // ...
};
```

## Usage

1. Access dashboard: `http://mdm.yourdomain.com`
2. Enter device hostname, serial, or UUID in search field
3. Use function buttons to query device information

### Wake Device Function

The Wake Device feature remotely wakes sleeping Mac devices using the `pmset schedule wake` command.

**Requirements:**
- **mdmagent** must be installed and running on target devices
- Agent repository: https://github.com/kozistan/mdmagent-micromdm
- Agent polls for commands every 5 seconds
- Commands delivered via HTTP to `repo.sloto.space/commands/{UUID}.json`

**How it works:**
1. Dashboard sends wake command via `send_command` script
2. Command uploaded to HTTP repository as JSON
3. mdmagent on device polls repository every 5 seconds
4. Agent executes `pmset schedule wake` command
5. Device wakes after ~30 seconds
6. Agent reports result to webhook
7. Dashboard displays execution status

**Usage:**
```bash
# Manual command execution
/opt/nanohub/tools/api/commands/send_command <UUID> shell "pmset schedule wake 'MM/DD/YY HH:MM:SS'"

# Via dashboard
1. Enter device hostname/serial/UUID
2. Click "Wake Device" button
3. Wait ~30 seconds for response
```

**Timing:**
- Initial wait: 15 seconds (for command delivery)
- Device wake: ~10 seconds
- Response polling: 5 seconds
- Total: ~30 seconds

**Monitoring:**
```bash
# On managed device
tail -f /var/log/mdmagent.log

# On NanoHUB server
tail -f /var/log/nanohub/webhook.log
```

### API Endpoints

- `GET /api/dep-account-detail` - DEP server information
- `GET /api/cfg-get-cert` - Certificate expiry dates
- `POST /api/device-search` - Search device by field
- `GET /api/devices.json` - List all devices
- `GET /api/mdm-analyzer` - Device activity analysis
- `POST /api/device-info` - Query device information
- `POST /api/os-updates` - Check available OS updates
- `POST /api/profile-list` - List installed profiles
- `POST /api/installed-apps` - List installed applications
- `POST /api/wake-device` - Remote wake device (requires mdmagent)

## Troubleshooting

### Backend not responding

```bash
# Check service status
sudo systemctl status mdm-flask-api

# View logs
sudo journalctl -u mdm-flask-api -f

# Check Flask process
ps aux | grep mdm-flask-api
```

### Frontend errors

Check browser console (F12) for JavaScript errors.

### Database connection issues

```bash
# Test MySQL connection
mysql -h DB_HOST -u DB_USER -p DB_NAME

# Check database permissions
SHOW GRANTS FOR 'DB_USER'@'%';
```

### Webhook polling issues

```bash
# Check webhook log exists and is readable
ls -la /var/log/nanohub/webhook.log

# Monitor webhook in real-time
tail -f /var/log/nanohub/webhook.log
```

### Wake Device not working

```bash
# Check mdmagent is running on device
ssh user@device "launchctl list | grep mdmagent"

# Check agent log on device
ssh user@device "tail -f /var/log/mdmagent.log"

# Verify command delivery
curl -u 'munkirepo:password' https://repo.sloto.space/commands/{UUID}.json

# Test manual wake command
/opt/nanohub/tools/api/commands/send_command {UUID} shell "pmset schedule wake '10/02/25 14:30:00'"

# Check webhook for response
grep "COMMAND RESULT" /var/log/nanohub/webhook.log | tail -5
```

### Common Wake Device issues

1. **Device not responding**
   - Verify mdmagent is installed and running
   - Check network connectivity
   - Verify UUID is correct

2. **Command not executed**
   - Check command file permissions on repo server
   - Verify agent can access HTTP repository
   - Check for firewall blocking agent

3. **Timeout errors**
   - Device may be offline or sleeping
   - Network latency issues
   - Agent polling interval misconfigured

## Security Considerations

- **Production deployment**: Use HTTPS with valid SSL certificate
- **Authentication**: Add authentication layer (nginx basic auth, OAuth, etc.)
- **Credentials**: Store credentials in environment file with restricted permissions
- **Firewall**: Restrict Flask API to localhost only
- **Database**: Use read-only database user for analyzer queries
- **Agent security**: Secure HTTP repository with authentication
- **Command validation**: Validate commands before execution on devices

## Development

### Running in development mode

```bash
cd /opt/nanohub/backend_api
source venv/bin/activate
python3 mdm-flask-api_wrappper.py
```

### Testing API endpoints

```bash
# Test device search
curl -X POST http://localhost:9006/api/device-search \
  -H "Content-Type: application/json" \
  -d '{"field":"hostname","value":"test-device"}'

# Test device info
curl -X POST http://localhost:9006/api/device-info \
  -H "Content-Type: application/json" \
  -d '{"type":"uuid","value":"12345678-1234-1234-1234-123456789012"}'

# Test wake device
curl -X POST http://localhost:9006/api/wake-device \
  -H "Content-Type: application/json" \
  -d '{"udid":"12345678-1234-1234-1234-123456789012"}'
```

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## License

MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Acknowledgments

- Built for NanoHUB by micromdm
- Uses Flask web framework
- Frontend with vanilla JavaScript (no frameworks)
- mdmagent custom agent for advanced device management