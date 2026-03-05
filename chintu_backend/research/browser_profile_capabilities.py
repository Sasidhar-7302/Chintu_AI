"""Capabilities for LLM-in-browser research profiles (Phase 23)."""

from __future__ import annotations

from typing import Any, Dict

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType

from .browser_profiles import (
    detect_site_from_text,
    extract_prompt_from_text,
    get_browser_research_assistant,
)


def handle_research_browser_draft(text: str, _context: Dict[str, Any]) -> ActionResult:
    assistant = get_browser_research_assistant()
    site = detect_site_from_text(text)
    prompt = extract_prompt_from_text(text)
    result = assistant.draft_prompt(site=site, prompt=prompt, logged_in=False)
    if not bool(result.get("ok")):
        return ActionResult.fail("Research browser draft failed.", "research_browser_draft")

    msg = (
        f"Draft ready for {result.get('site')} in profile '{result.get('profile')}'.\n"
        f"Prompt preview: {prompt[:220]}\n"
        f"Artifact: {result.get('artifact_path')}\n"
        "Say 'send this research prompt' to submit after explicit confirmation."
    )
    return ActionResult.ok(msg, result, "research_browser_draft")


def handle_research_browser_send(text: str, context: Dict[str, Any]) -> ActionResult:
    assistant = get_browser_research_assistant()
    site = detect_site_from_text(text)
    prompt = extract_prompt_from_text(text)

    needs_confirmation = bool(getattr(assistant.config, "research_browser_submit_requires_confirmation", True))
    if needs_confirmation and not bool(context.get("_research_submit_confirmed", False)):

        def _approve_send() -> ActionResult:
            next_ctx = dict(context or {})
            next_ctx["_research_submit_confirmed"] = True
            return handle_research_browser_send(text, next_ctx)

        preview = prompt if len(prompt) <= 260 else prompt[:257] + "..."
        return ActionResult.confirm(
            (
                f"I can submit this prompt to {site} in the logged-in browser profile.\n"
                f"Prompt preview: {preview}\n\n"
                "Confirm to proceed with the browser send action."
            ),
            _approve_send,
            "research_browser_send",
        )

    result = assistant.send_prompt(site=site, prompt=prompt, logged_in=True)
    if not bool(result.get("ok")):
        return ActionResult.fail("Research browser send failed.", "research_browser_send")

    submitted = bool(result.get("submitted"))
    msg = (
        f"Submitted prompt to {result.get('site')} in profile '{result.get('profile')}'.\n"
        f"Submitted: {submitted}\n"
        f"Artifact: {result.get('artifact_path')}"
    )
    return ActionResult.ok(msg, result, "research_browser_send")


def handle_research_browser_capture(text: str, _context: Dict[str, Any]) -> ActionResult:
    assistant = get_browser_research_assistant()
    site = detect_site_from_text(text)
    result = assistant.capture_response(site=site, note="captured for dossier", logged_in=True)
    if not bool(result.get("ok")):
        return ActionResult.fail("Research browser capture failed.", "research_browser_capture")
    response_text = str(result.get("response_text") or "").strip()
    preview = response_text[:280] + ("..." if len(response_text) > 280 else "")
    msg = (
        f"Captured {result.get('site')} response in profile '{result.get('profile')}'.\n"
        f"Preview: {preview or 'No visible text extracted.'}\n"
        f"Artifact: {result.get('artifact_path')}"
    )
    return ActionResult.ok(msg, result, "research_browser_capture")


def register_browser_profile_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="research_browser_draft",
            triggers=[
                "research using chatgpt",
                "research using claude",
                "research using gemini",
                "draft research prompt in browser",
                "open chatgpt for research",
            ],
            handler=handle_research_browser_draft,
            requires_confirmation=False,
            description="open an LLM website in dedicated research profile and draft a prompt",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="research_browser_send",
            triggers=[
                "send this research prompt",
                "submit research prompt",
                "send to chatgpt",
                "send to claude",
                "send to gemini",
            ],
            handler=handle_research_browser_send,
            requires_confirmation=False,
            description="send drafted prompt to LLM website with explicit approval",
            capability_type=CapabilityType.AUTOMATION,
        )
    )

    registry.register(
        Capability(
            name="research_browser_capture",
            triggers=[
                "capture research response",
                "capture chatgpt response",
                "capture claude response",
                "capture gemini response",
            ],
            handler=handle_research_browser_capture,
            requires_confirmation=False,
            description="capture text+screenshot evidence from LLM website page",
            capability_type=CapabilityType.SYSTEM,
        )
    )
