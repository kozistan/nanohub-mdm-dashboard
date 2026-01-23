"""
NanoHUB Webhook Poller
======================
Centralized webhook log polling and parsing.
Monitors /var/log/nanohub/webhook.log for MDM command responses.

Usage:
    from webhook_poller import poller

    # Poll for command result
    result = poller.poll_for_command(command_uuid)

    # Poll with custom timeout
    result = poller.poll_for_command(command_uuid, timeout=30, poll_interval=2)

    # Parse specific response types
    hardware_info = poller.parse_device_info(raw_block)
    profiles = poller.parse_profile_list(raw_block)
"""

import re
import ast
import time
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from config import Config

logger = logging.getLogger('nanohub_webhook')


@dataclass
class WebhookResponse:
    """Parsed webhook response."""
    success: bool
    command_uuid: Optional[str] = None
    status: Optional[str] = None
    udid: Optional[str] = None
    topic: Optional[str] = None
    request_type: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    raw: str = ''
    error: Optional[str] = None
    not_now: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'command_uuid': self.command_uuid,
            'status': self.status,
            'udid': self.udid,
            'topic': self.topic,
            'request_type': self.request_type,
            'data': self.data,
            'raw': self.raw,
            'error': self.error,
            'not_now': self.not_now
        }


class WebhookPoller:
    """Webhook log poller and parser."""

    def __init__(self):
        self.log_path = Config.WEBHOOK_LOG_PATH
        self.default_initial_sleep = Config.WEBHOOK_POLL_INITIAL_SLEEP
        self.default_max_attempts = Config.WEBHOOK_POLL_MAX_ATTEMPTS
        self.default_poll_interval = Config.WEBHOOK_POLL_INTERVAL
        self.default_window = Config.WEBHOOK_POLL_WINDOW

    def poll_for_command(self, command_uuid: str,
                         initial_sleep: int = None,
                         max_attempts: int = None,
                         poll_interval: int = None,
                         window: int = None,
                         timeout: int = None) -> Optional[WebhookResponse]:
        """
        Poll webhook log for command result.

        Args:
            command_uuid: UUID of command to look for
            initial_sleep: Seconds to wait before first poll
            max_attempts: Maximum poll attempts
            poll_interval: Seconds between polls
            window: Number of lines to read from end of log
            timeout: Total timeout (alternative to max_attempts)

        Returns:
            WebhookResponse if found, None if timeout
        """
        if not command_uuid:
            return None

        initial_sleep = initial_sleep or self.default_initial_sleep
        max_attempts = max_attempts or self.default_max_attempts
        poll_interval = poll_interval or self.default_poll_interval
        window = window or self.default_window

        # If timeout specified, calculate max_attempts
        if timeout:
            max_attempts = timeout // poll_interval

        logger.info(f"Polling for command_uuid: {command_uuid}")

        time.sleep(initial_sleep)

        for attempt in range(max_attempts):
            try:
                response = self._check_log_for_command(command_uuid, window)

                if response:
                    if response.not_now:
                        logger.info(f"Device returned NotNow, attempt {attempt + 1}/{max_attempts}")
                        time.sleep(poll_interval * 2)  # Wait longer for NotNow
                        continue
                    return response

            except Exception as e:
                logger.warning(f"Error polling webhook: {e}")

            time.sleep(poll_interval)

        logger.warning(f"Polling timeout for command_uuid: {command_uuid}")
        return None

    def _check_log_for_command(self, command_uuid: str, window: int) -> Optional[WebhookResponse]:
        """Check log file for command UUID."""
        try:
            with open(self.log_path, 'r') as f:
                lines = f.readlines()[-window:]
        except FileNotFoundError:
            logger.error(f"Webhook log not found: {self.log_path}")
            return None

        # Parse log into blocks separated by "=== MDM Event ==="
        blocks = self._parse_blocks(lines)

        # Search from newest to oldest for matching command_uuid
        for block in reversed(blocks):
            block_text = ''.join(block)

            if f'command_uuid: {command_uuid}' in block_text.lower():
                return self._parse_block(block, command_uuid)

        return None

    def _parse_blocks(self, lines: List[str]) -> List[List[str]]:
        """Split log lines into MDM event blocks."""
        blocks = []
        current_block = []

        for line in lines:
            if '=== MDM Event ===' in line:
                if current_block:
                    blocks.append(current_block)
                current_block = [line]
            else:
                current_block.append(line)

        if current_block:
            blocks.append(current_block)

        return blocks

    def _parse_block(self, block: List[str], command_uuid: str) -> WebhookResponse:
        """Parse a single MDM event block."""
        response = WebhookResponse(
            success=True,
            command_uuid=command_uuid,
            raw=''.join(block)
        )

        parsed_data = {}

        for line in block:
            line = line.strip()

            # Skip empty lines
            if not line:
                continue

            # Check for NotNow status
            if 'Status: NotNow' in line:
                response.not_now = True
                response.success = False
                return response

            # Check for error status
            if 'Status: Error' in line:
                response.success = False

            # Extract key-value pairs from [INFO] lines
            if '[INFO]' in line:
                content = line.split('[INFO]', 1)[1].strip()

                # Skip delimiters
                if content.startswith('==='):
                    continue

                # Parse key: value
                if ':' in content:
                    key, _, value = content.partition(':')
                    key = key.strip()
                    value = value.strip()

                    if key and value:
                        # Special handling for known fields
                        if key.lower() == 'status':
                            response.status = value
                        elif key.lower() == 'udid':
                            response.udid = value
                        elif key.lower() == 'topic':
                            response.topic = value
                        elif key.lower() == 'requesttype':
                            response.request_type = value
                        elif key.lower() != 'command_uuid':
                            # Add to data dict
                            parsed_data[key] = self._parse_value(value)

        response.data = parsed_data
        return response

    def _parse_value(self, value: str) -> Any:
        """Parse string value to appropriate type."""
        # Boolean
        if value.lower() in ['true', 'yes', '1']:
            return True
        if value.lower() in ['false', 'no', '0']:
            return False

        # Dict-like value
        if value.startswith('{') and value.endswith('}'):
            try:
                # Handle datetime.datetime(...) in value
                clean_value = re.sub(
                    r'datetime\.datetime\((\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)',
                    r'"\1-\2-\3 \4:\5:\6"',
                    value
                )
                return ast.literal_eval(clean_value)
            except (ValueError, SyntaxError):
                pass

        # Number
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass

        return value

    # ==========================================================================
    # SPECIALIZED PARSERS
    # ==========================================================================

    def parse_device_info(self, response: WebhookResponse) -> Dict[str, Any]:
        """
        Parse DeviceInformation response.

        Args:
            response: WebhookResponse from poll

        Returns:
            Dict with device information fields
        """
        return response.data if response else {}

    def parse_security_info(self, response: WebhookResponse) -> Dict[str, Any]:
        """
        Parse SecurityInfo response.

        Args:
            response: WebhookResponse from poll

        Returns:
            Dict with security information
        """
        return response.data if response else {}

    def parse_profile_list(self, response: WebhookResponse) -> List[Dict[str, str]]:
        """
        Parse ProfileList response from raw log lines.

        Args:
            response: WebhookResponse from poll

        Returns:
            List of profile dicts with identifier, name, status
        """
        if not response or not response.raw:
            return []

        profiles = []

        for line in response.raw.split('\n'):
            # Match: [0] com.identifier (Name) — Status
            match = re.search(r'\[(\d+)\]\s+(\S+)\s+\(([^)]+)\)\s*[—-]?\s*(\w+)?', line)
            if match:
                profiles.append({
                    'index': int(match.group(1)),
                    'identifier': match.group(2),
                    'name': match.group(3),
                    'status': match.group(4) or 'Unknown'
                })

        return profiles

    def parse_application_list(self, response: WebhookResponse) -> List[Dict[str, Any]]:
        """
        Parse InstalledApplicationList response from raw log lines.

        Args:
            response: WebhookResponse from poll

        Returns:
            List of app dicts with name, bundle_id, version
        """
        if not response or not response.raw:
            return []

        apps = []

        for line in response.raw.split('\n'):
            # Match: [0] AppName (com.bundle.id) v1.0
            match = re.search(r'\[(\d+)\]\s+(.+?)\s+\(([^)]+)\)\s+v?([\d.]+)?', line)
            if match:
                apps.append({
                    'index': int(match.group(1)),
                    'name': match.group(2).strip(),
                    'bundle_id': match.group(3),
                    'version': match.group(4) or '-'
                })

        return apps

    def parse_certificate_list(self, response: WebhookResponse) -> List[Dict[str, Any]]:
        """
        Parse CertificateList response.

        Args:
            response: WebhookResponse from poll

        Returns:
            List of certificate dicts
        """
        if not response or not response.raw:
            return []

        certs = []

        for line in response.raw.split('\n'):
            # Match: [0] CN: CommonName [ROOT]
            match = re.search(r'\[(\d+)\]\s+CN:\s+(.+?)(?:\s+\[ROOT\])?$', line)
            if match:
                certs.append({
                    'index': int(match.group(1)),
                    'common_name': match.group(2).strip(),
                    'is_root': '[ROOT]' in line
                })

        return certs

    # ==========================================================================
    # HIGH-LEVEL QUERY METHODS
    # ==========================================================================

    def query_device(self, udid: str, query_type: str,
                     send_command_func: callable,
                     max_retries: int = 3) -> WebhookResponse:
        """
        Execute MDM query and poll for response with retry logic.

        Args:
            udid: Device UUID
            query_type: One of 'hardware', 'security', 'profiles', 'apps'
            send_command_func: Function to call to send MDM command
                               (should return command_uuid)
            max_retries: Number of retry attempts for NotNow responses

        Returns:
            WebhookResponse with parsed data
        """
        import uuid

        request_types = {
            'hardware': 'DeviceInformation',
            'security': 'SecurityInfo',
            'profiles': 'ProfileList',
            'apps': 'InstalledApplicationList'
        }

        if query_type not in request_types:
            return WebhookResponse(
                success=False,
                error=f'Unknown query type: {query_type}'
            )

        for attempt in range(max_retries):
            command_uuid = str(uuid.uuid4())

            # Send the command (caller provides the function)
            if not send_command_func(udid, query_type, command_uuid):
                return WebhookResponse(
                    success=False,
                    error='Failed to send MDM command'
                )

            # Poll for response
            response = self.poll_for_command(
                command_uuid,
                initial_sleep=3 if attempt == 0 else 1,
                max_attempts=15
            )

            if response:
                if response.not_now and attempt < max_retries - 1:
                    logger.info(f"Device {udid} returned NotNow, retry {attempt + 1}")
                    time.sleep(2)
                    continue
                return response

        return WebhookResponse(
            success=False,
            error='Device not responding. It may be offline or sleeping.'
        )


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

