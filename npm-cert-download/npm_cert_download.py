import requests
import re
import zipfile
import io
from OpenSSL import crypto
import os
import argparse

DEFAULT_NPM_MGMT_ENDPOINT = os.getenv('NPM_MGMT_ENDPOINT')
DEFAULT_USERNAME = os.getenv('NPM_USERNAME')
DEFAULT_PASSWORD = os.getenv('NPM_PASSWORD')

# Global variables initialized in main()
npm_mgmt_endpoint: str | None = None
username: str | None = None
password: str | None = None
cert_file: str | None = None
key_file: str | None = None
cert_id: int | None = None

def get_bearer_token(username: str, password: str) -> str:
    url = f'{npm_mgmt_endpoint}/api/tokens'
    data = {
        'identity': username,
        'secret': password
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        token: str | None = response.json().get('token')
        if token is None:
            raise Exception("Token not found in response")
        return token
    else:
        raise Exception(f"Failed to authenticate: {response.text}")

def download_certificate(token: str, cert_id: int) -> bytes:
    url = f'{npm_mgmt_endpoint}/api/nginx/certificates/{cert_id}/download'
    headers = {
        'Authorization': f'Bearer {token}'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.content
    else:
        raise Exception(f"Failed to download certificate: {response.text}")

def read_certificates(zip_content: bytes) -> tuple[bytes, bytes, str]:
    with zipfile.ZipFile(io.BytesIO(zip_content)) as z:
        cert_filename = None
        key_filename = None
        for filename in z.namelist():
            if re.match(r'fullchain\d+\.pem', filename):
                cert_filename = filename
            elif re.match(r'privkey\d+\.pem', filename):
                key_filename = filename
        if cert_filename is None:
            raise Exception("No certificate file found matching the pattern 'fullchain\\d+\\.pem'.")
        if key_filename is None:
            raise Exception("No private key file found matching the pattern 'privkey\\d+\\.pem'.")
        with z.open(cert_filename) as cert_file:
            cert_data = cert_file.read()
            cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert_data)
            cn: str = cert.get_subject().CN or "unknown"
            with z.open(key_filename) as key_file:
                private_key_data = key_file.read()
            return cert_data, private_key_data, cn

def list_certificates(token: str) -> None:
    url = f'{npm_mgmt_endpoint}/api/nginx/certificates?expand=owner'
    headers = {
        'Authorization': f'Bearer {token}'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        certificates = response.json()
        print("ID | Domains | Provider")
        print("-" * 50)
        for cert in certificates:
            print(f"{cert['id']} | {cert['nice_name']} | {cert['provider']}")
    else:
        raise Exception(f"Failed to list certificates: {response.text}")

def main() -> None:
    parser = argparse.ArgumentParser(description='NPM Certificate Download Tool')
    parser.add_argument('--list-certs', action='store_true', help='List available certificates')
    parser.add_argument('--endpoint', help='NPM Management Endpoint (e.g., http://<truenas-ip>:81)')
    parser.add_argument('--username', help='Username for NPM Management Portal')
    parser.add_argument('--password', help='Password for NPM Management Portal')
    parser.add_argument('--cert-file', help='Path where the downloaded certificate will be saved')
    parser.add_argument('--key-file', help='Path where the downloaded private key will be saved')
    parser.add_argument('--cert-id', type=int, help='ID of the certificate to download')
    args = parser.parse_args()

    global npm_mgmt_endpoint, username, password, cert_file, key_file, cert_id
    
    npm_mgmt_endpoint = args.endpoint or DEFAULT_NPM_MGMT_ENDPOINT
    username = args.username or DEFAULT_USERNAME
    password = args.password or DEFAULT_PASSWORD
    
    if not npm_mgmt_endpoint:
        parser.error("NPM Management Endpoint is required. Provide it with --endpoint or set NPM_MGMT_ENDPOINT environment variable.")
    if not username:
        parser.error("Username is required. Provide it with --username or set NPM_USERNAME environment variable.")
    if not password:
        parser.error("Password is required. Provide it with --password or set NPM_PASSWORD environment variable.")
    try:
        assert username is not None
        assert password is not None
        token = get_bearer_token(username, password)
        if args.list_certs:
            list_certificates(token)
        else:
            cert_file_path = args.cert_file
            key_file_path = args.key_file
            cert_id_val = args.cert_id
            if not cert_file_path:
                parser.error("Certificate file path is required. Provide it with --cert-file.")
            if not key_file_path:
                parser.error("Key file path is required. Provide it with --key-file.")            
            if not cert_id_val:
                parser.error("Certificate ID is required. Provide it with --cert-id.")
            os.makedirs(os.path.dirname(cert_file_path), exist_ok=True)
            os.makedirs(os.path.dirname(key_file_path), exist_ok=True)
            zip_content = download_certificate(token, cert_id_val)
            cert_data, private_key_data, cn = read_certificates(zip_content)
            with open(cert_file_path, 'wb') as f:
                f.write(cert_data)
            with open(key_file_path, 'wb') as f:
                f.write(private_key_data)
            print(f"Certificate for {cn} has been downloaded successfully")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    main()
