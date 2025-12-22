import argparse
import os
from datetime import datetime
from typing import Any, cast
from truenas_api_client import Client
import urllib3
import requests

def generate_backup_filename(hostname: str, truenas_version: str, timestamp: str) -> str:
    """
    Generate the filename for the backup based on the hostname, 
    TrueNAS version, and timestamp.
    """
    return f"{hostname}-{truenas_version}-{timestamp}.tar"

def download_backup_file(download_url: str, output_file: str) -> None:
    """
    Download the backup file from the provided URL and save it to the 
    specified output file.
    """
    try:
        response = requests.get(download_url, verify=False, stream=True, timeout=10)
        response.raise_for_status()
        with open(output_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except requests.exceptions.Timeout:
        print("Timeout occurred while downloading the backup file.")
    except Exception as e:
        print(f"An error occurred: {e}")

def main() -> None:
    """
    Main function to handle the backup process.
    """
    # Disable insecure request warnings
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Automated TrueNAS configuration backup utility.")
    parser.add_argument("--output-dir", required=True, help="Directory to save the backup file.")
    args = parser.parse_args()

    # Generate token and get UI port
    with Client() as c:
        token = cast(str, c.call("auth.generate_token", 30, {}, False, True))  # pyright: ignore[reportUnknownMemberType]
        ui_port = cast(int, cast(dict[str, Any], c.call("system.general.config"))["ui_httpsport"])  # pyright: ignore[reportUnknownMemberType]

    # Login with token and download configuration
    with Client(uri=f"wss://localhost:{ui_port}/api/current", verify_ssl=False) as c:
        result = cast(Any, c.call("auth.login_with_token", token))  # pyright: ignore[reportUnknownMemberType]
        print("Login result:", result)

        try:
            # Read TrueNAS version and hostname
            with open('/etc/version', 'r', encoding='utf-8') as f:
                truenas_version = f.read().strip()
            with open('/etc/hostname', 'r', encoding='utf-8') as f:
                hostname = f.read().strip()
        except Exception as e:
            print(f"Error reading TrueNAS version or hostname: {e}")
            truenas_version = "unknown"
            hostname = "unknown"

        # Generate timestamp and backup filename
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_filename = generate_backup_filename(hostname, truenas_version, timestamp)

        # Download configuration
        config_result = cast(list[Any], c.call("core.download", "config.save", [{"secretseed": True, "root_authorized_keys": True}], backup_filename))  # pyright: ignore[reportUnknownMemberType]
        download_path = cast(str, config_result[1])
        download_url = f"https://localhost:{ui_port}{download_path}"

        # Save backup file
        output_file = os.path.join(args.output_dir, backup_filename)
        download_backup_file(download_url, output_file)
        print(f"Download successful. File saved to: {output_file}")

if __name__ == "__main__":
    main()