poller = WebhookPoller()


# =============================================================================
# CONVENIENCE FUNCTIONS (backward compatibility)
# =============================================================================

def poll_webhook_for_command(command_uuid: str, initial_sleep: int = 3,
                             max_polls: int = 15, poll_wait: int = 1,
                             window: int = 1000) -> Optional[Dict]:
    """
    Poll webhook for command result (backward compatibility).

    Returns dict in legacy format with 'raw' and 'parsed' keys.
    """
    response = poller.poll_for_command(
        command_uuid,
        initial_sleep=initial_sleep,
        max_attempts=max_polls,
        poll_interval=poll_wait,
        window=window
    )

    if not response:
        return None

    return {
        'raw': response.raw,
        'parsed': response.data
    }


def format_webhook_block(block: List[str]) -> Dict:
    """Format webhook block (backward compatibility)."""
    # This is now handled internally by WebhookPoller
    raw = ''.join(block)
    parsed = {}

    for line in block:
        line = line.strip()
        if '[INFO]' in line:
            content = line.split('[INFO]', 1)[1].strip()
            if ':' in content and not content.startswith('==='):
                key, _, value = content.partition(':')
                key = key.strip()
                value = value.strip()
                if key and value:
                    parsed[key] = value

    return {'raw': raw, 'parsed': parsed}
