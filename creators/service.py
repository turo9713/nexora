from __future__ import annotations

import json
import re
import secrets
import sqlite3
from typing import Any

from nexora.integrations.telegram_runtime.services.progress_service import utc_now
from nexora.marketplace import MarketplaceError, MarketplaceService
from nexora.marketplace.validation import PackageValidationError, PackageValidator
from nexora.security.audit.redaction import redact_text, sanitize_metadata


CREATOR_ID = re.compile(r"^CRT-[A-F0-9]{12}$")
AVATAR_REFERENCE = re.compile(r"^(?:avatar|asset):[A-Za-z0-9._-]{1,120}$")
TRUSTED_METRIC_SOURCES = {"agent_runner", "workflow_engine"}


class CreatorError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CreatorService:
    """Creator control plane; package execution and payments are intentionally absent."""

    def __init__(self, database: Any, marketplace: MarketplaceService, teams: Any, policy: Any, audit: Any, administrator: str | None = None) -> None:
        self.database = database
        self.marketplace = marketplace
        self.teams = teams
        self.policy = policy
        self.audit = audit
        self.administrator = administrator
        self.validator = PackageValidator()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{secrets.token_hex(6).upper()}"

    def create_profile(self, actor: str, display_name: str, bio: str = "", avatar_reference: str | None = None) -> dict[str, Any]:
        if self.database.get_creator_for_owner(actor) is not None:
            raise CreatorError("CREATOR_ALREADY_EXISTS")
        name = self._text(display_name, 100, minimum=2)
        clean_bio = self._text(bio, 1000, minimum=0)
        avatar = self._avatar(avatar_reference)
        publishers = self.database.list_publishers(actor)
        if publishers:
            publisher = publishers[0]
        else:
            try:
                publisher = self.marketplace.register_publisher(actor, name)
            except MarketplaceError as exc:
                raise CreatorError(exc.code) from exc
        now = utc_now()
        profile = self.database.create_creator_profile({"id":self._id("CRT"),"owner":actor,"publisher_id":publisher["id"],"display_name":name,"bio":clean_bio,"avatar_reference":avatar,"status":"ACTIVE","created_at":now,"updated_at":now})
        self.audit.record("CREATOR_CREATED",source="creator_service",action_result="SUCCESS",creator_id=profile["id"])
        return self._safe_profile(profile, include_private=True)

    def profile(self, creator_id: str) -> dict[str, Any]:
        if not CREATOR_ID.fullmatch(str(creator_id)):
            raise CreatorError("CREATOR_NOT_FOUND")
        profile = self.database.get_creator_profile(creator_id)
        if profile is None or profile.get("status") in {"BLOCKED","SUSPENDED"}:
            raise CreatorError("CREATOR_NOT_FOUND")
        analytics = self.database.creator_analytics(creator_id)
        return {**self._safe_profile(profile),"packages":analytics["packages"],"downloads":analytics["total_installs"],"rating":analytics["rating"],"verified":profile.get("level") in {"VERIFIED_CREATOR","TRUSTED_CREATOR"}}

    def my_profile(self, actor: str) -> dict[str, Any]:
        profile = self._own(actor)
        return {**self._safe_profile(profile, include_private=True),"analytics":self.database.creator_analytics(profile["id"])}

    def update_profile(self, actor: str, *, display_name: str | None = None, bio: str | None = None, avatar_reference: str | None = None) -> dict[str, Any]:
        profile = self._own(actor, writable=True)
        self.database.update_creator_profile(profile["id"],display_name=None if display_name is None else self._text(display_name,100,minimum=2),bio=None if bio is None else self._text(bio,1000,minimum=0),avatar_reference=None if avatar_reference is None else self._avatar(avatar_reference))
        return self.my_profile(actor)

    def set_profile_status(self, actor: str, creator_id: str, status: str, approval_id: str) -> dict[str, Any]:
        self._admin(actor)
        normalized=str(status).upper()
        if normalized not in {"ACTIVE","SUSPENDED","BLOCKED"}:
            raise CreatorError("CREATOR_STATUS_INVALID")
        self._approval(actor,approval_id,f"creator:status:{creator_id}:{normalized}")
        profile=self.database.get_creator_profile(creator_id)
        if profile is None:
            raise CreatorError("CREATOR_NOT_FOUND")
        self._policy("HIGH",True)
        self.database.update_creator_profile(creator_id,status=normalized)
        if normalized in {"SUSPENDED","BLOCKED"}:
            self.database.set_publisher_status(profile["publisher_id"],"SUSPENDED")
        self.audit.record("CREATOR_STATUS_CHANGED",severity="SECURITY",source="creator_service",action_result=normalized,creator_id=creator_id)
        return self._safe_profile(self.database.get_creator_profile(creator_id) or {},include_private=True)

    def grant_verification(self, actor: str, creator_id: str, level: str, approval_id: str) -> dict[str, Any]:
        self._admin(actor)
        normalized=str(level).upper()
        if normalized not in {"VERIFIED_CREATOR","TRUSTED_CREATOR"}:
            raise CreatorError("CREATOR_VERIFICATION_INVALID")
        profile=self.database.get_creator_profile(creator_id)
        if profile is None or profile.get("status") in {"BLOCKED","SUSPENDED"}:
            raise CreatorError("CREATOR_NOT_FOUND")
        if normalized == "TRUSTED_CREATOR" and not self._trusted_eligible(creator_id):
            raise CreatorError("CREATOR_TRUST_CRITERIA_NOT_MET")
        self._approval(actor,approval_id,f"creator:verification:{creator_id}:{normalized}")
        self._policy("HIGH",True)
        now=utc_now()
        self.database.set_creator_verification(creator_id,normalized,"ACTIVE",now)
        self.database.update_creator_profile(creator_id,status="VERIFIED")
        self.database.set_publisher_status(profile["publisher_id"],"VERIFIED")
        self.audit.record("VERIFICATION_GRANTED",source="creator_service",action_result=normalized,creator_id=creator_id)
        return self._safe_profile(self.database.get_creator_profile(creator_id) or {},include_private=True)

    def revoke_verification(self, actor: str, creator_id: str, approval_id: str) -> dict[str, Any]:
        self._admin(actor)
        self._approval(actor,approval_id,f"creator:verification_revoke:{creator_id}")
        profile=self.database.get_creator_profile(creator_id)
        if profile is None:
            raise CreatorError("CREATOR_NOT_FOUND")
        self._policy("HIGH",True)
        self.database.set_creator_verification(creator_id,"NEW_CREATOR","REVOKED",None)
        self.database.update_creator_profile(creator_id,status="ACTIVE")
        self.database.set_publisher_status(profile["publisher_id"],"SUSPENDED")
        self.audit.record("VERIFICATION_REVOKED",severity="SECURITY",source="creator_service",action_result="REVOKED",creator_id=creator_id)
        return self._safe_profile(self.database.get_creator_profile(creator_id) or {},include_private=True)

    def create_draft(self, actor: str, manifest: dict[str, Any], changelog: str = "") -> dict[str, Any]:
        profile=self._own(actor,writable=True)
        validated=self._validate(manifest)
        clean_changelog=self._text(changelog,2000,minimum=0)
        now=utc_now()
        value={"id":self._id("VER"),"package_id":validated.manifest["id"],"creator_id":profile["id"],"version":validated.manifest["version"],"manifest":validated.canonical,"checksum":validated.checksum,"changelog":clean_changelog,"compatibility":json.dumps(validated.manifest["compatibility"],sort_keys=True,separators=(",",":")),"status":"DRAFT","created_at":now,"updated_at":now,"published_at":None}
        try:
            self.database.insert_creator_package_version(value)
        except sqlite3.IntegrityError as exc:
            raise CreatorError("CREATOR_VERSION_EXISTS") from exc
        self.audit.record("PACKAGE_DRAFT_CREATED",source="creator_service",action_result="DRAFT",creator_id=profile["id"],package_id=value["package_id"],version=value["version"])
        return self._safe_version(value)

    def update_draft(self, actor: str, package_id: str, version: str, manifest: dict[str, Any], changelog: str = "") -> dict[str, Any]:
        profile=self._own(actor,writable=True)
        current=self._version(profile["id"],package_id,version)
        if current["status"] != "DRAFT":
            raise CreatorError("CREATOR_VERSION_IMMUTABLE")
        validated=self._validate(manifest)
        if validated.manifest["id"] != package_id or validated.manifest["version"] != version:
            raise CreatorError("CREATOR_VERSION_ID_MISMATCH")
        self.database.update_creator_package_version(profile["id"],package_id,version,manifest=validated.canonical,checksum=validated.checksum,changelog=self._text(changelog,2000,minimum=0),compatibility=json.dumps(validated.manifest["compatibility"],sort_keys=True,separators=(",",":")))
        self.audit.record("PACKAGE_UPDATED",source="creator_service",action_result="DRAFT",creator_id=profile["id"],package_id=package_id,version=version)
        return self._safe_version(self._version(profile["id"],package_id,version))

    def submit(self, actor: str, package_id: str, version: str) -> dict[str, Any]:
        profile=self._own(actor,writable=True); current=self._version(profile["id"],package_id,version)
        if current["status"] != "DRAFT": raise CreatorError("CREATOR_VERSION_STATE_INVALID")
        self.database.update_creator_package_version(profile["id"],package_id,version,status="SUBMITTED")
        return self._safe_version(self._version(profile["id"],package_id,version))

    def validate_version(self, actor: str, package_id: str, version: str) -> dict[str, Any]:
        profile=self._own(actor,writable=True); current=self._version(profile["id"],package_id,version)
        if current["status"] != "SUBMITTED": raise CreatorError("CREATOR_VERSION_STATE_INVALID")
        self.database.update_creator_package_version(profile["id"],package_id,version,status="VALIDATING")
        try: self._validate(json.loads(current["manifest"]))
        except CreatorError:
            self.database.update_creator_package_version(profile["id"],package_id,version,status="FAILED"); raise
        self.database.update_creator_package_version(profile["id"],package_id,version,status="APPROVED")
        return self._safe_version(self._version(profile["id"],package_id,version))

    def publish(self, actor: str, package_id: str, version: str) -> dict[str, Any]:
        profile=self._own(actor,writable=True); current=self._version(profile["id"],package_id,version)
        if profile.get("level") not in {"VERIFIED_CREATOR","TRUSTED_CREATOR"} or profile.get("verification_status") != "ACTIVE": raise CreatorError("CREATOR_VERIFICATION_REQUIRED")
        if current["status"] != "APPROVED": raise CreatorError("CREATOR_VERSION_STATE_INVALID")
        try: item=self.marketplace.publish(actor,profile["publisher_id"],json.loads(current["manifest"]))
        except MarketplaceError as exc: raise CreatorError(exc.code) from exc
        now=utc_now(); self.database.update_creator_package_version(profile["id"],package_id,version,status="PUBLISHED",published_at=now)
        self.quality(actor,package_id,version)
        self.audit.record("VERSION_RELEASED",source="creator_service",action_result="PUBLISHED",creator_id=profile["id"],package_id=package_id,version=version)
        return {"item":item,"version":self._safe_version(self._version(profile["id"],package_id,version))}

    def archive(self, actor: str, package_id: str, version: str, approval_id: str) -> dict[str, Any]:
        profile=self._own(actor,writable=True); current=self._version(profile["id"],package_id,version)
        if current["status"] != "PUBLISHED": raise CreatorError("CREATOR_VERSION_STATE_INVALID")
        self._approval(actor,approval_id,f"creator:archive:{package_id}:{version}"); self._policy("HIGH",True)
        self.database.update_creator_package_version(profile["id"],package_id,version,status="ARCHIVED")
        self.database.set_marketplace_item_status(package_id,"DISABLED")
        self.audit.record("PACKAGE_ARCHIVED",source="creator_service",action_result="ARCHIVED",package_id=package_id,version=version)
        return self._safe_version(self._version(profile["id"],package_id,version))

    def rollback(self, actor: str, package_id: str, version: str, approval_id: str) -> dict[str, Any]:
        profile=self._own(actor,writable=True); target=self._version(profile["id"],package_id,version)
        if target["status"] not in {"PUBLISHED","ARCHIVED"}: raise CreatorError("CREATOR_ROLLBACK_TARGET_INVALID")
        self._approval(actor,approval_id,f"creator:rollback:{package_id}:{version}"); self._policy("HIGH",True)
        if not self.database.set_marketplace_current_version(package_id,version): raise CreatorError("CREATOR_ROLLBACK_TARGET_INVALID")
        self.database.set_marketplace_item_status(package_id,"PUBLISHED")
        self.audit.record("VERSION_ROLLED_BACK",source="creator_service",action_result="SUCCESS",package_id=package_id,version=version)
        return self.marketplace.item(package_id)

    def packages(self, actor: str) -> list[dict[str, Any]]:
        profile=self._own(actor)
        return self.database.list_creator_package_versions(profile["id"])

    def analytics(self, actor: str) -> dict[str, Any]:
        profile=self._own(actor)
        return {"summary":self.database.creator_analytics(profile["id"]),"packages":self.database.creator_package_analytics(profile["id"])}

    def record_execution(self, creator_id: str, package_id: str, *, success: bool, source: str) -> None:
        if source not in TRUSTED_METRIC_SOURCES: raise CreatorError("CREATOR_METRIC_SOURCE_DENIED")
        if self.database.get_creator_profile(creator_id) is None or self.database.get_marketplace_item(package_id) is None: raise CreatorError("CREATOR_METRIC_TARGET_INVALID")
        for metric,value in (("EXECUTION",1),("SUCCESS" if success else "ERROR",1)):
            self.database.record_creator_metric({"id":self._id("CME"),"creator_id":creator_id,"package_id":package_id,"metric":metric,"value":value,"result":"SUCCESS" if success else "ERROR","created_at":utc_now()})

    def quality(self, actor: str, package_id: str, version: str) -> dict[str, Any]:
        profile=self._own(actor); current=self._version(profile["id"],package_id,version)
        manifest=json.loads(current["manifest"]); package_stats=next((x for x in self.database.creator_package_analytics(profile["id"]) if x["id"]==package_id),None) or {"success_rate":100.0,"rating":0.0}
        security=100 if manifest.get("security",{}).get("sandbox") is True and current["status"] in {"APPROVED","PUBLISHED","ARCHIVED"} else 0
        compatibility=100 if manifest.get("compatibility",{}).get("minimum_nexora") else 0
        reliability=max(0,min(100,round(float(package_stats["success_rate"]))))
        rating=float(package_stats["rating"]); rating_score=round(rating*20) if rating else 80
        score=round(security*0.35+compatibility*0.20+reliability*0.25+rating_score*0.20)
        grade="A+" if score>=95 else "A" if score>=90 else "B" if score>=80 else "C" if score>=70 else "D" if score>=60 else "F"
        value={"package_id":package_id,"version":version,"security_score":security,"compatibility_score":compatibility,"reliability_score":reliability,"user_rating":rating,"score":score,"grade":grade,"updated_at":utc_now()}
        self.database.upsert_quality_score(value); self.audit.record("QUALITY_UPDATED",source="creator_service",action_result=grade,package_id=package_id,version=version)
        return value

    def vote_review(self, actor: str, workspace_id: str, review_id: str, helpful: bool) -> dict[str, Any]:
        context=self.teams.workspace_context(actor,workspace_id,"tasks:read"); review=self.database.review_for_vote(review_id)
        if review is None: raise CreatorError("REVIEW_NOT_FOUND")
        if int(review["user_id"]) == int(context["user_id"]): raise CreatorError("REVIEW_SELF_VOTE_DENIED")
        installation=self.database.get_marketplace_installation(workspace_id,review["item_id"],review["version"])
        if installation is None or installation.get("status") != "ACTIVE": raise CreatorError("REVIEW_NOT_FOUND")
        self.database.add_review_vote(review_id,context["user_id"],1 if helpful else -1)
        return self.database.review_for_vote(review_id) or {}

    def _trusted_eligible(self, creator_id: str) -> bool:
        analytics=self.database.creator_analytics(creator_id); versions=self.database.list_creator_package_versions(creator_id)
        return sum(1 for item in versions if item["status"]=="PUBLISHED")>=3 and analytics["success_rate"]>=95 and (analytics["rating"]>=4.0 or analytics["reviews"]==0) and not any(item["status"]=="FAILED" for item in versions)

    def _own(self, actor: str, writable: bool=False) -> dict[str, Any]:
        profile=self.database.get_creator_for_owner(actor)
        if profile is None or (writable and profile.get("status") in {"SUSPENDED","BLOCKED"}):
            self.audit.record("CREATOR_ACCESS_DENIED",severity="SECURITY",source="creator_service",action_result="BLOCKED")
            raise CreatorError("CREATOR_NOT_FOUND")
        return profile

    def _admin(self, actor: str) -> None:
        if self.administrator is None or not secrets.compare_digest(actor,self.administrator): raise CreatorError("CREATOR_ADMIN_DENIED")

    def _approval(self, actor: str, approval_id: str, action: str) -> None:
        if not re.fullmatch(r"APR-[A-Za-z0-9-]{6,64}",str(approval_id)) or not self.database.consume_team_approval(actor,approval_id,action): raise CreatorError("CREATOR_APPROVAL_REQUIRED")

    def _policy(self, risk: str, approved: bool) -> None:
        decision=self.policy.evaluate("orchestrator",risk=risk,action_type="configuration_changes",approval_granted=approved)
        if not decision.allowed: raise CreatorError("CREATOR_POLICY_DENIED")

    def _version(self, creator_id: str, package_id: str, version: str) -> dict[str, Any]:
        value=self.database.get_creator_package_version(creator_id,package_id,version)
        if value is None: raise CreatorError("CREATOR_VERSION_NOT_FOUND")
        return value

    def _validate(self, manifest: dict[str, Any]):
        try: result=self.validator.validate(manifest)
        except PackageValidationError as exc: raise CreatorError(str(exc)) from exc
        if redact_text(result.canonical,len(result.canonical)+1) != result.canonical: raise CreatorError("CREATOR_SECRET_DETECTED")
        return result

    @staticmethod
    def _text(value: str, limit: int, minimum: int) -> str:
        clean=" ".join(str(value).replace("\x00","").split())[:limit]
        if len(clean)<minimum or redact_text(clean,limit+1)!=clean: raise CreatorError("CREATOR_TEXT_INVALID")
        return clean

    @staticmethod
    def _avatar(value: str | None) -> str | None:
        if value is None or value=="": return None
        if not AVATAR_REFERENCE.fullmatch(str(value)): raise CreatorError("CREATOR_AVATAR_INVALID")
        return str(value)

    @staticmethod
    def _safe_profile(value: dict[str, Any], include_private: bool=False) -> dict[str, Any]:
        keys=("id","display_name","bio","avatar_reference","status","level","verification_status","verified_at","created_at","updated_at")
        result={key:value.get(key) for key in keys}
        if include_private: result["publisher_id"]=value.get("publisher_id")
        return result

    @staticmethod
    def _safe_version(value: dict[str, Any]) -> dict[str, Any]:
        return {key:value.get(key) for key in ("id","package_id","version","checksum","changelog","compatibility","status","created_at","updated_at","published_at")}
