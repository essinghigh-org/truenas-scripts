#!/usr/bin/env python3
"""
TrueNAS Crontab Restore Script

This script creates a post-init task to restore a crontab backup file.
It can also create a backup of the current crontab configuration.
"""

import argparse
import os
import subprocess
import sys
from typing import Any, cast
from truenas_api_client import Client
import urllib3


def validate_backup_path(backup_path: str) -> str:
    """
    Validate the backup file path and check if it exists.
    Warn if the path is not in /mnt as it should be stored on a ZFS storage pool.
    """
    if not os.path.exists(os.path.dirname(backup_path)):
        print(f"Error: Directory {os.path.dirname(backup_path)} does not exist")
        sys.exit(1)
    
    if not backup_path.startswith(('/mnt', '/home', '/root')):
        print(f"Error: Backup path must start with /mnt, /home, or /root")
        sys.exit(1)
    
    if not backup_path.startswith('/mnt'):
        print("Warning: It is recommended to store crontab backups on a ZFS storage pool (/mnt)")
    
    return os.path.abspath(backup_path)


def backup_current_crontab(backup_path: str) -> None:
    """
    Create a backup of the current crontab configuration.
    """
    try:
        result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Warning: Could not read current crontab. It might be empty. {result.stderr}")
            # Create an empty file as backup
            with open(backup_path, 'w') as f:
                pass
            return
        
        with open(backup_path, 'w') as f:
            f.write(result.stdout)
        
        print(f"Current crontab configuration backed up to {backup_path}")
    except Exception as e:
        print(f"Error backing up crontab: {e}")
        sys.exit(1)


def check_and_create_init_script(backup_path: str, no_confirm: bool = False) -> None:
    """
    Check if the crontab restore command already exists as an init script.
    If not, create a new init script to restore the crontab.
    
    Args:
        backup_path: Path to the crontab backup file
        no_confirm: If True, automatically update existing init scripts without confirmation
    """
    # Disable insecure request warnings
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        with Client() as client:
            # Query existing init scripts
            init_scripts = cast(list[dict[str, Any]], client.call('initshutdownscript.query'))  # pyright: ignore[reportUnknownMemberType]
            
            # Check if crontab restore command already exists
            for script in init_scripts:
                if script['type'] == 'COMMAND' and cast(str, script['command']).startswith('crontab '):
                    restore_path = cast(str, script['command']).split(' ')[1]
                    
                    if restore_path == backup_path:
                        print(f"Crontab restore command already exists (ID: {script['id']})")
                        return
                    else:
                        print(f"A different crontab restore command exists (ID: {script['id']}, path: {restore_path})")
                        
                        if no_confirm:
                            answer = 'y'
                        else:
                            answer = input("Do you want to update it? (y/n): ")
                        
                        if answer.lower() == 'y':
                            client.call('initshutdownscript.update', script['id'], {  # pyright: ignore[reportUnknownMemberType]
                                'command': f"crontab {backup_path}",
                                'comment': f"Restore crontab from {backup_path}"
                            })
                            print(f"Updated init script (ID: {script['id']}) to restore crontab from {backup_path}")
                        else:
                            print("Keeping existing init script unchanged")
                        return
            
            # Create new init script only if no existing crontab restore command was found
            params: dict[str, Any] = {
                'type': 'COMMAND',
                'command': f"crontab {backup_path}",
                'when': 'POSTINIT',
                'enabled': True,
                'timeout': 10,
                'comment': f"Restore crontab from {backup_path}"
            }
            
            result = cast(dict[str, Any], client.call('initshutdownscript.create', params))  # pyright: ignore[reportUnknownMemberType]
            print(f"Created new init script (ID: {result['id']}) to restore crontab from {backup_path}")
            
    except Exception as e:
        print(f"Error managing init script: {e}")
        sys.exit(1)


def main() -> None:
    """
    Main function to handle the crontab backup and restoration setup.
    """
    parser = argparse.ArgumentParser(description="TrueNAS crontab backup and restoration setup.")
    parser.add_argument("--crontab-backup-file", required=True, 
                        help="Path to crontab backup file (e.g., /mnt/tank/dataset/crontab.bak")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Automatically update existing init scripts without confirmation (if needed)")
    
    args = parser.parse_args()
    
    # Validate backup path
    backup_path = validate_backup_path(args.crontab_backup_file)
    
    # Backup current crontab
    backup_current_crontab(backup_path)
    
    # Check and create init script
    check_and_create_init_script(backup_path, args.no_confirm)
    
    print("Done!")


if __name__ == "__main__":
    main()
