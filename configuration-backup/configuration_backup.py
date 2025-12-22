import argparse
import subprocess
import json
import requests
import os
import sys
import datetime
import re
from typing import Any

"""
Automated TrueNAS configuration backup utility.
Handles config backup creation via midclt API calls and file download.
Maintains versioned backups with timestamp and system version metadata.
"""

def check_version_compatibility() -> str:
    """Check if the TrueNAS version is compatible with this script.
    
    Versions above Electric Eel (25.04.0) need to use the websocket variant.
    
    Returns:
        str: The detected TrueNAS version string
        
    Raises:
        SystemExit: If version is above 25.04.0 (Fangtooth)
    """
    try:
        with open('/etc/version', 'r') as f:
            full_version = f.read().strip()
            
        # Extract the base version (e.g., 25.04.0)
        version_match = re.match(r'(\d+\.\d+\.\d+)', full_version)
        if version_match:
            base_version = version_match.group(1)
        else:
            base_version = full_version
            
        version_parts = [int(part) for part in base_version.split('.')]
        if len(version_parts) >= 2 and (
            version_parts[0] > 24 or 
            (version_parts[0] == 24 and version_parts[1] >= 10)
        ):
            print("WARNING: This script is unsupported on versions above Electric Eel.")
            print("Please use the websocket variant of the script found here:")
            print("https://github.com/essinghigh/truenas-scripts/tree/main/configuration-backup")
            sys.exit(1)
            
        return full_version
    except Exception as e:
        print(f"Error reading TrueNAS version: {e}")
        return "unknown"

def midclt_runner(call_args: list[str]) -> Any:
    """Execute midclt command and handle errors.
    
    Args:
        call_args (list): midclt command arguments as list
        
    Returns:
        dict: Parsed JSON response from midclt
        
    Raises:
        SystemExit: On command failure or JSON decode error
    """
    try:
        result = subprocess.check_output(call_args, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print("Error executing command: {}".format(' '.join(call_args)))
        print("Output:", e.output.decode())
        sys.exit(1)
    
    try:
        return json.loads(result)
    except json.JSONDecodeError as e:
        print("JSON decode error. Output was:")
        print(result.decode())
        sys.exit(1)

def main() -> None:
    """Main backup execution flow.
    
    1. Parse command line arguments
    2. Get system version info
    3. Generate backup filename with metadata
    4. Initiate config backup via midclt API
    5. Retrieve download URL from response
    6. Download and save backup file
    """
    # Check TrueNAS version compatibility first
    truenas_version = check_version_compatibility()
    
    parser = argparse.ArgumentParser(description="Automagically backup TrueNAS config file using midclt.")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to save the backup file. Will be created if it does not exist."
    )
    args = parser.parse_args()
    
    # We already have the TrueNAS version from the compatibility check
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    backup_filename = f"truenas-{truenas_version}-{timestamp}.tar"  # Format: truenas-<version>-<timestamp>.tar
    
    midclt_download_cmd = [
        "midclt", "call", "core.download",
        "config.save",
        '[{"secretseed": true, "root_authorized_keys": true}]',
        backup_filename
    ]
    print("Requesting download via midclt ...")
    download_json = midclt_runner(midclt_download_cmd)
    try:
        download_id = download_json[0]
        download_path = download_json[1]
    except (IndexError, KeyError):
        print("Unexpected response from midclt call: ", download_json)
        sys.exit(1)
    print("Download response received:")
    print("ID:", download_id)
    print("Path:", download_path)
    print("Retrieving UI port ...")
    general_config_cmd = ["midclt", "call", "system.general.config"]
    system_config = midclt_runner(general_config_cmd)
    ui_port = system_config.get("ui_port")
    if ui_port is None:
        print("Could not retrieve ui_port from system.general.config: ", system_config)
        sys.exit(1)
    print("UI port:", ui_port)
    download_url = f"http://localhost:{ui_port}{download_path}"
    print("Download URL:", download_url)
    
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    print("Downloading file ...")
    try:
        response = requests.get(download_url, verify=False, stream=True)
        response.raise_for_status()
        
        filename = backup_filename
        output_file = os.path.join(output_dir, filename)
        
        with open(output_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"Download successful. File saved to: {output_file}")
    except requests.RequestException as e:
        print("Error downloading file:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
