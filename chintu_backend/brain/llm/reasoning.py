"""
Deep Reasoning Mode for Chintu AI Assistant.

Provides chain-of-thought reasoning for complex queries.
Uses structured prompting to break down problems step-by-step.

Based on ChatGPT recommendation:
- Use cloud LLM only when ambiguity is high
- "Deep mode" when you say "think deeply" / "research"
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class DeepReasoner:
    """
    Chain-of-thought reasoning for complex queries.
    
    Breaks down problems step-by-step:
    1. Understand the question
    2. Break into sub-problems
    3. Solve each step
    4. Verify answer
    5. Synthesize response
    """
    
    DEEP_TRIGGERS = [
        "think deeply",
        "think about",
        "reason through",
        "analyze",
        "explain step by step",
        "break down",
        "research this",
        "figure out",
    ]
    
    def __init__(self, llm_client=None):
        """
        Initialize deep reasoner.
        
        Args:
            llm_client: LLM client for reasoning (required)
        """
        self.llm = llm_client
        
    def requires_deep_reasoning(self, text: str) -> bool:
        """
        Check if the query requires deep reasoning.
        
        Args:
            text: User query
            
        Returns:
            True if deep reasoning is needed
        """
        text_lower = text.lower()
        
        # Check for explicit triggers
        for trigger in self.DEEP_TRIGGERS:
            if trigger in text_lower:
                return True
        
        # Check for complex question patterns
        complex_patterns = [
            "why does",
            "how would",
            "what if",
            "compare and contrast",
            "pros and cons",
            "should i",
            "explain the difference",
            "what are the implications",
        ]
        
        for pattern in complex_patterns:
            if pattern in text_lower:
                return True
                
        return False
    
    def reason(self, question: str, context: str = "") -> Dict[str, Any]:
        """
        Perform deep reasoning on a question.
        
        Args:
            question: The question to reason about
            context: Optional context information
            
        Returns:
            Dict with reasoning steps and final answer
        """
        if not self.llm:
            return {
                "success": False,
                "error": "No LLM available for deep reasoning",
                "answer": "I need an LLM to think deeply about this."
            }
        
        # Step 1: Understand and decompose
        decompose_prompt = f"""I need to think carefully about this question.

QUESTION: {question}

First, let me break this down:
1. What is the core question being asked?
2. What sub-questions do I need to answer first?
3. What facts or information do I need?

Break it down:"""

        try:
            decomposition = self.llm.generate(decompose_prompt)
            logger.info("Deep reasoning: decomposition complete")
        except Exception as e:
            logger.error(f"Decomposition failed: {e}")
            decomposition = "Unable to decompose the question."
        
        # Step 2: Reason through
        reasoning_prompt = f"""Now I'll reason through each part step by step.

QUESTION: {question}

MY ANALYSIS:
{decomposition}

Let me think through this carefully:

Step-by-step reasoning:"""

        try:
            reasoning = self.llm.generate(reasoning_prompt)
            logger.info("Deep reasoning: step-by-step complete")
        except Exception as e:
            logger.error(f"Reasoning failed: {e}")
            reasoning = "Unable to complete reasoning."
        
        # Step 3: Synthesize answer
        synthesis_prompt = f"""Based on my analysis, I'll now give a clear, concise answer.

QUESTION: {question}

MY REASONING:
{reasoning}

FINAL ANSWER (clear and helpful):"""

        try:
            answer = self.llm.generate(synthesis_prompt)
            logger.info("Deep reasoning: synthesis complete")
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            answer = reasoning  # Fall back to reasoning
        
        return {
            "success": True,
            "question": question,
            "decomposition": decomposition,
            "reasoning": reasoning,
            "answer": answer.strip(),
            "mode": "deep_reasoning"
        }
    
    def quick_reason(self, question: str) -> str:
        """
        Quick chain-of-thought in a single prompt.
        
        More efficient for moderately complex questions.
        """
        if not self.llm:
            return "I need an LLM to reason about this."
        
        prompt = f"""Think step by step to answer this question.

Question: {question}

Let me think through this:
1. First, I'll consider...
2. Then, I'll analyze...
3. Finally, I'll conclude...

My reasoning:"""

        try:
            response = self.llm.generate(prompt)
            return response.strip()
        except Exception as e:
            logger.error(f"Quick reasoning failed: {e}")
            return f"I had trouble reasoning about this: {e}"


# Global instance
_reasoner: Optional[DeepReasoner] = None


def get_deep_reasoner(llm_client=None) -> DeepReasoner:
    """Get or create the global reasoner."""
    global _reasoner
    if _reasoner is None:
        _reasoner = DeepReasoner(llm_client)
    elif llm_client and not _reasoner.llm:
        _reasoner.llm = llm_client
    return _reasoner
