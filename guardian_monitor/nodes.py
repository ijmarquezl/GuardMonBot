import json
from guardian_monitor.state import GuardianState
from guardian_monitor.ssh_tools import run_command
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from guardian_monitor import bot
from guardian_monitor.search_tools import search_duckduckgo
import os
import asyncio

# Thresholds
# Thresholds
CPU_THRESHOLD = float(os.getenv("CPU_THRESHOLD", "80.0"))
DISK_THRESHOLD = float(os.getenv("DISK_THRESHOLD", "90.0"))
RAM_THRESHOLD = float(os.getenv("RAM_THRESHOLD", "90.0"))

SAFE_COMMANDS = ["ls", "cat", "grep", "head", "tail", "who", "ps", "top", "df", "free", "ip", "uptime", "journalctl", "netstat", "ss", "search"]

def sanitize_command(cmd: str) -> str:
    """
    Removes comments or explanations from the command string.
    e.g. "cat /etc/hosts # check hosts" -> "cat /etc/hosts"
    """
    if not cmd:
        return ""
        
    # Split by newline and take first line
    cmd = cmd.split('\n')[0].strip()
    
    # Remove # comments
    cmd = cmd.split('#')[0].strip()
    
    # Handle "kill 1234 (process_name)" -> "kill 1234"
    if cmd.startswith("kill ") and "(" in cmd:
        cmd = cmd.split('(')[0].strip()
    
    # Some LLMs output "Run: cat ..."
    if cmd.lower().startswith("run: "):
        cmd = cmd[5:].strip()

    # REMOVE COMMON HALLUCINATIONS
    if "restart/stop/start" in cmd:
        # If the LLM was lazy, just return empty to force a retry/fail or better, try to guess? 
        # Better to return it as is but maybe log? 
        # Actually let's assume the LLM prompt fix will handle this.
        pass
        
    return cmd

async def monitor_node(state: GuardianState) -> GuardianState:
    # print("--- MONITORING SYSTEM ---") # Silenced for passive mode
    
    # Check for Manual Trigger from Telegram
    is_manual = False
    if bot.BotGlobals.manual_trigger.is_set():
        is_manual = True
        bot.BotGlobals.manual_trigger.clear()
        print("--- MANUAL MONITORING TRIGGERED ---")
    
    # Check CPU Percentage (real usage 0-100%)
    loop = asyncio.get_event_loop()
    try:
        # Run top twice in batch mode to get accurate reading (first is often average since boot)
        # Actually top -bn2 -d 0.5 | grep "Cpu(s)" | tail -n 1
        top_cpu = await loop.run_in_executor(None, run_command, "top -bn2 -d 0.5 | grep 'Cpu(s)' | tail -n 1")
        # Example: "%Cpu(s):  5.9 us,  2.0 sy,  0.0 ni, 92.1 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st"
        # Extract idle value (id)
        parts = top_cpu.split(",")
        idle_str = [x for x in parts if "id" in x][0]
        # " 92.1 id"
        idle_val = float(idle_str.split("id")[0].strip())
        cpu_usage = 100.0 - idle_val
        cpu_usage = round(cpu_usage, 2)
    except:
        cpu_usage = 0.0
        
    # Still get uptime for display
    uptime_output = await loop.run_in_executor(None, run_command, "uptime")
        
    # Check Disk
    df_output = await loop.run_in_executor(None, run_command, "df -h /")
    # Example: "/dev/sda1        20G   15G  4.0G  79% /"
    try:
        lines = df_output.splitlines()
        # Find the line with "/" mounted
        disk_line = [l for l in lines if l.endswith("/")][0]
        # Parse percentage (remove %)
        disk_usage_str = [x for x in disk_line.split() if x.endswith("%")][0]
        disk_usage = float(disk_usage_str.strip("%"))
    except:
        disk_usage = 0.0

    # Check RAM
    free_output = await loop.run_in_executor(None, run_command, "free -m")
    try:
        # Mem:           7954        3934        1567
        # We want used / total
        lines = free_output.splitlines()
        mem_line = [l for l in lines if l.startswith("Mem:")][0]
        parts = mem_line.split()
        total_ram = int(parts[1])
        used_ram = int(parts[2])
        ram_usage = (used_ram / total_ram) * 100
    except:
        ram_usage = 0.0

    # Check Network
    net_output = await loop.run_in_executor(None, run_command, "cat /proc/net/dev")
    
    # Check Top Processes (CPU)
    # ps -eo pid,cmd,%mem,%cpu --sort=-%cpu | head -n 6
    top_procs_output = await loop.run_in_executor(None, run_command, "ps -eo pid,cmd,%mem,%cpu --sort=-%cpu | head -n 10")
    
    # Filter out our own PID to avoid self-diagnosis
    my_pid = str(os.getpid())
    filtered_procs = []
    for line in top_procs_output.splitlines():
        if my_pid in line and "python" in line:
            continue
        filtered_procs.append(line)
    
    top_procs = "\n".join(filtered_procs[:6]) # Keep header + top 5
        
    metrics = {
        "cpu_usage": cpu_usage,
        "disk_usage": disk_usage,
        "ram_usage": ram_usage,
        "net_stats": net_output[:200] + "...", # Truncate for prompt size
        "top_processes": top_procs,
        "raw_uptime": uptime_output
    }
    
    anomalies = []
    if cpu_usage > CPU_THRESHOLD:
        anomalies.append(f"High CPU Usage: {cpu_usage}% (Threshold: {CPU_THRESHOLD}%)")
    if disk_usage > DISK_THRESHOLD:
        anomalies.append(f"High Disk Usage: {disk_usage}%")
    if ram_usage > RAM_THRESHOLD:
        anomalies.append(f"High RAM Usage: {ram_usage:.1f}%")
        
    # Check for Manual Trigger from Telegram
    is_manual = False
    if bot.BotGlobals.manual_trigger.is_set():
        is_manual = True
        bot.BotGlobals.manual_trigger.clear()
        
    # If NO anomalies but Manual Trigger -> Force a "Manual Check" anomaly to trigger diagnose
    if is_manual and not anomalies:
         anomalies.append("Manual System Check Requested")
    
    # PASSIVE MODE: If NOT manual and NOT empty anomalies -> Do we want to alert?
    # User requested On-Demand. So we should suppress anomalies UNLESS manual trigger is set.
    # WAIT. If critical thresholds are crossed, maybe we SHOULD alert? 
    # User said: "I need you to indicate what program is... I think it is better to make diagnosis a tool... only execute when I ask".
    # OK, STRICT passive mode.
    if not is_manual:
        anomalies = []

    # Inject fake anomaly for testing if needed
    if os.getenv("TEST_ANOMALY", "False").lower() == "true":
         anomalies.append("TEST_ANOMALY: Simulated High CPU")
         
    # Update global bot metrics
    bot.latest_metrics = metrics
         
    return {
        **state,
        "metrics": metrics,
        "anomalies": anomalies,
        "investigation_history": [], # Reset history
        "steps_count": 0
    }

