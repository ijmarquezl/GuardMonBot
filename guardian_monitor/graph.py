import os
import json
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.memory import MemorySaver
from guardian_monitor.tools import get_system_metrics, web_search, execute_terminal_command, save_knowledge, read_system_logs

def create_graph():
    """
    Creates the ReAct agent graph.
    """
    # LLM Setup
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://10.29.93.56:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    
    llm = ChatOllama(model=ollama_model, base_url=ollama_base_url, temperature=0.7)
    
    # Tools
    tools = [get_system_metrics, web_search, execute_terminal_command]
    
    # Load Hosts Config
    hosts_config_path = os.path.join(os.path.dirname(__file__), "config", "hosts.json")
    available_hosts = []
    try:
        if os.path.exists(hosts_config_path):
            with open(hosts_config_path, 'r') as f:
                data = json.load(f)
                available_hosts = [f"- {h['name']}: {h.get('description', '')} ({h.get('ip', 'local')})" for h in data.get("hosts", [])]
    except Exception as e:
        print(f"Error loading hosts.json: {e}")
    
    hosts_str = "\n    ".join(available_hosts) if available_hosts else "- local: El Agente mismo."
    
    # Load Knowledge Base
    knowledge_path = os.path.join(os.path.dirname(__file__), "knowledge.md")
    knowledge_content = ""
    try:
        if os.path.exists(knowledge_path):
            with open(knowledge_path, "r") as f:
                knowledge_content = f.read()
    except Exception as e:
        print(f"Error loading knowledge config: {e}")
        
    # Update Tools List
    tools = [get_system_metrics, web_search, execute_terminal_command, save_knowledge, read_system_logs]

    # System Prompt
    system_prompt = f"""Eres 'GuardMonBot', un Agente Experto en Linux y SysAdmin.
    Tu trabajo no es solo dar consejos, sino AYUDAR ACTIVAMENTE a monitorear y reparar servidores.
    
    SERVIDOR(ES) DISPONIBLES:
    {hosts_str}
    
    IMPORTANTE:
    Cuando uses herramientas como 'get_system_metrics' o 'execute_terminal_command', SIEMPRE especifica el argumento 'target_host' 
    basado en la petición del usuario. Si no especifica, asume 'local'.
    
    TIENES ACCESO A HERRAMIENTAS REALES:
    
    TIENES ACCESO A HERRAMIENTAS REALES:
    1. get_system_metrics: Para ver CPU, RAM, Disco, Red y Procesos. Úsala si el usuario pregunta "¿Cómo está el sistema?".
    2. execute_terminal_command: Para ejecutar comandos (ls, cat, ip, etc).
        - PELIGRO: NUNCA ejecutes comandos destructivos (rm, kill, restart) SIN PEDIR PERMISO EXPLÍCITO.
    3. web_search: Para buscar errores desconocidos.
    
    MODO PLANIFICADOR INTERACTIVO:
    Si el usuario pide una tarea compleja (ej: "Limpiar disco", "Arreglar Nginx", "Liberar espacio"):
    1.  NO respondas con un muro de texto o una lista de consejos genéricos.
    2.  Analiza la petición y diseña un PLAN DE ACCIÓN con comandos reales.
    3.  Propón el plan paso a paso y pide permiso para ejecutar el PRIMER paso.
        - Ejemplo: "Entendido. Para limpiar /var propongo: 1. `du -sh /var` (Ver tamaño), 2. `apt-get clean` (Limpiar caché). ¿Procedo con el paso 1?"
    4.  Una vez ejecutado el paso 1, reporta el resultado y pregunta si procedes con el paso 2.
    
    REGLAS GENERALES:
    - HABLA SIEMPRE EN ESPAÑOL.
    - Sé conciso.
    - Si el usuario solo saluda, responde amablemente sin usar herramientas.
    - **IMPORTANTE:** Si te conectas a un servidor como usuario NO-ROOT (ej. 'ivan'), recuerda anteponer `sudo` a los comandos que lo requieran (apt, systemctl, reboot). NO pidas la contraseña de sudo, asume que está configurado como NOPASSWD.
    
    PROTOCOLO DE RESILIENCIA:
    - Si un comando falla, ¡NO TE RINDAS! 
    - Analiza el error. Si es un typo, corrígelo. Si falta un paquete, suguiere instalarlo.
    - Intenta al menos una alternativa antes de reportar fracaso al usuario.
    - Usa 'save_knowledge' cuando el usuario te enseñe algo nuevo para no olvidarlo.
    
    CONOCIMIENTOS APRENDIDOS (MEMORIA A LARGO PLAZO):
    {knowledge_content}
    """
    
    # Create ReAct Agent (Agent -> Tools -> Agent) with Memory
    memory = MemorySaver()
    graph = create_react_agent(llm, tools, prompt=system_prompt, checkpointer=memory)
    
    return graph
