import subprocess
import paramiko
import os
import json
from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "hosts.json")

def _load_host_config(target_host: str):
    """
    Loads host details from config/hosts.json.
    Returns dict or None.
    """
    if not os.path.exists(CONFIG_PATH):
        # Fallback for unconfigured systems: return 'local' if requested
        if target_host == "local":
            return {"type": "local"}
        return None
        
    try:
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
            
        for host in data.get("hosts", []):
            if host["name"].lower() == target_host.lower():
                return host
    except Exception as e:
        print(f"Error reading hosts.json: {e}")
        
    return None

def run_command(cmd: str, target_host: str = "local") -> str:
    """
    Executes a command on the target host defined in hosts.json.
    """
    host_config = _load_host_config(target_host)
    
    if not host_config:
        return f"Error: Host '{target_host}' not found in configuration."
        
    # LOCAL EXECUTION
    if host_config.get("type", "local") == "local":
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return f"Error executing command '{cmd}': {e.stderr}"
            
    # SSH EXECUTION
    elif host_config.get("type") == "ssh":
        ip = host_config.get("ip")
        user = host_config.get("user")
        key_path = host_config.get("key_path")
        
        # print(f"[SSH] Connecting to {target_host} ({ip})...")
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {"hostname": ip, "username": user}
            if key_path:
                connect_kwargs["key_filename"] = key_path
                
            client.connect(**connect_kwargs, timeout=10)
            stdin, stdout, stderr = client.exec_command(cmd)
            exit_status = stdout.channel.recv_exit_status()
            
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            
            client.close()
            
            if exit_status != 0:
                return f"Error (Status {exit_status}): {err}"
            return out
            
        except Exception as e:
             return f"SSH Connection to {target_host} failed: {str(e)}"
             
    else:
        return f"Error: Unknown host type for '{target_host}'"