async def diagnose_node(state: GuardianState) -> GuardianState:
    print("--- DIAGNOSING ISSUE ---")
    metrics = state["metrics"]
    anomalies = state["anomalies"]
    history = state.get("investigation_history", [])
    
    # If no anomalies and no history, we are fine.
    if not anomalies and not history:
        return {**state, "diagnosis": "System Healthy", "proposed_action": "", "action_type": "none"}

    # Ollama Configuration
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://10.29.93.56:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")

    try:
        print(f"Connecting to Ollama at {ollama_base_url}...")
        llm = ChatOllama(model=ollama_model, base_url=ollama_base_url, temperature=0)
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a Linux SysAdmin. Analyze the system metrics and anomalies. 
            You have permissions to execute standard Linux commands.
            
            HISTORY OF INVESTIGATION:
            {history}
            
            GOAL:
            1. If you need more info to identify the root cause, propose a SAFE command (e.g. cat logs, ps aux). Set 'action_type' to 'investigate'.
            2. If you have identified the root cause and know the fix, propose an ACTION command (e.g. systemctl restart <service>, rm <file>, kill <pid>). Set 'action_type' to 'fix'.
            3. If the system is healthy or you cannot do anything more, set 'proposed_action' to 'FINISH' and 'action_type' to 'finish'.
            
            CRITICAL RULES:
            - **DIAGNOSIS MUST BE SPECIFIC**: Don't say "resource-intensive processes". Say "Process 'rustdesk' (PID 1234) is using 80% CPU".
            - **PROCESS != SERVICE**: Do NOT assume a process name (e.g. 'python', 'rustdesk') is a service name.
              - If you are not sure, INVESTIGATE first: 'systemctl status <name>' or 'ps -fp <pid>'.
              - If it is a user process (not a service), proposal 'kill -15 <pid>'.
              - **KILL RULE**: When proposing 'kill', YOU MUST format it as: `kill <pid> (<process_name>)`. Example: `kill 1234 (python)`.
              - Only propose 'systemctl restart' if you are sure it is a service.
            - **DO NOT** use placeholders like 'restart/stop/start'.
            - If a previous command failed, DO NOT retry it.
            
            Available Tools/Actions:
            - File System: mkdir, rm, ls, touch, cat, grep, head, tail
            - Package Management: apt update, apt upgrade, apt install
            - System: systemctl restart <name>, systemctl stop <name>, reboot, systemctl status <name>
            - Process: kill -15 <pid>, kill -9 <pid>
            - Network: ip, ping
            - Web Search: search "query" (e.g. search "nginx failed to bind port 80")
            
            Propose a SINGLE command.
            Return ONLY JSON: {{'diagnosis': '...', 'proposed_action': '...', 'action_type': 'investigate|fix|finish'}}"""),
            ("user", "Metrics: {metrics}\nAnomalies: {anomalies}\n\nProvide response in JSON format.")
        ])
        
        
        chain = prompt | llm
        
        # Async invoke if supported, otherwise wrapper
        response = await chain.ainvoke({
            "metrics": str(metrics), 
            "anomalies": str(anomalies),
            "history": "\n".join(history) if history else "None"
        })
        
        # Simple JSON parsing (robustness would require OutputParser)
        content = response.content.strip()
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "")
        
        data = json.loads(content)
        
        return {
            **state,
            **state,
            "diagnosis": data.get("diagnosis", "Unknown"),
            "proposed_action": sanitize_command(data.get("proposed_action", "echo 'No action'")),
            "action_type": data.get("action_type", "investigate")
        }
    except Exception as e:
        return {
            **state,
            "diagnosis": f"Error in diagnosis: {str(e)}",
            "proposed_action": "echo 'Error'",
            "action_type": "finish"
        }

async def review_node(state: GuardianState) -> GuardianState:
    print("\n--- HUMAN REVIEW ---")
    diagnosis = state['diagnosis']
    action = state['proposed_action']
    action_type = state.get('action_type', 'fix')
    
    print(f"Diagnosis: {diagnosis}")
    print(f"Proposed Action: {action} ({action_type})")
    
    # Store context for Chatbot Q&A
    bot.BotGlobals.current_diagnosis = diagnosis
    bot.BotGlobals.current_action = action
    
    if action == "FINISH" or action_type == "finish":
        bot.BotGlobals.current_diagnosis = None
        bot.BotGlobals.current_action = None
        return {**state, "human_approval": False}

    # CHECK SAFETY FOR AUTO-APPROVAL
    # We only auto-approve "investigate" actions that start with safe prefixes
    is_safe = False
    if action_type == "investigate":
        # Check against SAFE_COMMANDS list
        cmd_prefix = action.split()[0]
        if cmd_prefix in SAFE_COMMANDS:
             is_safe = True
    
    if is_safe:
        print("✅ AUTO-APPROVED SAFE COMMAND")
        # Notify user about the investigation logic
        if bot.BotGlobals.app:
            diagnosis_preview = diagnosis[:200] + "..." if len(diagnosis) > 200 else diagnosis
            await bot.send_execution_result(f"(Auto) {action}", f"🧠 Reasoning: {diagnosis_preview}\n\nRunning investigation...")
        return {**state, "human_approval": True}
    
    # Check if we have a bot
    if bot.BotGlobals.app:
        print("Creating Telegram alert...")
        approved = await bot.send_approval_request(diagnosis, action)
    else:
        # Fallback to CLI
        loop = asyncio.get_event_loop()
        print("Response required in CLI (No Telegram Token found)...")
        response = await loop.run_in_executor(None, input, "Do you approve this action? (y/n): ")
        approved = response.lower().startswith('y')
    
    return {**state, "human_approval": approved}

async def execute_node(state: GuardianState) -> GuardianState:
    print("--- EXECUTING ACTION ---")
    action = state["proposed_action"]
    
    if state.get("human_approval"):
        loop = asyncio.get_event_loop()
        
        # Check if it is a search command
        if action.startswith("search "):
            query = action[7:].strip('"').strip("'")
            print(f"Executing Search: {query}")
            result = await loop.run_in_executor(None, search_duckduckgo, query)
        else:
            result = await loop.run_in_executor(None, run_command, action)
            
        print(f"Result: {result}")
        
        # Send result back to Telegram
        await bot.send_execution_result(action, result)
        
        # Append to history with Status
        status_label = "[FAILURE]" if "Error" in result else "[SUCCESS]"
        new_history = state.get("investigation_history", []) + [f"{status_label} Command: {action}\nOutput: {result[:500]}"]
        
        return {
            **state, 
            "anomalies": [], # We don't clear anomalies yet if we are investigating? Actually better not to clear them until "fix"
            "investigation_history": new_history,
            "steps_count": state.get("steps_count", 0) + 1
        }
    else:
        print("Action NOT approved.")
        return state
