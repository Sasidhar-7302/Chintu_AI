"""Safe social/content automation capabilities (Phase 8.5)."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from chintu_backend.core.capabilities import ActionResult, Capability, CapabilityType
from chintu_backend.core.config import get_config
from chintu_backend.policy.action_risk import detect_action_categories
from chintu_backend.security.payment_guard import detect_payment_signal

logger = logging.getLogger(__name__)


class SocialContentPipelineSchema(BaseModel):
    topic: str = Field(..., description="Topic or idea for the social content campaign.")
    platforms: Optional[List[str]] = Field(
        default=None,
        description="Optional target platforms (youtube, instagram, both).",
    )
    tone: Optional[str] = Field("engaging", description="Content tone/style.")
    duration_seconds: Optional[int] = Field(60, ge=15, le=900, description="Target runtime in seconds.")


class SocialStageUploadSchema(BaseModel):
    platform: str = Field(..., description="Target platform: youtube or instagram.")
    asset_dir: Optional[str] = Field(None, description="Folder created by social_content_pipeline.")
    title: Optional[str] = Field(None, description="Optional title override.")
    caption: Optional[str] = Field(None, description="Optional caption override.")


class SocialPublishSchema(BaseModel):
    platform: str = Field(..., description="Target platform: youtube or instagram.")
    asset_dir: Optional[str] = Field(None, description="Folder created by social_content_pipeline.")


class SocialYouTubeChannelSetupSchema(BaseModel):
    channel_name: Optional[str] = Field(None, description="Preferred YouTube channel name.")
    profile: Optional[str] = Field(None, description="Optional browser profile name override.")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_slug(value: str) -> str:
    raw = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return raw or "campaign"


def _campaign_dir(topic: str) -> Path:
    cfg = get_config()
    root = Path(cfg.data_dir) / "content_studio" / "social_campaigns"
    path = root / f"{_utc_stamp()}_{_safe_slug(topic)[:50]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_platforms(text: str, explicit: Optional[List[str]]) -> List[str]:
    if explicit:
        normalized = [str(item).strip().lower() for item in explicit if str(item).strip()]
    else:
        normalized = []
    lower = str(text or "").lower()
    if "both" in normalized or "both" in lower:
        return ["youtube", "instagram"]
    found: List[str] = []
    for name in ("youtube", "instagram"):
        if name in normalized or name in lower:
            found.append(name)
    return found or ["youtube"]


def _generate_script(topic: str, tone: str, duration_seconds: int, platforms: List[str], context: Dict[str, Any]) -> str:
    # Local-first: best effort through model router; deterministic fallback otherwise.
    router = context.get("model_router")
    if not router:
        try:
            from chintu_backend.core.model_router import get_router

            router = get_router()
        except Exception:
            router = None

    prompt = (
        "Create a short-form social script.\n"
        f"Topic: {topic}\n"
        f"Tone: {tone}\n"
        f"Duration: ~{max(15, int(duration_seconds))} seconds\n"
        f"Platforms: {', '.join(platforms)}\n"
        "Output 5 short sections: Hook, Value 1, Value 2, CTA."
    )
    if router and hasattr(router, "route_and_execute"):
        try:
            answer, _source = router.route_and_execute(prompt)
            script = str(answer or "").strip()
            if len(script.split()) >= 40:
                return script
        except Exception:
            pass

    return (
        f"Hook: Stop scrolling. Here is {topic} in one minute.\n"
        f"Value 1: The biggest practical insight is that {topic} is now usable by regular creators.\n"
        "Value 2: Start small, test daily, and keep what actually performs.\n"
        "CTA: Follow for more practical breakdowns and comment what you want next."
    )


def _build_caption(script: str) -> str:
    lines = [part.strip() for part in re.split(r"[.\n]+", script) if part.strip()]
    picked = lines[:4]
    if not picked:
        return "New short is ready."
    return "\n".join(f"- {line}" for line in picked)


def _build_hashtags(topic: str, platforms: List[str]) -> str:
    words = [re.sub(r"[^a-z0-9]", "", token.lower()) for token in topic.split()]
    words = [w for w in words if w]
    tags = ["#ai", "#creator", "#shorts"]
    for word in words[:5]:
        tags.append(f"#{word}")
    if "instagram" in platforms:
        tags.append("#reels")
    if "youtube" in platforms:
        tags.append("#youtubeshorts")
    dedup: List[str] = []
    for tag in tags:
        if tag not in dedup:
            dedup.append(tag)
    return " ".join(dedup)


def _build_thumbnail_prompt(topic: str) -> str:
    return (
        "Design a bold, high-contrast 9:16 thumbnail with 2-4 words max text.\n"
        f"Theme: {topic}\n"
        "Style: modern, readable on mobile, dramatic lighting."
    )


def _build_schedule_checklist(platforms: List[str], title: str) -> str:
    lines = [
        "# Scheduling Checklist",
        "",
        f"Campaign Title: {title}",
        "",
        "## Preflight",
        "- Verify script, captions, hashtags, and thumbnail prompt.",
        "- Ensure final video file is rendered and under platform limits.",
        "- Confirm no payment/upgrade screens are involved.",
        "",
        "## Platform Drafting",
    ]
    for platform in platforms:
        lines.extend(
            [
                f"- [{platform}] Open studio/create page.",
                f"- [{platform}] Upload media and paste caption/hashtags.",
                f"- [{platform}] Save as draft (do NOT publish yet).",
            ]
        )
    lines.extend(
        [
            "",
            "## Final Gate",
            "- Ask explicit confirmation before publish/submit.",
            "- If any checkout/payment UI appears, stop immediately.",
        ]
    )
    return "\n".join(lines) + "\n"


def _normalize_duration_seconds(value: Any) -> int:
    """Clamp duration to a practical social-video range."""
    try:
        seconds = int(value)
    except Exception:
        seconds = 60
    return max(15, min(seconds, 300))


def _platform_upload_url(platform: str) -> str:
    name = str(platform or "").strip().lower()
    if name == "instagram":
        return "https://www.instagram.com/"
    return "https://studio.youtube.com/"


def _social_profile_name(context: Dict[str, Any]) -> str:
    validated = context.get("_validated_params")
    if validated and isinstance(validated, SocialYouTubeChannelSetupSchema):
        raw = str(validated.profile or "").strip()
        if raw:
            return raw
    explicit = str(context.get("browser_profile") or "").strip()
    if explicit:
        return explicit
    cfg = get_config()
    return str(getattr(cfg, "research_browser_loggedin_profile", "") or "assistant_accounts").strip() or "assistant_accounts"


def _parse_social_pipeline_input(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    validated = context.get("_validated_params")
    if isinstance(validated, SocialContentPipelineSchema):
        topic = validated.topic
        platforms = _extract_platforms(text, validated.platforms)
        tone = str(validated.tone or "engaging")
        duration = _normalize_duration_seconds(validated.duration_seconds or 60)
        return {"topic": topic, "platforms": platforms, "tone": tone, "duration": duration}

    topic = text
    for marker in ("about", "on", ":"):
        idx = text.lower().find(marker)
        if idx >= 0:
            topic = text[idx + len(marker) :].strip(" :,-")
            break
    return {
        "topic": topic.strip() or "AI creator workflow",
        "platforms": _extract_platforms(text, None),
        "tone": "engaging",
        "duration": 60,
    }


def handle_social_content_pipeline(text: str, context: Dict[str, Any]) -> ActionResult:
    parsed = _parse_social_pipeline_input(text, context)
    topic = str(parsed["topic"]).strip()
    platforms = list(parsed["platforms"])
    tone = str(parsed["tone"]).strip()
    duration = _normalize_duration_seconds(parsed["duration"])
    campaign_dir = _campaign_dir(topic)

    script = _generate_script(topic, tone, duration, platforms, context)
    captions = _build_caption(script)
    hashtags = _build_hashtags(topic, platforms)
    thumbnail_prompt = _build_thumbnail_prompt(topic)
    checklist = _build_schedule_checklist(platforms, title=topic)

    script_path = campaign_dir / "script.txt"
    captions_path = campaign_dir / "captions.txt"
    hashtags_path = campaign_dir / "hashtags.txt"
    thumbnail_path = campaign_dir / "thumbnail_prompt.txt"
    checklist_path = campaign_dir / "scheduling_checklist.md"
    manifest_path = campaign_dir / "campaign_manifest.json"

    script_path.write_text(script + "\n", encoding="utf-8")
    captions_path.write_text(captions + "\n", encoding="utf-8")
    hashtags_path.write_text(hashtags + "\n", encoding="utf-8")
    thumbnail_path.write_text(thumbnail_prompt + "\n", encoding="utf-8")
    checklist_path.write_text(checklist, encoding="utf-8")
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "topic": topic,
        "platforms": platforms,
        "tone": tone,
        "duration_seconds": duration,
        "files": {
            "script": str(script_path),
            "captions": str(captions_path),
            "hashtags": str(hashtags_path),
            "thumbnail_prompt": str(thumbnail_path),
            "schedule_checklist": str(checklist_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")

    msg = (
        "Social content pipeline ready.\n"
        f"- Topic: {topic}\n"
        f"- Platforms: {', '.join(platforms)}\n"
        f"- Script: {script_path}\n"
        f"- Captions: {captions_path}\n"
        f"- Hashtags: {hashtags_path}\n"
        f"- Thumbnail prompt: {thumbnail_path}\n"
        f"- Campaign folder: {campaign_dir}\n"
        "- Next: run social_stage_upload for draft staging."
    )
    return ActionResult.ok(
        msg,
        {
            "campaign_dir": str(campaign_dir),
            "script": str(script_path),
            "captions": str(captions_path),
            "hashtags": str(hashtags_path),
            "thumbnail_prompt": str(thumbnail_path),
            "schedule_checklist": str(checklist_path),
            "manifest": str(manifest_path),
        },
        "social_content_pipeline",
    )


def _parse_stage_input(text: str, context: Dict[str, Any]) -> Dict[str, str]:
    validated = context.get("_validated_params")
    if isinstance(validated, SocialStageUploadSchema):
        return {
            "platform": str(validated.platform).strip().lower() or "youtube",
            "asset_dir": str(validated.asset_dir or "").strip(),
            "title": str(validated.title or "").strip(),
            "caption": str(validated.caption or "").strip(),
        }
    lower = str(text or "").lower()
    platform = "instagram" if "instagram" in lower else "youtube"
    return {"platform": platform, "asset_dir": "", "title": "", "caption": ""}


def handle_social_stage_upload(text: str, context: Dict[str, Any]) -> ActionResult:
    stage = _parse_stage_input(text, context)
    platform = stage["platform"] or "youtube"

    payment_signal = detect_payment_signal(text)
    if payment_signal.matched:
        return ActionResult.fail(
            "Payment/checkout UI is blocked for social automation.",
            "social_stage_upload",
        )

    stage_url = _platform_upload_url(platform)
    open_ok = False
    page_url = stage_url
    try:
        from chintu_backend.automation.browser.browser_controller import get_browser_controller

        controller = get_browser_controller(
            headless=bool(context.get("_headless", False)),
            profile_name=_social_profile_name(context),
        )
        page = controller.open_url(stage_url)
        page_url = str(getattr(page, "url", "") or stage_url)
        open_ok = True
    except Exception as exc:
        logger.warning("Stage upload browser open failed: %s", exc)

    receipt_path = ""
    asset_dir = Path(stage["asset_dir"]).expanduser() if stage["asset_dir"] else None
    if asset_dir and asset_dir.exists():
        receipt_payload = {
            "platform": platform,
            "stage_url": page_url,
            "opened_browser": open_ok,
            "publish_submitted": False,
            "status": "draft_staged",
        }
        receipt = asset_dir / "stage_upload_receipt.json"
        receipt.write_text(json.dumps(receipt_payload, indent=2, ensure_ascii=True), encoding="utf-8")
        receipt_path = str(receipt)

    msg = (
        f"Draft staging ready for {platform}.\n"
        "- Browser staging page is open.\n"
        f"- Browser profile: {_social_profile_name(context)}\n"
        "- Upload/publish submission was NOT executed.\n"
        "- Next: run social_publish_post and confirm explicitly."
    )
    return ActionResult.ok(
        msg,
        {
            "platform": platform,
            "url": page_url,
            "draft_staged": True,
            "publish_submitted": False,
            "stage_receipt": receipt_path,
        },
        "social_stage_upload",
    )


def _extract_youtube_channel_name(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    patterns = [
        r"(?:channel named|channel name|name it|named)\s+['\"]?([^'\"]+)['\"]?",
        r"create youtube channel\s+['\"]?([^'\"]+)['\"]?",
        r"create a youtube channel\s+['\"]?([^'\"]+)['\"]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            value = str(match.group(1) or "").strip(" .:-")
            # Trim common follow-up instruction tails from natural language prompts.
            value = re.split(
                r"\s+(?:and|with|then|so|after|please|by)\s+",
                value,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .:-")
            if value:
                return value
    return ""


def _read_current_page(controller) -> Dict[str, str]:
    try:
        info = controller.get_page_info()
        return {
            "url": str(getattr(info, "url", "") or "").strip(),
            "title": str(getattr(info, "title", "") or "").strip(),
        }
    except Exception:
        return {"url": "", "title": ""}


def _is_google_auth_url(url: str) -> bool:
    low = str(url or "").lower()
    return ("accounts.google.com" in low) or ("/signin" in low and "google" in low) or ("challenge" in low)


def _find_interactive_ref(controller, tokens: List[str]) -> str:
    """Best-effort lookup of an interactive ref by visible text tokens."""
    try:
        listing = controller.list_interactive_elements(max_elements=180)
        elements = list((listing or {}).get("elements") or [])
    except Exception:
        return ""
    wants = [str(t or "").strip().lower() for t in tokens if str(t or "").strip()]
    if not wants:
        return ""
    for element in elements:
        role = str((element or {}).get("role") or "").strip().lower()
        text = str((element or {}).get("text") or "").strip().lower()
        ref = str((element or {}).get("ref") or "").strip()
        if not ref or role not in {"button", "link", "menuitem", "tab"}:
            continue
        if any(token in text for token in wants):
            return ref
    return ""


def _try_fill_channel_name(controller, channel_name: str) -> bool:
    value = str(channel_name or "").strip()
    if not value:
        return False
    # Never type channel names into sign-in/email pages.
    page = _read_current_page(controller)
    current_url = str(page.get("url") or "")
    if _is_google_auth_url(current_url):
        return False
    page_text = _safe_page_text(controller, max_length=3000).lower()
    if ("email or phone" in page_text and "sign in" in page_text) or (
        "to continue to youtube" in page_text and "sign in" in page_text
    ):
        return False
    selectors = [
        "input#name",
        "input#channel-name",
        "input[name='name']",
        "input[aria-label*='Name' i]",
        "input[placeholder*='name' i]",
    ]
    for selector in selectors:
        try:
            if controller.fill_input(selector, value):
                return True
        except Exception:
            continue
    # Accessibility fallback: textbox-like refs from structured DOM.
    try:
        listing = controller.list_interactive_elements(max_elements=220)
        for element in list((listing or {}).get("elements") or []):
            role = str((element or {}).get("role") or "").strip().lower()
            text = str((element or {}).get("text") or "").strip().lower()
            ref = str((element or {}).get("ref") or "").strip()
            if not ref:
                continue
            if role in {"textbox", "input"} or "name" in text or "channel" in text:
                acted = controller.act_by_ref(ref, action="fill", value=value, screenshot_after=False)
                if bool((acted or {}).get("success")):
                    return True
    except Exception:
        pass
    return False


def _assistant_google_credentials(context: Dict[str, Any]) -> tuple[str, str]:
    email = str(context.get("assistant_google_email") or "").strip()
    password = str(context.get("assistant_google_password") or "").strip()
    if email and password:
        return email, password
    email = str(
        os.environ.get("CHINTU_ASSISTANT_GOOGLE_EMAIL")
        or os.environ.get("CHINTU_ASSISTANT_EMAIL")
        or ""
    ).strip()
    password = str(
        os.environ.get("CHINTU_ASSISTANT_GOOGLE_PASSWORD")
        or os.environ.get("CHINTU_ASSISTANT_PASSWORD")
        or ""
    ).strip()
    return email, password


def _verify_channel_created(controller, channel_name: str) -> Dict[str, Any]:
    try:
        info = controller.open_url("https://studio.youtube.com/", wait_for="domcontentloaded")
        url = str(getattr(info, "url", "") or "")
        low_url = url.lower()
        if _is_google_auth_url(low_url):
            return {"verified": False, "reason": "not_authenticated", "url": url}

        page_text = str(controller.get_page_content(max_length=8000) or "")
        low_text = page_text.lower()
        wanted = str(channel_name or "").strip().lower()
        if wanted:
            if wanted in low_text:
                return {"verified": True, "reason": "name_match", "url": url}
            if any(marker in low_text for marker in ("create channel", "create a new channel", "start your channel")):
                return {"verified": False, "reason": "creation_not_finished", "url": url}
            return {"verified": False, "reason": "name_not_found", "url": url}

        if any(marker in low_text for marker in ("create channel", "start your channel")):
            return {"verified": False, "reason": "creation_not_finished", "url": url}

        if "studio.youtube.com" in low_url:
            return {"verified": True, "reason": "studio_active", "url": url}
        return {"verified": False, "reason": "unknown_state", "url": url}
    except Exception as exc:
        return {"verified": False, "reason": f"verify_error:{exc}", "url": ""}


def _safe_page_text(controller, max_length: int = 9000) -> str:
    try:
        return str(controller.get_page_content(max_length=max_length) or "")
    except Exception:
        return ""


def _click_by_tokens(controller, tokens: List[str]) -> bool:
    wants = [str(token or "").strip() for token in tokens if str(token or "").strip()]
    for token in wants:
        try:
            if controller.click_link(token):
                controller.wait_for_text(token, timeout_ms=1800)
                return True
        except Exception:
            continue
        try:
            ref = _find_interactive_ref(controller, [token])
            if ref:
                acted = controller.act_by_ref(ref, action="click", screenshot_after=False)
                if bool((acted or {}).get("success")):
                    return True
        except Exception:
            continue
        try:
            if controller.click_text_force(token):
                return True
        except Exception:
            continue
    return False


def _read_youtube_state(controller) -> Dict[str, Any]:
    page = _read_current_page(controller)
    url = str(page.get("url") or "")
    low_url = url.lower()
    text = _safe_page_text(controller).lower()
    try:
        listing = controller.list_interactive_elements(max_elements=220)
        elements = list((listing or {}).get("elements") or [])
    except Exception:
        elements = []

    interactive_text = " ".join(
        str((element or {}).get("text") or "").strip().lower() for element in elements
    )
    combined = f"{text}\n{interactive_text}"

    def has_token(*tokens: str) -> bool:
        return any(str(token).lower() in combined for token in tokens)

    likely_auth_text = has_token(
        "email or phone",
        "forgot email",
        "to continue to youtube",
        "sign in",
        "google account",
    )
    likely_post_login = has_token(
        "customize channel",
        "manage videos",
        "view channel",
        "create a channel",
        "channel name",
    )
    needs_auth = _is_google_auth_url(low_url) or (likely_auth_text and not likely_post_login)

    return {
        "url": url,
        "needs_auth": needs_auth,
        "is_feed_you": "youtube.com/feed/you" in low_url,
        "has_switch_account": has_token("switch account"),
        "has_view_all_channels": has_token("view all channels", "all channels"),
        "has_create_entry": has_token("create a channel", "create channel", "create a new channel"),
        "has_name_field": has_token("name", "channel name"),
        "has_handle_field": has_token("handle"),
        "has_view_channel": has_token("view channel"),
        "has_customize_channel": has_token("customize channel"),
        "has_manage_videos": has_token("manage videos"),
        "has_submit_create": has_token("create channel"),
    }


def _rename_existing_youtube_channel(controller, channel_name: str, opened_urls: List[str]) -> Dict[str, Any]:
    """Best-effort rename flow for already-created channels."""
    target = str(channel_name or "").strip()
    if not target:
        return {"attempted": False, "reason": "missing_name"}

    page = _read_current_page(controller)
    url = str(page.get("url") or "")
    low_url = url.lower()

    # Prefer in-session transition from YouTube page to Studio via existing buttons.
    if "studio.youtube.com" not in low_url:
        _click_by_tokens(controller, ["Customize channel", "Manage videos", "YouTube Studio"])
        page = _read_current_page(controller)
        url = str(page.get("url") or url)
        low_url = url.lower()

    # Fallback direct open to studio home in same profile.
    if "studio.youtube.com" not in low_url:
        try:
            info = controller.open_url("https://studio.youtube.com/", wait_for="domcontentloaded")
            url = str(getattr(info, "url", "") or "https://studio.youtube.com/")
            opened_urls.append(url)
            low_url = url.lower()
        except Exception:
            pass

    if "studio.youtube.com" not in low_url:
        return {"attempted": True, "reason": "studio_unavailable", "url": url}

    # Navigate to customization/basic info when available.
    _click_by_tokens(controller, ["Customization", "Channel customization"])
    _click_by_tokens(controller, ["Basic info", "Profile", "Channel"])

    filled = _try_fill_channel_name(controller, target)
    if not filled:
        try:
            filled = bool(controller.fill_visible_textbox(target, hint="name"))
        except Exception:
            filled = False

    saved = False
    if filled:
        saved = _click_by_tokens(controller, ["Publish", "Save", "Done"])

    # Wait briefly for UI settle and then verify against current Studio text.
    time.sleep(1.0)
    verification = _verify_channel_created(controller, target)
    return {
        "attempted": True,
        "url": _read_current_page(controller).get("url") or url,
        "filled": bool(filled),
        "saved": bool(saved),
        "verification": verification,
    }


def _advance_to_channel_form(controller, opened_urls: List[str]) -> Dict[str, Any]:
    """State machine for hostile YouTube SPA channel-creation flows."""
    for _ in range(8):
        state = _read_youtube_state(controller)
        if state.get("needs_auth"):
            return {"stage": "auth_required", "state": state}
        if bool(state.get("has_customize_channel")) or bool(state.get("has_manage_videos")):
            return {"stage": "existing_channel", "state": state}
        if bool(state.get("has_name_field")) and bool(state.get("has_submit_create")):
            return {"stage": "form_ready", "state": state}
        if bool(state.get("has_create_entry")) and _click_by_tokens(
            controller, ["Create a channel", "Create a new channel", "Create channel"]
        ):
            continue
        if bool(state.get("has_view_all_channels")) and _click_by_tokens(
            controller, ["View all channels", "All channels"]
        ):
            continue
        if bool(state.get("has_switch_account")) and _click_by_tokens(controller, ["Switch account"]):
            continue
        if not bool(state.get("is_feed_you")):
            try:
                info = controller.open_url("https://www.youtube.com/feed/you", wait_for="domcontentloaded")
                opened_urls.append(str(getattr(info, "url", "") or "https://www.youtube.com/feed/you"))
            except Exception:
                pass
            continue
        break
    return {"stage": "manual_required", "state": _read_youtube_state(controller)}


def handle_social_youtube_channel_setup(text: str, context: Dict[str, Any]) -> ActionResult:
    """Stateful YouTube channel setup using a persistent profile/browser session."""
    validated = context.get("_validated_params")
    profile_name = _social_profile_name(context)
    channel_name = ""
    if isinstance(validated, SocialYouTubeChannelSetupSchema):
        channel_name = str(validated.channel_name or "").strip()
    if not channel_name:
        channel_name = _extract_youtube_channel_name(text)
    if not channel_name:
        waiting_meta = context.get("_waiting_input_meta")
        if isinstance(waiting_meta, dict):
            channel_name = str(waiting_meta.get("channel_name") or "").strip()

    if bool(context.get("_resume_waiting_input")) and any(
        token in str(text or "").lower()
        for token in ("done", "continue", "resume", "created", "finished", "completed")
    ):
        try:
            from chintu_backend.automation.browser.browser_controller import get_browser_controller

            verify_controller = get_browser_controller(headless=False, profile_name=profile_name)
            verification = _verify_channel_created(verify_controller, channel_name)
        except Exception:
            verification = {"verified": False, "reason": "verify_unavailable", "url": ""}
            verify_controller = None
        rename_attempt: Dict[str, Any] = {}
        if (
            not bool(verification.get("verified"))
            and str(verification.get("reason") or "") == "name_not_found"
            and channel_name
            and verify_controller is not None
        ):
            try:
                rename_attempt = _rename_existing_youtube_channel(verify_controller, channel_name, opened_urls=[])
                post_verify = dict(rename_attempt.get("verification") or {})
                if post_verify:
                    verification = post_verify
            except Exception:
                rename_attempt = {"attempted": True, "reason": "rename_attempt_failed"}
        if not bool(verification.get("verified")):
            reason = str(verification.get("reason") or "verification_failed")
            return ActionResult.ok(
                (
                    "I could not verify the channel as created yet. "
                    f"Reason: {reason}. I kept the same browser session open. "
                    "Finish any remaining prompts, then say 'done, continue channel setup' again."
                ),
                {
                    "profile": profile_name,
                    "channel_name": channel_name,
                    "verification": verification,
                    "rename_attempt": rename_attempt,
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "youtube_channel_setup",
                    "manual_login_required": False,
                },
                "social_youtube_channel_setup",
            )
        return ActionResult.ok(
            "Great. I verified YouTube channel setup in your profile. We can proceed to content staging.",
            {
                "profile": profile_name,
                "channel_name": channel_name,
                "verification": verification,
                "rename_attempt": rename_attempt,
                "awaiting_user_action": False,
                "manual_login_required": False,
            },
            "social_youtube_channel_setup",
        )

    try:
        from chintu_backend.automation.browser.browser_controller import (
            get_browser_controller,
            get_open_browser_controller,
        )

        existing = get_open_browser_controller(headless=False, profile_name=profile_name)
        controller = existing or get_browser_controller(headless=False, profile_name=profile_name)
        active_profile = str(getattr(controller, "profile_name", "") or profile_name or "").strip() or profile_name
        if active_profile:
            profile_name = active_profile
        opened_urls: List[str] = []
        page = _read_current_page(controller) if getattr(controller, "is_open", False) else {"url": "", "title": ""}
        current_url = str(page.get("url") or "")

        # Keep session stable: only navigate when we need to.
        if not current_url:
            info = controller.open_url("https://www.youtube.com/", wait_for="domcontentloaded")
            current_url = str(getattr(info, "url", "") or "https://www.youtube.com/")
            opened_urls.append(current_url)

        if _is_google_auth_url(current_url):
            email, password = _assistant_google_credentials(context)
            if email and password:
                auto = controller.google_sign_in(email=email, password=password)
                if bool(auto.get("success")) and not bool(auto.get("needs_user_action")):
                    current_url = str(auto.get("url") or current_url)
                else:
                    reason = str(auto.get("error") or "additional_verification_required")
                    login_hint = [
                        "YouTube setup is at Google sign-in.",
                        f"Profile: {profile_name}",
                        "I attempted automatic sign-in and kept the same browser session open.",
                        f"Status: {reason}",
                        "Please complete any challenge/2FA in that window.",
                        "Then say: 'done, continue channel setup'.",
                    ]
                    if channel_name:
                        login_hint.append(f"Target channel name: {channel_name}")
                    return ActionResult.ok(
                        "\n".join(login_hint),
                        {
                            "profile": profile_name,
                            "channel_name": channel_name,
                            "opened_urls": opened_urls,
                            "manual_login_required": True,
                            "awaiting_user_action": True,
                            "awaiting_user_action_type": "youtube_channel_setup",
                            "next_step": "Complete Google verification, then say 'done, continue channel setup'.",
                        },
                        "social_youtube_channel_setup",
                    )

            refreshed = _read_current_page(controller)
            current_url = str(refreshed.get("url") or current_url)
            if _is_google_auth_url(current_url):
                login_hint = [
                    "YouTube setup is at Google sign-in.",
                    f"Profile: {profile_name}",
                    "I kept the same browser session open.",
                    "Please complete sign-in (including 2FA) in that window.",
                    "Then say: 'done, continue channel setup'.",
                ]
                if channel_name:
                    login_hint.append(f"Target channel name: {channel_name}")
                return ActionResult.ok(
                    "\n".join(login_hint),
                    {
                        "profile": profile_name,
                        "channel_name": channel_name,
                        "opened_urls": opened_urls,
                        "manual_login_required": True,
                        "awaiting_user_action": True,
                        "awaiting_user_action_type": "youtube_channel_setup",
                        "next_step": "Complete Google sign-in, then say 'done, continue channel setup'.",
                    },
                    "social_youtube_channel_setup",
                )

        if "youtube.com/feed/you" not in current_url.lower():
            info = controller.open_url("https://www.youtube.com/feed/you", wait_for="domcontentloaded")
            current_url = str(getattr(info, "url", "") or "https://www.youtube.com/feed/you")
            opened_urls.append(current_url)

        state_result = _advance_to_channel_form(controller, opened_urls)
        stage = str(state_result.get("stage") or "")
        state = dict(state_result.get("state") or {})
        if stage == "auth_required":
            return ActionResult.ok(
                (
                    "YouTube setup reached an authentication checkpoint. "
                    "Complete the login/challenge in the same browser window, then say "
                    "'done, continue channel setup'."
                ),
                {
                    "profile": profile_name,
                    "channel_name": channel_name,
                    "opened_urls": opened_urls,
                    "manual_login_required": True,
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "youtube_channel_setup",
                    "next_step": "Complete Google auth and say 'done, continue channel setup'.",
                },
                "social_youtube_channel_setup",
            )
        if stage == "existing_channel" and channel_name:
            rename_attempt = _rename_existing_youtube_channel(controller, channel_name, opened_urls)
            verification = dict(rename_attempt.get("verification") or {})
            if bool(verification.get("verified")):
                return ActionResult.ok(
                    "Channel already existed; I updated it to your requested name in the same profile session.",
                    {
                        "profile": profile_name,
                        "channel_name": channel_name,
                        "opened_urls": opened_urls,
                        "verification": verification,
                        "rename_attempt": rename_attempt,
                        "awaiting_user_action": False,
                        "manual_login_required": False,
                    },
                    "social_youtube_channel_setup",
                )
            return ActionResult.ok(
                (
                    "I detected an existing YouTube channel in this profile and attempted to rename it. "
                    "Please check the visible Studio form and click Publish/Save if prompted, then say "
                    "'done, continue channel setup'."
                ),
                {
                    "profile": profile_name,
                    "channel_name": channel_name,
                    "opened_urls": opened_urls,
                    "rename_attempt": rename_attempt,
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "youtube_channel_setup",
                    "next_step": "Confirm publish/save in Studio, then say 'done, continue channel setup'.",
                },
                "social_youtube_channel_setup",
            )
        if stage != "form_ready":
            return ActionResult.ok(
                (
                    "I kept the same browser and profile session open. "
                    "YouTube has not exposed the channel form yet, so I did not type anything into fields. "
                    "Complete the visible sign-in/channel chooser step, then say 'done, continue channel setup'."
                ),
                {
                    "profile": profile_name,
                    "channel_name": channel_name,
                    "opened_urls": opened_urls,
                    "stage": stage or "unknown",
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "youtube_channel_setup",
                    "next_step": "Complete visible step and say 'done, continue channel setup'.",
                },
                "social_youtube_channel_setup",
            )

        name_prefilled = _try_fill_channel_name(controller, channel_name)
        if not name_prefilled and channel_name:
            name_prefilled = bool(controller.fill_visible_textbox(channel_name, hint="name"))
        if not name_prefilled and bool(state.get("has_name_field")) and channel_name:
            try:
                name_ref = _find_interactive_ref(controller, ["name", "channel name"])
                if name_ref:
                    acted = controller.act_by_ref(name_ref, action="fill", value=channel_name, screenshot_after=False)
                    name_prefilled = bool((acted or {}).get("success"))
            except Exception:
                name_prefilled = False

        create_ref = _find_interactive_ref(
            controller,
            tokens=["create channel", "create", "continue", "done", "next"],
        )
        if not create_ref:
            try:
                submitted = False
                if hasattr(controller, "click_popup_button_exact"):
                    submitted = bool(controller.click_popup_button_exact("Create channel"))
                if not submitted:
                    submitted = bool(controller.click_text_force("Create channel"))
                if submitted:
                    # We already clicked final create action in-place.
                    time.sleep(1.0)
                    after_force = _read_current_page(controller)
                    return ActionResult.ok(
                        "Channel creation submit step executed in the same browser session. "
                        "If YouTube asks for extra steps (handle/photo), complete them and say 'done, continue channel setup'.",
                        {
                            "profile": profile_name,
                            "channel_name": channel_name,
                            "opened_urls": opened_urls,
                            "name_prefilled": name_prefilled,
                            "submit_clicked": True,
                            "url": str(after_force.get("url") or current_url),
                            "awaiting_user_action": True,
                            "awaiting_user_action_type": "youtube_channel_setup",
                            "next_step": "Finish any remaining YouTube prompts, then say 'done, continue channel setup'.",
                        },
                        "social_youtube_channel_setup",
                    )
            except Exception:
                pass
        if not create_ref and stage == "manual_required":
            return ActionResult.ok(
                (
                    "I kept the same profile session open but YouTube did not expose the channel form yet. "
                    "I am at the account/channel chooser flow. Complete the last visible step "
                    "(usually 'Switch account' -> 'View all channels' -> 'Create a channel'), "
                    "then say 'done, continue channel setup'."
                ),
                {
                    "profile": profile_name,
                    "channel_name": channel_name,
                    "opened_urls": opened_urls,
                    "name_prefilled": name_prefilled,
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "youtube_channel_setup",
                    "next_step": "Finish channel chooser steps and say 'done, continue channel setup'.",
                },
                "social_youtube_channel_setup",
            )
        if create_ref and not bool(context.get("_youtube_channel_submit_confirmed")):
            def pending_submit() -> ActionResult:
                next_ctx = dict(context or {})
                next_ctx["_youtube_channel_submit_confirmed"] = True
                return handle_social_youtube_channel_setup(text, next_ctx)

            return ActionResult.confirm(
                "I kept YouTube open and prepared channel creation. "
                "I can click the final 'Create channel' action now. Proceed?",
                pending_submit,
                "social_youtube_channel_setup",
            )

        if create_ref and bool(context.get("_youtube_channel_submit_confirmed")):
            acted = {"success": False}
            try:
                if hasattr(controller, "click_popup_button_exact") and controller.click_popup_button_exact("Create channel"):
                    acted = {
                        "success": True,
                        "ref": "popup:create-channel",
                        "action": "click",
                        "screenshot": "",
                    }
            except Exception:
                acted = {"success": False}
            if not bool(acted.get("success")):
                acted = controller.act_by_ref(create_ref, action="click", screenshot_after=True)
            time.sleep(1.2)
            after = _read_current_page(controller)
            return ActionResult.ok(
                "Channel creation submit step executed in the same browser session. "
                "If YouTube asks for extra steps (handle/photo), complete them and say 'done, continue channel setup'.",
                {
                    "profile": profile_name,
                    "channel_name": channel_name,
                    "opened_urls": opened_urls,
                    "name_prefilled": name_prefilled,
                    "submit_clicked": bool(acted.get("success")),
                    "screenshot": str(acted.get("screenshot") or ""),
                    "url": str(after.get("url") or current_url),
                    "awaiting_user_action": True,
                    "awaiting_user_action_type": "youtube_channel_setup",
                    "next_step": "Finish any remaining YouTube prompts, then say 'done, continue channel setup'.",
                },
                "social_youtube_channel_setup",
            )
    except Exception as exc:
        return ActionResult.fail(
            f"I couldn't open YouTube setup pages in profile '{profile_name}': {exc}",
            "social_youtube_channel_setup",
        )

    lines = [
        "I kept YouTube open in Chintu's browser profile and moved to channel setup.",
        f"Profile: {profile_name}",
        "Please complete any remaining channel prompts in that same window.",
    ]
    if channel_name:
        lines.append(f"Preferred channel name: {channel_name}")
    lines.append("I did not close or reopen the browser session.")
    lines.extend(
        [
            "",
            "When done, say: 'done, continue channel setup'.",
            "After that I can stage/upload content in the same profile.",
        ]
    )

    return ActionResult.ok(
        "\n".join(lines).strip(),
        {
            "profile": profile_name,
            "channel_name": channel_name,
            "opened_urls": opened_urls if "opened_urls" in locals() else [],
            "manual_login_required": True,
            "awaiting_user_action": True,
            "awaiting_user_action_type": "youtube_channel_setup",
            "next_step": "Say 'done, continue channel setup' after creating the channel.",
        },
        "social_youtube_channel_setup",
    )


def _parse_publish_input(text: str, context: Dict[str, Any]) -> Dict[str, str]:
    validated = context.get("_validated_params")
    if isinstance(validated, SocialPublishSchema):
        return {
            "platform": str(validated.platform).strip().lower() or "youtube",
            "asset_dir": str(validated.asset_dir or "").strip(),
        }
    lower = str(text or "").lower()
    platform = "instagram" if "instagram" in lower else "youtube"
    return {"platform": platform, "asset_dir": ""}


def handle_social_publish_post(text: str, context: Dict[str, Any]) -> ActionResult:
    payload = _parse_publish_input(text, context)
    platform = payload["platform"] or "youtube"
    payment_signal = detect_payment_signal(text)
    if payment_signal.matched:
        return ActionResult.fail(
            "Payment/checkout UI is blocked for social automation.",
            "social_publish_post",
        )

    categories = detect_action_categories("social_publish_post", text, context)
    if "browser_submit" not in categories:
        categories.append("browser_submit")

    if not context.get("_publish_confirmed"):
        def pending() -> ActionResult:
            next_ctx = dict(context or {})
            next_ctx["_publish_confirmed"] = True
            return handle_social_publish_post(text, next_ctx)

        return ActionResult.confirm(
            (
                f"Publishing to {platform} is sensitive and requires explicit confirmation.\n"
                "I will not execute any transaction actions.\n\nProceed with publish approval?"
            ),
            pending,
            "social_publish_post",
        )

    receipt_path = ""
    asset_dir = Path(payload["asset_dir"]).expanduser() if payload["asset_dir"] else None
    if asset_dir and asset_dir.exists():
        receipt_payload = {
            "platform": platform,
            "approved": True,
            "publish_submitted": False,
            "categories": categories,
            "status": "approval_captured_only",
        }
        receipt = asset_dir / "publish_receipt.json"
        receipt.write_text(json.dumps(receipt_payload, indent=2, ensure_ascii=True), encoding="utf-8")
        receipt_path = str(receipt)

    return ActionResult.ok(
        (
            f"Publish confirmation captured for {platform}.\n"
            "Final submit remains explicit/manual by design.\n"
            "No transaction action was executed."
        ),
        {
            "platform": platform,
            "approved": True,
            "publish_submitted": False,
            "receipt_path": receipt_path,
        },
        "social_publish_post",
    )


def register_social_content_capabilities(registry) -> None:
    registry.register(
        Capability(
            name="social_content_pipeline",
            triggers=[
                "social content campaign",
                "create a social content campaign",
                "social content pipeline",
                "create social campaign",
                "prepare reels content",
                "prepare shorts content",
            ],
            handler=handle_social_content_pipeline,
            requires_confirmation=False,
            description="generate script/captions/hashtags/thumbnail prompt/schedule checklist",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Create social campaign about local AI workflows for YouTube and Instagram"],
            schema=SocialContentPipelineSchema,
        )
    )
    registry.register(
        Capability(
            name="social_youtube_channel_setup",
            triggers=[
                "create youtube channel",
                "set up youtube channel",
                "setup youtube channel",
                "create channel for chintu",
                "open youtube channel setup",
            ],
            handler=handle_social_youtube_channel_setup,
            requires_confirmation=False,
            description="open YouTube channel setup flow in Chintu browser profile and wait for user completion",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Create a YouTube channel named Chintu AI in your profile"],
            schema=SocialYouTubeChannelSetupSchema,
        )
    )
    registry.register(
        Capability(
            name="social_stage_upload",
            triggers=[
                "stage upload",
                "prepare social draft",
                "open upload studio",
            ],
            handler=handle_social_stage_upload,
            requires_confirmation=False,
            description="stage browser draft upload without publishing",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Stage upload for youtube using campaign folder C:\\path"],
            schema=SocialStageUploadSchema,
        )
    )
    registry.register(
        Capability(
            name="social_publish_post",
            triggers=[
                "publish post",
                "publish youtube post",
                "publish the youtube post",
                "publish instagram post",
                r"publish\s+(?:the\s+)?(?:youtube|instagram)?\s*post",
                "publish reel",
                "publish short",
                "submit social post",
            ],
            handler=handle_social_publish_post,
            requires_confirmation=False,
            description="explicit publish approval gate",
            capability_type=CapabilityType.AUTOMATION,
            examples=["Publish post on instagram from campaign folder C:\\path"],
            schema=SocialPublishSchema,
        )
    )
