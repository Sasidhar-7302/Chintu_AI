"""
Dataset Generator for Chintu Auto Fine-Tuning.
Exports successful interactions from memory to Alpaca JSONL format.
"""
import json
import logging
from typing import List, Dict, Any
from pathlib import Path

from chintu_backend.brain.memory.hybrid_memory import get_hybrid_memory
from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)

def generate_dataset(output_path: str = None, limit: int = 1000) -> str:
    """
    Export successful task executions to a JSONL dataset.
    
    Args:
        output_path: Path to save JSONL file. Defaults to data/training/chintu_finetune.jsonl
        limit: Max samples to export
        
    Returns:
        Path to generated file or error message
    """
    try:
        mem = get_hybrid_memory()
        if not mem:
            return "Memory manager not initialized."
            
        config = get_config()
        if not output_path:
            out_dir = Path(config.data_dir) / "training"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / "chintu_finetune.jsonl"
            
        # Query successful task executions
        # Note: hybrid_memory search doesn't support complex SQL filters perfectly via public API,
        # so we access the connection directly for this admin task.
        with mem._lock:
            cur = mem._conn.execute(
                """
                SELECT role, content, tags 
                FROM interactions 
                WHERE category = 'task_execution' 
                  AND content LIKE '%success: True%'
                ORDER BY id DESC 
                LIMIT ?
                """,
                (limit,)
            )
            rows = cur.fetchall()
            
        if not rows:
            return "No successful training examples found in memory."
            
        dataset = []
        for row in rows:
            # Parse content: "Executed capability 'cap_name': Result message..."
            content = row["content"]
            
            # Rough parsing logic - assumes basic format from action_dispatcher
            # In a real system, we'd store structured inputs/outputs separately.
            # Here we reconstruct the prompt from context if possible, or skip.
            # Since we only stored the RESULT, we might need the INPUT.
            # But wait, action_dispatcher saves the RESULT interaction.
            # The USER input was a previous interaction.
            
            # Strategy: Look for the User Input immediately preceding this Task Execution
            # This requires a join or subquery. Let's try to fetch user inputs too.
            pass

        # Improved Query: Join User Input with Assistant Execution
        # We need pairs: (User Request) -> (Assistant Execution)
        # This is hard because they are separate rows.
        # Fallback: Just return the stats for now as V1.
        
        return f"Found {len(rows)} potential training samples. (Full pair extraction pending Phase 2 db schema update)"
        
    except Exception as e:
        logger.error(f"Dataset generation failed: {e}")
        return f"Error generation dataset: {str(e)}"

# Improved Implementation with Join Logic
def generate_dataset_v2(output_path: str = None, limit: int = 1000) -> str:
    """
    Export successful task executions to a JSONL dataset.
    Matches User Request -> Assistant Success.
    """
    try:
        mem = get_hybrid_memory()
        if not mem:
            return "Memory manager not initialized."
            
        config = get_config()
        if not output_path:
            out_dir = Path(config.data_dir) / "training"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / "chintu_finetune.jsonl"
            
        with mem._lock:
            # Join strategy: Find assistant rows from task execution + conversation,
            # then pair with nearest preceding user row.
            cur = mem._conn.execute(
                """
                SELECT 
                    u.content as instruction,
                    a.content as output,
                    a.category as category
                FROM interactions a
                JOIN interactions u ON u.id = (
                    SELECT max(id) FROM interactions 
                    WHERE id < a.id AND role = 'user'
                )
                WHERE a.role = 'assistant'
                  AND a.category IN ('task_execution', 'conversation', 'research', 'developer')
                ORDER BY a.id DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cur.fetchall()
            
        samples = []
        for row in rows:
            instruction = row["instruction"]
            output = row["output"]
            category = (row["category"] or "").strip().lower()

            # Filter out obvious low-signal/error responses.
            output_lower = output.lower()
            if "[error" in output_lower or "i'm having trouble" in output_lower:
                continue
            if len(output.strip()) < 20 or len(instruction.strip()) < 3:
                continue
            
            # Clean up output (remove meta prefixes if needed)
            # "Executed capability 'code_interpreter': Result: 100" -> "100"
            # For now, keeping full trace is actually good for Chain of Thought training.
            
            sample = {
                "instruction": instruction,
                "input": "", # Optional context
                "output": output,
                "metadata": {"category": category}
            }
            samples.append(json.dumps(sample))
            
        if not samples:
            return "No training pairs found."
            
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(samples))
            
        return f"Successfully exported {len(samples)} training samples to {output_path}"
        
    except Exception as e:
        logger.error(f"Dataset generation failed: {e}")
        return f"Error: {e}"

if __name__ == "__main__":
    print(generate_dataset_v2())
