from typing import TypedDict, List, Dict, Optional, Any

class GuardianState(TypedDict):
    """
    State for the Guardian Graph.
    """
    metrics: Dict[str, Any]  # Stores CPU, RAM, Disk usage
    anomalies: List[str]     # List of detected issues (e.g. "High CPU")
    diagnosis: str           # Explanation from the LLM
    proposed_action: str     # Command proposed to fix the issue
    action_type: str         # "investigate" or "fix"
    human_approval: bool     # Whether the user approved the action
    investigation_history: List[str] # Log of executed commands and outputs
    steps_count: int         # Counter to prevent infinite loops
