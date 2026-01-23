# Troubleshooting

Common issues and solutions.

## Service Issues

### Check Service Status

```bash
systemctl status nanohub
systemctl status nanohub-web
systemctl status nanohub-webhook
systemctl status mdm-flask-api
```

### View Logs

```bash
# NanoMDM logs
journalctl -u nanohub -f

# Web frontend logs
journalctl -u nanohub-web -f

# Webhook logs
tail -f /var/log/nanohub/webhook.log

# API logs
journalctl -u mdm-flask-api -f
```

### Restart Services

```bash
sudo systemctl restart nanohub
sudo systemctl restart nanohub-web
sudo systemctl restart nanohub-webhook
```

### Python Template Changes

**IMPORTANT:** Python templates (HTML in `render_template_string()`) are cached by Flask/gunicorn.

After changing any Python file with HTML templates:
```bash
sudo systemctl restart nanohub-web.service
```

Template files location:
- `/opt/nanohub/backend_api/nanohub_admin_core.py` - Dashboard, command, history templates
- `/opt/nanohub/backend_api/nanohub_admin/profiles.py` - Profiles page template
- `/opt/nanohub/backend_api/nanohub_admin/routes/devices.py` - Device list & detail templates
- `/opt/nanohub/backend_api/nanohub_admin/routes/*.py` - Other route-specific templates

## NGINX Static Files

**CRITICAL:** Nginx serves static files from a different path than Flask!

| Component | Static Path |
|-----------|-------------|
| Nginx (production) | `/var/www/mdm-web/static/` |
| Flask (development) | `/opt/nanohub/backend_api/static/` |

### CSS Changes Not Appearing?

If CSS changes don't appear after editing files in `/opt/nanohub/backend_api/static/`:

```bash
# Copy CSS to nginx static folder
sudo cp /opt/nanohub/backend_api/static/css/admin.css /var/www/mdm-web/static/css/admin.css
sudo cp /opt/nanohub/backend_api/static/dashboard.css /var/www/mdm-web/static/dashboard.css
```

### Nginx Configuration

Location: `/etc/nginx/sites-enabled/nanohub.example.com`

Static files have cache headers:
```nginx
expires 1d;
add_header Cache-Control "public, immutable";
```

**Debug tip:** Add `?v=2` to CSS URL to bypass browser cache:
```html
<link href="/static/css/admin.css?v=2" rel="stylesheet">
```

## LDAP Issues

### Test Connection

```bash
cd /opt/nanohub/backend_api
source /opt/nanohub/venv/bin/activate
python3 -c "from nanohub_ldap_auth import test_ldap_connection; test_ldap_connection()"
```

### Common Problems

| Issue | Solution |
|-------|----------|
| Connection timeout | Check LDAP server reachability, firewall |
| Invalid credentials | Verify LDAP_BIND_DN and LDAP_BIND_PASSWORD |
| User not found | Check LDAP_BASE_DN |
| No groups returned | Verify user is member of MDM groups |

### Check User Groups

```bash
# Using ldapsearch
ldapsearch -H ldap://dc01.example.com -D "CN=ldapadmin,OU=Admins,DC=example,DC=com" \
  -W -b "DC=example,DC=com" "(sAMAccountName=username)" memberOf
```

## Database Issues

### Test Connection

```bash
mysql -h localhost -u nanohub -p nanohub -e "SELECT 1"
```

### Check Tables

```bash
mysql -h localhost -u nanohub -p nanohub -e "SHOW TABLES"
```

### Common Problems

| Issue | Solution |
|-------|----------|
| Connection refused | Check MySQL is running |
| Access denied | Verify credentials in config |
| Table doesn't exist | Run schema creation SQL |

### Reset Tables

```sql
-- Recreate device_details
DROP TABLE IF EXISTS device_details;
CREATE TABLE device_details (...);
```

## MDM Command Issues

### Command Not Executing

1. Check device is online (last seen time)
2. Verify device is enrolled in MDM
3. Check NanoMDM service is running
4. Review Command History for errors

### Command Stuck

```sql
-- Check pending commands in NanoMDM
SELECT * FROM command_queue WHERE status = 'pending';
```

### Push Notifications

```bash
# Test APNS connectivity
curl -v https://api.push.apple.com
```

## Webhook Issues

### HMAC Verification Failed

```bash
# Check log for security warnings
grep SECURITY /var/log/nanohub/webhook.log
```

**Causes:**
- Secret mismatch between NanoHUB and webhook
- Wrong header name (should be X-Hmac-Signature)
- Encoding mismatch (should be Base64)

### Webhook Not Receiving

1. Check NanoHUB has `-webhook-url` configured
2. Verify webhook service is running on port 5001
3. Test endpoint: `curl http://localhost:5001/health`

### Database Write Failed

Check webhook log for DB errors:
```bash
grep "DB" /var/log/nanohub/webhook.log | tail -20
```

## Device Issues

### Device Not Appearing

1. Check device is enrolled in MDM
2. Verify device in NanoMDM: `SELECT * FROM devices WHERE ...`
3. Add to device_inventory manually or via API

### Device Offline

1. Check device has internet connection
2. Verify MDM profile installed: `profiles show -type enrollment`
3. Check APNS certificate validity

### Commands Not Working

1. Device must be supervised for some commands
2. Check command compatibility with OS version
3. Review error in Command History

## DDM Issues

### Declarations Not Applying

```bash
# Check declaration status
/opt/nanohub/ddm/scripts/ddm-status.sh device <UDID>
```

### Status Errors

```sql
SELECT * FROM status_errors WHERE enrollment_id = '<UDID>';
```

### Force Resync

```bash
/opt/nanohub/ddm/scripts/ddm-force-sync.sh <UDID>
```

## VPP Issues

### Token Expired

1. Download new token from Apple Business Manager
2. Update `/opt/nanohub/environment.sh`
3. Restart services

### App Not Installing

1. Check license availability
2. Verify device compatibility
3. Check VPP token is valid

### License Count Wrong

```bash
# Refresh from Apple
curl -H "Authorization: Bearer $VPP_TOKEN" \
  https://vpp.itunes.apple.com/mdm/v2/assets
```

## Performance Issues

### Slow Page Load

1. Check database indexes exist
2. Optimize tables: `OPTIMIZE TABLE device_inventory, device_details`
3. Review slow queries in MySQL slow log

### High Memory Usage

1. Check connection pool settings in config.py
2. Restart services to clear memory
3. Review for memory leaks in logs

## Log Files

| Log | Location |
|-----|----------|
| Webhook | `/var/log/nanohub/webhook.log` |
| Audit | `/var/log/nanohub/admin_audit.log` |
| NanoMDM | `journalctl -u nanohub` |
| Web | `journalctl -u nanohub-web` |
| API | `journalctl -u mdm-flask-api` |
