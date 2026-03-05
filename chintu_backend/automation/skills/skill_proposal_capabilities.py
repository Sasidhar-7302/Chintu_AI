"""Capabilities for skill proposal approval workflow."""

from __future__ import annotations

import re
from typing import Dict, Any

from chintu_backend.core.capabilities import Capability, CapabilityType, ActionResult
from chintu_backend.core.config import get_config
from chintu_backend.automation.skills.skill_proposals import (
    create_proposal,
    list_proposals,
    approve_proposal,
    reject_proposal,
    rollback_skill,
)


def _extract_id(text: str) -> str:
    match = re.search(r"(proposal_[a-z0-9_-]+)", text.lower())
    return match.group(1) if match else ""


def handle_skill_propose(text: str, context: Dict[str, Any]) -> ActionResult:
    """Generate a SKILL.md proposal using the Librarian agent."""
    # Extract topic
    topic = text
    for prefix in ["propose skill", "draft skill", "create skill", "suggest skill", "learn skill"]:
        if topic.lower().startswith(prefix):
            topic = topic[len(prefix):].strip()
            break
    if not topic:
        return ActionResult.fail("Tell me what skill to propose.", "skill_propose")

    try:
        from chintu_backend.brain.swarm.agents.librarian import LibrarianAgent
        llm = context.get("llm_client")
        if llm is None:
            try:
                from chintu_backend.brain.llm.ollama_client import OllamaClient
                llm = OllamaClient()
            except Exception:
                llm = None
        if not llm:
            return ActionResult.fail("No LLM available to draft a skill.", "skill_propose")

        agent = LibrarianAgent(llm_client=llm)
        result = agent.run(topic, context=context)
        proposal_id = result.get("proposal_id")
        if proposal_id:
            msg = f"Drafted skill proposal {proposal_id}. Say 'approve skill {proposal_id}' to enable it."
        else:
            # Fallback: store directly if agent didn't save
            proposal = create_proposal(
                result.get("proposed_skill", ""),
                source="skill_propose",
                reason=f"Requested skill proposal: {topic}",
            )
            msg = f"Drafted skill proposal {proposal.id}. Say 'approve skill {proposal.id}' to enable it."
        return ActionResult.ok(msg, {"proposal_id": proposal_id}, "skill_propose")
    except Exception as e:
        return ActionResult.fail(f"Failed to draft skill: {e}", "skill_propose")


def handle_skill_list(_text: str, _context: Dict[str, Any]) -> ActionResult:
    proposals = list_proposals()
    if not proposals:
        return ActionResult.ok("No pending skill proposals.", capability="skill_proposal_list")
    lines = ["Skill proposals:"]
    for p in proposals[:20]:
        issue_note = f" (issues: {len(p.issues)})" if p.issues else ""
        lines.append(f"- {p.id}: {', '.join(p.names)} [{p.status}]{issue_note}")
    return ActionResult.ok("\n".join(lines), capability="skill_proposal_list")


def handle_skill_approve(text: str, _context: Dict[str, Any]) -> ActionResult:
    proposal_id = _extract_id(text)
    if not proposal_id:
        return ActionResult.fail("Specify proposal id, e.g. 'approve skill proposal_xyz'.", "skill_proposal_approve")
    try:
        proposal = approve_proposal(proposal_id, approver="user")
        if proposal.status == "failed":
            return ActionResult.fail(
                "Skill tests failed. Fix the proposal or adjust tests before approving.",
                "skill_proposal_approve",
            )
        if proposal.status == "blocked":
            return ActionResult.fail(
                "Skill blocked by policy. Check allowlist/denylist or shell policy.",
                "skill_proposal_approve",
            )
        # Best-effort reload
        try:
            from chintu_backend.core.capabilities import get_registry
            from chintu_backend.automation.skills.skill_registry import SkillRegistry
            from chintu_backend.core.config import get_config
            config = get_config()
            registry = get_registry()
            skill_registry = SkillRegistry()
            sources = [
                (config.skills_bundled_dir, "bundled"),
                (config.skills_learned_dir, "learned"),
                (config.skills_user_dir, "user"),
                (config.skills_dir, "workspace"),
            ]
            sources = [(path, label) for path, label in sources if path]
            skill_registry.load_sources(sources)
            skill_registry.register_capabilities(registry)
        except Exception:
            pass
        msg = f"Approved {proposal.id}. Skill(s) enabled: {', '.join(proposal.names)}."
        if proposal.issues:
            msg += f" Note: {len(proposal.issues)} issue(s) were flagged."
        return ActionResult.ok(msg, {"proposal_id": proposal.id}, "skill_proposal_approve")
    except Exception as e:
        return ActionResult.fail(f"Failed to approve: {e}", "skill_proposal_approve")


def handle_skill_reject(text: str, _context: Dict[str, Any]) -> ActionResult:
    proposal_id = _extract_id(text)
    if not proposal_id:
        return ActionResult.fail("Specify proposal id, e.g. 'reject skill proposal_xyz'.", "skill_proposal_reject")
    try:
        proposal = reject_proposal(proposal_id, reason="rejected by user")
        return ActionResult.ok(f"Rejected {proposal.id}.", {"proposal_id": proposal.id}, "skill_proposal_reject")
    except Exception as e:
        return ActionResult.fail(f"Failed to reject: {e}", "skill_proposal_reject")


def handle_skill_rollback(text: str, _context: Dict[str, Any]) -> ActionResult:
    match = re.search(r"rollback skill ([a-z0-9_-]+)", text.lower())
    if not match:
        return ActionResult.fail("Specify a skill name to rollback, e.g. 'rollback skill weather'.", "skill_rollback")
    name = match.group(1)
    path = rollback_skill(name)
    if not path:
        return ActionResult.fail("No rollback version found for that skill.", "skill_rollback")
    return ActionResult.ok(f"Rolled back skill '{name}' to {path.name}.", {"skill": name}, "skill_rollback")


def register_skill_proposal_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="skill_propose",
            triggers=[
                "propose skill",
                "draft skill",
                "suggest skill",
                "create skill",
                "learn skill",
            ],
            handler=handle_skill_propose,
            requires_confirmation=False,
            description="draft a skill proposal that requires approval",
            capability_type=CapabilityType.AI_AGENT,
            examples=["Propose skill for summarizing PDFs"],
        )
    )
    registry.register(
        Capability(
            name="skill_proposal_list",
            triggers=["list skill proposals", "show skill proposals", "pending skills"],
            handler=handle_skill_list,
            requires_confirmation=False,
            description="list pending skill proposals",
            capability_type=CapabilityType.SYSTEM,
            examples=["List skill proposals"],
        )
    )
    registry.register(
        Capability(
            name="skill_proposal_approve",
            triggers=["approve skill"],
            handler=handle_skill_approve,
            requires_confirmation=True,
            description="approve a pending skill proposal",
            capability_type=CapabilityType.SYSTEM,
            examples=["Approve skill proposal_foo_123"],
        )
    )
    registry.register(
        Capability(
            name="skill_proposal_reject",
            triggers=["reject skill"],
            handler=handle_skill_reject,
            requires_confirmation=True,
            description="reject a pending skill proposal",
            capability_type=CapabilityType.SYSTEM,
            examples=["Reject skill proposal_foo_123"],
        )
    )
    registry.register(
        Capability(
            name="skill_rollback",
            triggers=["rollback skill"],
            handler=handle_skill_rollback,
            requires_confirmation=True,
            description="rollback a skill to the previous version",
            capability_type=CapabilityType.SYSTEM,
            examples=["Rollback skill weather"],
        )
    )
