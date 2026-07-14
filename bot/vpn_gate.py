import os
import sys
import base64
import urllib.request
import subprocess
import time

def get_vpn_gate_servers():
    """Fetches the active server list from VPN Gate API."""
    print("Fetching server list from VPN Gate...")
    url = "https://www.vpngate.net/api/iphone/"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode('utf-8', errors='ignore')
        
        lines = content.split('\n')
        if len(lines) < 3:
            raise Exception("Invalid API response format (too few lines).")
        
        # Parse CSV header
        header_line = None
        for i, line in enumerate(lines):
            if line.startswith("#HostName") or line.startswith("HostName"):
                header_line = i
                break
        
        if header_line is None:
            raise Exception("CSV header not found in VPN Gate response.")
            
        headers = [h.strip('#').strip() for h in lines[header_line].split(',')]
        
        servers = []
        for line in lines[header_line + 1:]:
            line = line.strip()
            if not line or line.startswith("*") or line.startswith("#"):
                continue
            parts = line.split(',')
            if len(parts) < len(headers):
                continue
            
            srv = dict(zip(headers, parts))
            # Convert metrics to integers for sorting
            try:
                srv['Score'] = int(srv.get('Score', 0))
                srv['Speed'] = int(srv.get('Speed', 0))
                srv['Ping'] = int(srv.get('Ping', 9999))
            except ValueError:
                continue
            
            servers.append(srv)
            
        print(f"Successfully loaded {len(servers)} servers from VPN Gate.")
        return servers
    except Exception as e:
        print(f"Error fetching VPN Gate server list: {e}")
        return []

def get_current_ip():
    """Returns the current public IP address."""
    urls = ["https://icanhazip.com", "https://api.ipify.org", "https://ifconfig.me/ip"]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read().decode('utf-8').strip()
        except Exception:
            continue
    return None

def connect_vpn():
    """Attempts to connect to the best VPN Gate servers until successful."""
    servers = get_vpn_gate_servers()
    if not servers:
        print("Error: No VPN Gate servers available.")
        sys.exit(1)
        
    # Sort servers: prefer high score, then high speed, then low ping
    servers.sort(key=lambda s: (-s['Score'], -s['Speed'], s['Ping']))
    
    initial_ip = get_current_ip()
    print(f"Initial public IP address: {initial_ip}")
    
    # Try the top 10 servers
    for idx, srv in enumerate(servers[:10]):
        country = srv.get('CountryLong', 'Unknown')
        ip = srv.get('IP', 'Unknown')
        speed_mbps = round(int(srv.get('Speed', 0)) / 1000000.0, 2)
        print(f"\n[{idx+1}/10] Attempting connection to {country} (IP: {ip}, Speed: {speed_mbps} Mbps)...")
        
        config_b64 = srv.get('OpenVPN_ConfigData_Base64', '')
        if not config_b64:
            continue
            
        try:
            config_data = base64.b64decode(config_b64).decode('utf-8')
        except Exception as e:
            print(f"Failed to decode config: {e}")
            continue
            
        # Write config to a temporary file
        config_path = "vpn.ovpn"
        # We append some timeout settings to prevent openvpn from hanging forever if the server is dead
        config_data += "\nconnect-retry-max 2\nresolv-retry 2\ntimeout-transit 5\nhandshake-window 10\n"
        # Prevent openvpn from updating system DNS since we just want general routing
        config_data += "\nsetenv PATH /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_data)
            
        # Start OpenVPN client as daemon
        print("Starting OpenVPN client...")
        try:
            # Clear any existing openvpn processes first
            subprocess.run(["sudo", "killall", "openvpn"], capture_output=True)
            
            # Start openvpn daemon
            proc = subprocess.run([
                "sudo", "openvpn",
                "--config", config_path,
                "--daemon", "openvpn_proc"
            ], capture_output=True, text=True)
            
            if proc.returncode != 0:
                print(f"OpenVPN failed to start: {proc.stderr}")
                continue
                
            # Wait up to 25 seconds for the connection to establish and update IP
            connected = False
            for sec in range(25):
                time.sleep(1)
                new_ip = get_current_ip()
                if new_ip and new_ip != initial_ip:
                    print(f"✅ VPN connected successfully! New public IP address: {new_ip} ({country})")
                    connected = True
                    break
                else:
                    if sec % 5 == 0:
                        print("Waiting for VPN to assign new IP address...")
            
            if connected:
                # Cleanup config file
                try:
                    os.remove(config_path)
                except Exception:
                    pass
                return
            else:
                print("VPN connection timed out or failed to update public IP. Retrying another server...")
                subprocess.run(["sudo", "killall", "openvpn"], capture_output=True)
        except Exception as e:
            print(f"Error during OpenVPN attempt: {e}")
            
    print("❌ Failed to connect to any VPN Gate servers.")
    sys.exit(1)

if __name__ == "__main__":
    connect_vpn()
