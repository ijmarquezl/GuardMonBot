import asyncio
import os
from langchain_core.tools import tool
from guardian_monitor.ssh_tools import run_command
from guardian_monitor.search_tools import search_duckduckgo
# Knowledge Path
import os
KNOWLEDGE_FILE = os.path.join(os.path.dirname(__file__), "knowledge.md")

@tool
def get_system_metrics(target_host: str = "local") -> str:
    """
    Checks the current health of the system (CPU, RAM, Disk, Network).
    Returns a detailed string with metrics and status (NORMAL/HIGH).
    
    Args:
        target_host: The name of the host to check (e.g., 'local', 'proxmox-pve'). 
                     Defaults to 'local'. Refer to your Available Hosts list.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    return loop.run_until_complete(_async_get_metrics(target_host))

async def _async_get_metrics(host: str):
    # Thresholds
    cpu_thresh = float(os.getenv("CPU_THRESHOLD", "80.0"))
    ram_thresh = float(os.getenv("RAM_THRESHOLD", "90.0"))
    disk_thresh = float(os.getenv("DISK_THRESHOLD", "90.0"))
    
    loop = asyncio.get_event_loop()
    
    # helper for concise calls
    async def run(cmd):
        return await loop.run_in_executor(None, run_command, cmd, host)

    # 1. CPU Usage (Top)
    # Check connectivity FIRST
    connectivity_check = await run("echo 'ok'")
    if "Error" in connectivity_check or "failed" in connectivity_check:
        return f"CRITICAL ERROR: Could not connect to host '{host}'. Details: {connectivity_check}\nPlease verify 'guardian_monitor/config/hosts.json'."

    try:
        top_cpu = await run("top -bn2 -d 0.5 | grep 'Cpu(s)' | tail -n 1")
        parts = top_cpu.split(",")
        idle_str = [x for x in parts if "id" in x][0]
        idle_val = float(idle_str.split("id")[0].strip())
        cpu_usage = round(100.0 - idle_val, 2)
    except:
        cpu_usage = 0.0

    # 2. RAM Usage
    try:
        free_output = await run("free -m")
        lines = free_output.splitlines()
        mem_line = [l for l in lines if l.startswith("Mem:")][0]
        parts = mem_line.split()
        total_ram = int(parts[1])
        used_ram = int(parts[2])
        ram_usage = round((used_ram / total_ram) * 100, 2)
    except:
        ram_usage = 0.0

    # 3. Disk Usage (Root)
    try:
        df_output = await run("df -h /")
        lines = df_output.splitlines()
        disk_line = [l for l in lines if l.endswith("/")][0]
        disk_usage_str = [x for x in disk_line.split() if x.endswith("%")][0]
        disk_usage = float(disk_usage_str.strip("%"))
    except:
        disk_usage = 0.0
        
    # 4. Network Stats
    net_output = await run("cat /proc/net/dev")
    
    # 5. Top Processes
    top_procs = await run("ps -eo pid,cmd,%mem,%cpu --sort=-%cpu | head -n 10")
    
    # Simple filtering (heuristic)
    try:
        top_procs_clean = "\n".join(top_procs.splitlines()[:6])
    except:
        top_procs_clean = ""

    # Status Labels
    cpu_status = "ALTA" if cpu_usage > cpu_thresh else "NORMAL"
    ram_status = "ALTA" if ram_usage > ram_thresh else "NORMAL"
    disk_status = "ALTA" if disk_usage > disk_thresh else "NORMAL"
    
    report = f"""
[MÉTRICAS DEL SISTEMA: {host}]
CPU: {cpu_usage}% (Umbral: {cpu_thresh}%) [{cpu_status}]
RAM: {ram_usage}% (Umbral: {ram_thresh}%) [{ram_status}]
DISCO (/): {disk_usage}% (Umbral: {disk_thresh}%) [{disk_status}]

[TRÁFICO DE RED]
{net_output[:300] if net_output else "No data"}...

[TOP PROCESOS]
{top_procs_clean}
"""
    return report.strip()

@tool
def web_search(query: str) -> str:
    """
    Searches the web for information using DuckDuckGo.
    Use this to look up error messages, solutions, or unknown Linux commands.
    """
    return search_duckduckgo(query)

@tool
def execute_terminal_command(command: str, target_host: str = "local") -> str:
    """
    Executes a shell command on the specified server.
    
    Args:
        command: The shell command to run.
        target_host: The name of the host (e.g., 'local', 'proxmox'). Defaults to 'local'.
    
    CRITICAL: Only use for diagnosis (ls, cat, ps) safely. 
    If a modification (kill, rm, restart) is needed, YOU MUST ASK THE USER FIRST.
    """
    return run_command(command, target_host)

@tool
def save_knowledge(topic: str, content: str) -> str:
    """
    Saves useful information to permanent memory.
    Use this when the user teaches you something new (e.g., "To restart app X, do Y").
    
    Args:
        topic: A short title for the knowledge (e.g., "Nginx Restart").
        content: The detailed instruction or fact.
    """
    try:
        entry = f"\n- **{topic}**: {content}"
        with open(KNOWLEDGE_FILE, "a") as f:
            f.write(entry)
        return f"Successfully saved knowledge about '{topic}'."
    except Exception as e:
        return f"Error saving knowledge: {e}"

@tool
def read_system_logs(target_host: str = "local", log_source: str = "journal_errors", lines: int = 50) -> str:
    """
    Reads system logs to diagnose errors.
    
    Args:
        target_host: The server to check (default 'local').
        log_source: One of ['journal_errors', 'journal_all', 'auth', 'syslog', 'dmesg'].
                   - 'journal_errors': Critical system errors (since boot). BEST FOR DEBUGGING.
                   - 'auth': Login attempts (ssh).
        lines: Number of lines to read (default 50).
    """
    valid_sources = {
        "journal_errors": "journalctl -p 3 -xb --no-pager",
        "journal_all": "journalctl -xb --no-pager",
        "auth": "cat /var/log/auth.log",
        "syslog": "cat /var/log/syslog",
        "dmesg": "dmesg -T"
    }
    
    cmd = valid_sources.get(log_source, "journalctl -p 3 -xb --no-pager")
    full_cmd = f"{cmd} | tail -n {lines}"
    
    # Run helper function for async capability if needed, but run_command is sync compatible here
    # Actually tools.py calls sync run_command inside async wrappers in other tools.
    # Let's keep it simple and blocking for now as it's just text reading.
    # Wait, tools.py structure usually uses _async wrapper. Let's do that to be safe.
    
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    return loop.run_until_complete(async_run_log_cmd(full_cmd, target_host))

async def async_run_log_cmd(cmd, host):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_command, cmd, host)
