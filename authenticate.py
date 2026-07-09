import os
import json
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

def main():
    secrets_file = "client_secrets.json"
    
    if not os.path.exists(secrets_file):
        print(f"ERROR: '{secrets_file}' not found in the current directory.")
        print("Please download your client secrets JSON from Google Cloud Console,")
        print(f"rename it to '{secrets_file}', place it here, and run the script again.")
        sys.exit(1)
        
    # Standard YouTube Upload & Read scopes
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly"
    ]
    
    print("Starting authentication flow...")
    print("A browser window should open. Log in to your YouTube account and authorize access.")
    
    try:
        # Run local server to capture redirect authorization code
        flow = InstalledAppFlow.from_client_secrets_file(secrets_file, scopes)
        credentials = flow.run_local_server(port=0)
        
        # Read the client secrets back to compile the GHA secrets payload
        with open(secrets_file, "r") as f:
            secrets_data = json.load(f)
            
        # Get client_id and client_secret from either web or installed formats
        client_type = "installed" if "installed" in secrets_data else "web"
        client_info = secrets_data.get(client_type, {})
        
        client_id = client_info.get("client_id")
        client_secret = client_info.get("client_secret")
        
        # Compile formatted GHA secrets JSON string
        secret_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri or "https://oauth2.googleapis.com/token"
        }
        
        print("\n" + "="*50)
        print("SUCCESS! Copy the entire JSON block below and save it")
        print("as a secret in your GitHub repository (e.g. YOUTUBE_OAUTH_MINECRAFT):")
        print("="*50)
        print(json.dumps(secret_payload, indent=2))
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\nERROR: Authentication flow failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
