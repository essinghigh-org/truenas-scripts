#!/usr/bin/env python3
import os
import sys
import json
import socket
import datetime
from truenas_api_client import Client
import re
import time


def log(message: str) -> None:
    timestamp = datetime.datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    print(f"{timestamp} {message}")


def parse_toml(config_path: str) -> dict:
    """Parser for the TOML config file."""
    default_config = {
        "hostname": socket.gethostname(),
        "discord": {"enabled": False, "webhook_url": ""},
        "slack": {"enabled": False, "webhook_url": ""},
        "exclude": {"apps": []},
        "debug": {"enabled": False, "dry_run": False}
    } 
    if not os.path.isfile(config_path):
        return default_config
    config = {
        "discord": {},
        "slack": {},
        "exclude": {},
        "debug": {}
    }
    current_section = None
    with open(config_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            section_match = re.match(r'\[(.*)\]', line)
            if section_match:
                current_section = section_match.group(1)
                continue
            if '=' in line:
                key, value = (item.strip() for item in line.split('=', 1))
                if current_section == "general" and key == "hostname":
                    config["hostname"] = value.strip('"')
                    continue
                if key == "apps" and current_section == "exclude":
                    apps_str = re.sub(r'^\[|\]$', '', value)
                    apps = []
                    in_quotes = False
                    current_app = ""
                    for char in apps_str:
                        if char == '"' and (not current_app.endswith('\\') or not in_quotes):
                            in_quotes = not in_quotes
                            current_app += char
                        elif char == ',' and not in_quotes:
                            apps.append(current_app.strip(' "'))
                            current_app = ""
                        else:
                            current_app += char
                    if current_app:
                        apps.append(current_app.strip(' "'))
                    
                    config["exclude"]["apps"] = apps
                    continue
                if value.lower() in ("true", "false"):
                    parsed_value = (value.lower() == "true")
                else:
                    parsed_value = value.strip('"')
                if current_section in config:
                    config[current_section][key] = parsed_value
    if "hostname" not in config:
        config["hostname"] = socket.gethostname()
    return config


def load_config(script_dir: str) -> dict:
    """Load configuration from JSON or convert from TOML if needed."""
    json_config_path = os.path.join(script_dir, "update_apps.json")
    toml_config_path = os.path.join(script_dir, "update_apps.toml")
    if os.path.isfile(json_config_path):
        try:
            with open(json_config_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            log("Error parsing JSON config file, falling back to default")
    if os.path.isfile(toml_config_path):
        try:
            config = parse_toml(toml_config_path)
            with open(json_config_path, 'w') as f:
                json.dump(config, f, indent=4)
            os.remove(toml_config_path)
            log(f"Converted TOML config to JSON and removed TOML file")
            return config
        except Exception as e:
            log(f"Error converting TOML to JSON: {e}")
    return {
        "hostname": socket.gethostname(),
        "discord": {"enabled": False, "webhook_url": ""},
        "slack": {"enabled": False, "webhook_url": ""},
        "exclude": {"apps": []},
        "debug": {"enabled": False, "dry_run": False}
    }


def send_webhook_notification(webhook_url: str, content: str) -> bool:
    """Send notification to a webhook (Discord or Slack)."""
    if not webhook_url:
        return False
    try:
        import requests
        headers = {'Content-Type': 'application/json'}
        payload = {'content': content}
        response = requests.post(webhook_url, headers=headers, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as error:
        log(f"Webhook notification error: {error}")
        return False


def upgrade_app(app: dict, config: dict, log_content: list, debug_enabled: bool, dry_run: bool, client) -> None:
    """Upgrade a single app if eligible."""
    app_name = app.get("name", "")
    current_version = app.get("version", "")
    excluded_apps = config.get("exclude", {}).get("apps", [])
    if debug_enabled:
        log(f"DEBUG: Checking if app '{app_name}' is in exclude list: {excluded_apps}")
    if app_name in excluded_apps:
        log(f"Skipping excluded app: {app_name}")
        log("-----------------------------------------")
        return
    log(f"Processing: {app_name}")
    if debug_enabled:
        log(f"DEBUG: App {app_name} - current version: {current_version}, has_update: {app.get('upgrade_available', False)}")
    log(f"   - Current version: {current_version}")
    if dry_run:
        log(f"   - Dry-run mode: not upgrading {app_name}")
        new_version = f"{current_version} (dry-run)"
        log_content.append(f"{app_name} | {current_version} → {new_version}")
    else:
        try:
            client.call("app.upgrade", app_name)
        except Exception as e:
            log(f"   - Upgrade failed for {app_name}: {e}")
            log("-----------------------------------------")
            return
        new_version = "unknown"
        max_attempts = 60
        attempts = 0
        while (new_version == "unknown" or new_version == current_version) and attempts < max_attempts:
            try:
                config_data = client.call("app.config", app_name)
                new_version = config_data.get("ix_context", {}).get("app_metadata", {}).get("version", "unknown")
            except Exception as e:
                log(f"   - Error fetching new version for {app_name}: {e}")
                new_version = "unknown"
            if new_version == "unknown" or new_version == current_version:
                time.sleep(5)
                attempts += 1
        log(f"   - New version:    {new_version}")
        log_content.append(f"{app_name} | {current_version} → {new_version}")
    log("-----------------------------------------")


def main() -> int:
    """Main entry point for the update process."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config = load_config(script_dir)
    hostname = config.get("hostname", socket.gethostname())
    debug_enabled = config.get("debug", {}).get("enabled", False)
    dry_run = config.get("debug", {}).get("dry_run", False)
    discord_enabled = config.get("discord", {}).get("enabled", False)
    discord_webhook = config.get("discord", {}).get("webhook_url", "")
    slack_enabled = config.get("slack", {}).get("enabled", False)
    slack_webhook = config.get("slack", {}).get("webhook_url", "")
    excluded_apps = config.get("exclude", {}).get("apps", [])
    if debug_enabled:
        log(f"DEBUG: Config loaded - hostname: {hostname}, discord_enabled: {discord_enabled}, slack_enabled: {slack_enabled}, dry_run: {dry_run}")
        log(f"DEBUG: Excluded apps: {excluded_apps}")
    with Client() as client:
        log("Starting catalog sync...")
        try:
            client.call("catalog.sync")
        except Exception as e:
            log(f"Catalog sync failed: {e}")
        log("-----------------------------------------")
        log("Checking for non-custom apps with available upgrades...")
        try:
            apps_data = client.call("app.query")
        except Exception as e:
            log(f"Failed to query apps: {e}")
            return 1
        upgradable_apps = [
            app for app in apps_data
            if (
                not app.get("custom_app", False)
                and app.get("upgrade_available", False)
                and app.get("state") == "RUNNING"
            )
        ]
        if not upgradable_apps:
            log("No updates available for non-custom applications")
            log("-----------------------------------------")
            return 0
        log("Found updates for the following apps:")
        for app in upgradable_apps:
            log(f"• {app.get('name', '')} (Current: {app.get('version', '')})")
        log("-----------------------------------------")
        total_upgrades = 0
        log_content = []
        for app in upgradable_apps:
            before_count = len(log_content)
            upgrade_app(app, config, log_content, debug_enabled, dry_run, client)
            if len(log_content) > before_count:
                total_upgrades += 1
        log(f"Successfully upgraded {total_upgrades} app(s)")
        if total_upgrades > 0:
            if discord_enabled:
                message = f"[{hostname}] "
                if dry_run:
                    message += f"(Dry Run) Would have upgraded {total_upgrades} app(s):\n" + "\n".join(log_content)
                else:
                    message += f"Successfully upgraded {total_upgrades} app(s):\n" + "\n".join(log_content)
                send_webhook_notification(discord_webhook, message)
            if slack_enabled:
                message = f"[{hostname}] "
                if dry_run:
                    message += f"(Dry Run) Would have upgraded {total_upgrades} app(s):\n" + "\n".join(log_content)
                else:
                    message += f"Successfully upgraded {total_upgrades} app(s):\n" + "\n".join(log_content)
                send_webhook_notification(slack_webhook, message)
        log("Script execution completed")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("Script interrupted by user")
        sys.exit(1)
    except Exception as e:
        log(f"Error: {e}")
        sys.exit(1)
