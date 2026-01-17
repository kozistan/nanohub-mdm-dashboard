"""
NanoHUB Command Executor
========================
Centralized command execution with sanitization, timeout handling, and logging.

Usage:
    from command_executor import executor

    # Run simple command
    result = executor.run('install_profile', udid, profile_path)

    # Run with custom timeout
    result = executor.run('system_report', udid, timeout=120)

    # Run bulk command on multiple devices
    results = executor.run_bulk('install_profile', devices, profile_path)

    # Send MDM push notification
    executor.send_push(udid)

    # Execute MDM command via API
    result = executor.send_mdm_command(udid, plist_xml)
"""

import os
import re
import subprocess
import logging
import base64
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass

from config import Config

logger = logging.getLogger('nanohub_executor')


@dataclass
class CommandResult:
    """Result of command execution."""
    success: bool
    output: str
    return_code: int
    error: Optional[str] = None
    command_uuid: Optional[str] = None
    device: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'output': self.output,
            'return_code': self.return_code,
            'error': self.error,
            'command_uuid': self.command_uuid,
            'device': self.device
        }


class CommandExecutor:
    """Centralized command executor with sanitization and logging."""

    # Characters to strip from parameters (prevent command injection)
    DANGEROUS_CHARS = ['`', '$', '|', '&', ';', '\n', '\r', '>', '<', '\\', '(', ')', '{', '}']

    def __init__(self):
        self.commands_dir = Config.COMMANDS_DIR
        self.ddm_scripts_dir = Config.DDM_SCRIPTS_DIR
        self.tools_dir = Config.TOOLS_DIR
        self.default_timeout = Config.COMMAND_TIMEOUT
        self.bulk_timeout = Config.COMMAND_TIMEOUT_BULK
        self.bulk_delay = Config.BULK_COMMAND_DELAY

    def sanitize(self, value: Any) -> str:
        """
        Sanitize parameter value to prevent command injection.

        Args:
            value: Value to sanitize

        Returns:
            Sanitized string
        """
        if value is None:
            return ''

        value = str(value).strip()

        for char in self.DANGEROUS_CHARS:
            value = value.replace(char, '')

        return value

    def sanitize_all(self, *values) -> Tuple[str, ...]:
        """Sanitize multiple values."""
        return tuple(self.sanitize(v) for v in values)

    def _get_env(self) -> Dict[str, str]:
        """Get environment for subprocess execution."""
        return Config.get_subprocess_env()

    def _find_script(self, script_name: str, script_dir: str = None) -> Optional[str]:
        """
        Find script path.

        Args:
            script_name: Script name or path
            script_dir: Optional directory override

        Returns:
            Full script path or None if not found
        """
        # If already absolute path
        if os.path.isabs(script_name):
            return script_name if os.path.exists(script_name) else None

        # Check in specified or default directory
        base_dir = script_dir or self.commands_dir
        script_path = os.path.join(base_dir, script_name)

        if os.path.exists(script_path):
            return script_path

        # Check other common directories
        for check_dir in [self.commands_dir, self.ddm_scripts_dir, self.tools_dir]:
            check_path = os.path.join(check_dir, script_name)
            if os.path.exists(check_path):
                return check_path

        return None

    def run(self, script: str, *args, timeout: int = None,
            script_dir: str = None, cwd: str = None) -> CommandResult:
        """
        Execute command script with arguments.

        Args:
            script: Script name or path
            *args: Arguments to pass to script
            timeout: Timeout in seconds (default from config)
            script_dir: Directory containing script
            cwd: Working directory for execution

        Returns:
            CommandResult with success, output, return_code
        """
        script_path = self._find_script(script, script_dir)

        if not script_path:
            return CommandResult(
                success=False,
                output='',
                return_code=-1,
                error=f'Script not found: {script}'
            )

        # Build command with sanitized arguments
        cmd = [script_path] + [self.sanitize(arg) for arg in args if arg]

        timeout = timeout or self.default_timeout
        working_dir = cwd or os.path.dirname(script_path)

        logger.info(f"Executing: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                env=self._get_env()
            )

            output = result.stdout + result.stderr
            success = result.returncode == 0

            # Try to extract command_uuid from output
            command_uuid = self._extract_command_uuid(output)

            return CommandResult(
                success=success,
                output=output,
                return_code=result.returncode,
                command_uuid=command_uuid
            )

        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout}s: {script}")
            return CommandResult(
                success=False,
                output='',
                return_code=-1,
                error=f'Command timed out after {timeout} seconds'
            )

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return CommandResult(
                success=False,
                output='',
                return_code=-1,
                error=str(e)
            )

    def run_bulk(self, script: str, devices: List[str], *args,
                 max_workers: int = 10, timeout: int = None,
                 progress_callback: Callable[[str, CommandResult], None] = None) -> List[CommandResult]:
        """
        Execute command on multiple devices in parallel.

        Args:
            script: Script name or path
            devices: List of device UUIDs
            *args: Additional arguments (device UUID will be first arg)
            max_workers: Maximum parallel workers
            timeout: Timeout per device
            progress_callback: Called with (device, result) after each completion

        Returns:
            List of CommandResult for each device
        """
        results = []
        timeout = timeout or self.default_timeout

        def run_for_device(device: str) -> CommandResult:
            result = self.run(script, device, *args, timeout=timeout)
            result.device = device
            return result

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(run_for_device, d): d for d in devices}

            for future in as_completed(futures):
                device = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = CommandResult(
                        success=False,
                        output='',
                        return_code=-1,
                        error=str(e),
                        device=device
                    )

                results.append(result)

                if progress_callback:
                    progress_callback(device, result)

        return results

    def _extract_command_uuid(self, output: str) -> Optional[str]:
        """Extract command_uuid from script output."""
        # Try JSON format: "command_uuid": "xxx"
        match = re.search(r'"command_uuid"\s*:\s*"([a-f0-9-]+)"', output, re.IGNORECASE)
        if match:
            return match.group(1)

        # Try plain UUID pattern after command_uuid keyword
        match = re.search(
            r'command_uuid["\s:]+([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
            output, re.IGNORECASE
        )
        if match:
            return match.group(1)

        # Try "Command UUID:" format from shell scripts
        match = re.search(
            r'Command\s+UUID:\s*([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
            output, re.IGNORECASE
        )
        if match:
            return match.group(1)

        return None

    # ==========================================================================
    # MDM API METHODS
    # ==========================================================================

    def _get_auth_header(self) -> str:
        """Get Basic auth header for MDM API."""
        credentials = f"{Config.MDM_API_USER}:{Config.MDM_API_KEY}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    def send_push(self, udid: str) -> bool:
        """
        Send APNs push notification to wake up device.

        Args:
            udid: Device UUID

        Returns:
            True if push sent successfully
        """
        url = f"{Config.MDM_PUSH_URL}/{udid}"

        try:
            req = urllib.request.Request(url, method='POST')
            req.add_header('Authorization', self._get_auth_header())

            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info(f"Push sent to {udid}")
                    return True

        except urllib.error.HTTPError as e:
            logger.warning(f"Push failed for {udid}: HTTP {e.code}")
        except Exception as e:
            logger.warning(f"Push failed for {udid}: {e}")

        return False

    def send_mdm_command(self, udid: str, plist_xml: str) -> CommandResult:
        """
        Send MDM command via NanoMDM API.

        Args:
            udid: Device UUID
            plist_xml: Command plist XML

        Returns:
            CommandResult with success status and command_uuid
        """
        url = f"{Config.MDM_ENQUEUE_URL}/{udid}"

        try:
            req = urllib.request.Request(
                url,
                data=plist_xml.encode('utf-8'),
                method='PUT'
            )
            req.add_header('Content-Type', 'application/xml')
            req.add_header('Authorization', self._get_auth_header())

            with urllib.request.urlopen(req, timeout=10) as resp:
                response_body = resp.read().decode('utf-8')

                if resp.status == 200:
                    # Extract command_uuid from response
                    command_uuid = self._extract_command_uuid(response_body)
                    return CommandResult(
                        success=True,
                        output=response_body,
                        return_code=0,
                        command_uuid=command_uuid
                    )
                else:
                    return CommandResult(
                        success=False,
                        output=response_body,
                        return_code=resp.status,
                        error=f'MDM API error: HTTP {resp.status}'
                    )

        except urllib.error.HTTPError as e:
            logger.error(f"MDM API error for {udid}: {e.code} {e.reason}")
            return CommandResult(
                success=False,
                output='',
                return_code=e.code,
                error=f'MDM API error: HTTP {e.code} - Device may not be enrolled'
            )

        except Exception as e:
            logger.error(f"MDM command failed for {udid}: {e}")
            return CommandResult(
                success=False,
                output='',
                return_code=-1,
                error=str(e)
            )

    # ==========================================================================
    # MDM COMMAND BUILDERS
    # ==========================================================================

    def build_device_information_plist(self, command_uuid: str,
                                        queries: List[str] = None) -> str:
        """Build DeviceInformation command plist."""
        default_queries = [
            'UDID', 'DeviceName', 'OSVersion', 'BuildVersion', 'ModelName',
            'Model', 'ProductName', 'SerialNumber', 'DeviceCapacity',
            'AvailableDeviceCapacity', 'BatteryLevel', 'CellularTechnology',
            'IMEI', 'MEID', 'ModemFirmwareVersion', 'IsSupervised',
            'IsDeviceLocatorServiceEnabled', 'IsActivationLockEnabled',
            'IsDoNotDisturbInEffect', 'IsCloudBackupEnabled', 'OSUpdateSettings',
            'LocalHostName', 'HostName', 'SystemIntegrityProtectionEnabled',
            'IsMDMLostModeEnabled', 'WiFiMAC', 'BluetoothMAC', 'EthernetMAC'
        ]

        queries = queries or default_queries
        queries_xml = '\n'.join(f'            <string>{q}</string>' for q in queries)

        return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>DeviceInformation</string>
        <key>Queries</key>
        <array>
{queries_xml}
        </array>
    </dict>
    <key>CommandUUID</key>
    <string>{command_uuid}</string>
</dict>
</plist>'''

    def build_simple_command_plist(self, command_uuid: str, request_type: str) -> str:
        """Build simple MDM command plist (no parameters)."""
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>{request_type}</string>
    </dict>
    <key>CommandUUID</key>
    <string>{command_uuid}</string>
</dict>
</plist>'''

    def build_install_profile_plist(self, command_uuid: str, profile_data: bytes) -> str:
        """Build InstallProfile command plist."""
        encoded_profile = base64.b64encode(profile_data).decode('utf-8')

        return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Command</key>
    <dict>
        <key>RequestType</key>
        <string>InstallProfile</string>
        <key>Payload</key>
        <data>{encoded_profile}</data>
    </dict>
    <key>CommandUUID</key>
    <string>{command_uuid}</string>
</dict>
</plist>'''


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

executor = CommandExecutor()


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def sanitize_param(value: Any) -> str:
    """Sanitize single parameter (backward compatibility)."""
    return executor.sanitize(value)


def run_command(script: str, *args, **kwargs) -> CommandResult:
    """Run command (backward compatibility)."""
    return executor.run(script, *args, **kwargs)
