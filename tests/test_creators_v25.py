from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexora.agents.registry import AgentRegistry
from nexora.collaboration import TeamService
from nexora.creators import CreatorError, CreatorService
from nexora.database import SQLiteRepository
from nexora.integrations.telegram_runtime.services.audit_service import AuditService
from nexora.integrations.telegram_runtime.storage.audit_repository import AuditRepository
from nexora.marketplace import MarketplaceService
from nexora.security.policies import PolicyEngine
from nexora.dashboard.auth.passwords import hash_password
from nexora.dashboard.auth import Session
from nexora.dashboard.backend.server import DashboardConfig, create_application


PROJECT=Path(__file__).resolve().parents[1]
ADMIN="a"*32
CREATOR="b"*32
CONSUMER="c"*32
VOTER="d"*32
OUTSIDER="e"*32


def platform(tmp_path: Path):
    database=SQLiteRepository(tmp_path/"state"/"nexora.sqlite3"); database.migrate()
    agents=AgentRegistry(PROJECT/"agents").load(); policy=PolicyEngine(agents,PROJECT,status_resolver=database.agent_enabled)
    audit_repository=AuditRepository(tmp_path/"audit"); audit=AuditService(audit_repository,database=database)
    teams=TeamService(database,policy,audit); marketplace=MarketplaceService(database,teams,policy,audit)
    creators=CreatorService(database,marketplace,teams,policy,audit,administrator=ADMIN)
    return database,teams,marketplace,creators,audit_repository


def approval(database: SQLiteRepository, owner: str, action: str, suffix: str) -> str:
    now=datetime.now(timezone.utc).isoformat(); task_id=f"NX-CREATOR-{suffix}"; approval_id=f"APR-{suffix:0<8}"[:12]
    database.upsert_task({"task_id":task_id,"owner_namespace":owner,"title":"Creator approval","status":"WAITING_APPROVAL","progress":50,"assigned_agent":"Orchestrator","created_at":now,"updated_at":now,"completed_at":None,"result_summary":"","error_code":None})
    database.upsert_approval({"approval_id":approval_id,"task_id":task_id,"owner_namespace":owner,"action_type":action,"status":"APPROVED","expires_at":"2099-01-01T00:00:00+00:00","used_at":now})
    return approval_id


def manifest(item_id: str, version: str="1.0.0") -> dict:
    return {"id":item_id,"name":item_id.replace("-"," ").title(),"type":"SKILL","version":version,"author":"AI Studio","description":"Safe creator package","category":"creator","permissions":{"filesystem":{"scope":"workspace"},"network":{"mode":"none"},"shell":False},"risk_level":"LOW","requirements":[],"compatibility":{"minimum_nexora":"2.5.0"},"security":{"sandbox":True,"secret_access":False,"docker_access":False}}


def verified(database: SQLiteRepository, creators: CreatorService) -> dict:
    profile=creators.create_profile(CREATOR,"AI Studio","Security-first creator","avatar:ai-studio")
    grant=approval(database,ADMIN,f"creator:verification:{profile['id']}:VERIFIED_CREATOR","VERIFY01")
    return creators.grant_verification(ADMIN,profile["id"],"VERIFIED_CREATOR",grant)


def release(creators: CreatorService, item_id: str, version: str="1.0.0") -> dict:
    creators.create_draft(CREATOR,manifest(item_id,version),f"Release {version}")
    assert creators.submit(CREATOR,item_id,version)["status"]=="SUBMITTED"
    assert creators.validate_version(CREATOR,item_id,version)["status"]=="APPROVED"
    return creators.publish(CREATOR,item_id,version)


def workspace(teams: TeamService, actor: str, label: str):
    organization=teams.create_organization(actor,f"{label} Organization")
    return teams.create_workspace(actor,organization["id"],f"{label} Workspace")


def test_profile_creation_public_view_settings_isolation_and_suspension(tmp_path: Path) -> None:
    database,_,_,creators,audit=platform(tmp_path)
    profile=creators.create_profile(CREATOR,"AI Studio","Builds safe agents","avatar:studio")
    public=creators.profile(profile["id"])
    assert public["packages"]==0 and public["downloads"]==0 and public["verified"] is False
    assert "publisher_id" not in public and CREATOR not in json.dumps(public)
    updated=creators.update_profile(CREATOR,bio="Updated safe profile")
    assert updated["bio"]=="Updated safe profile"
    with pytest.raises(CreatorError,match="CREATOR_NOT_FOUND"): creators.my_profile(OUTSIDER)
    suspend=approval(database,ADMIN,f"creator:status:{profile['id']}:SUSPENDED","SUSPEND1")
    assert creators.set_profile_status(ADMIN,profile["id"],"SUSPENDED",suspend)["status"]=="SUSPENDED"
    with pytest.raises(CreatorError,match="CREATOR_NOT_FOUND"): creators.profile(profile["id"])
    assert "b"*32 not in audit.path.read_text(encoding="utf-8")


def test_verification_is_approved_one_time_and_revocable(tmp_path: Path) -> None:
    database,_,_,creators,_=platform(tmp_path)
    profile=creators.create_profile(CREATOR,"AI Studio")
    grant=approval(database,ADMIN,f"creator:verification:{profile['id']}:VERIFIED_CREATOR","VERIFY02")
    result=creators.grant_verification(ADMIN,profile["id"],"VERIFIED_CREATOR",grant)
    assert result["level"]=="VERIFIED_CREATOR" and result["status"]=="VERIFIED"
    with pytest.raises(CreatorError,match="CREATOR_APPROVAL_REQUIRED"): creators.grant_verification(ADMIN,profile["id"],"VERIFIED_CREATOR",grant)
    revoke=approval(database,ADMIN,f"creator:verification_revoke:{profile['id']}","REVOKE01")
    assert creators.revoke_verification(ADMIN,profile["id"],revoke)["verification_status"]=="REVOKED"
    with pytest.raises(CreatorError,match="CREATOR_ADMIN_DENIED"): creators.grant_verification(OUTSIDER,profile["id"],"VERIFIED_CREATOR","APR-X000000")


def test_draft_validation_semver_publish_versions_immutability_and_rollback(tmp_path: Path) -> None:
    database,_,marketplace,creators,_=platform(tmp_path); verified(database,creators)
    first=creators.create_draft(CREATOR,manifest("seo-studio"),"Initial release")
    changed=manifest("seo-studio"); changed["description"]="Updated draft metadata"
    assert creators.update_draft(CREATOR,"seo-studio","1.0.0",changed,"Updated")["checksum"]!=first["checksum"]
    creators.submit(CREATOR,"seo-studio","1.0.0"); creators.validate_version(CREATOR,"seo-studio","1.0.0"); creators.publish(CREATOR,"seo-studio","1.0.0")
    with pytest.raises(CreatorError,match="CREATOR_VERSION_IMMUTABLE"): creators.update_draft(CREATOR,"seo-studio","1.0.0",changed)
    release(creators,"seo-studio","1.1.0")
    assert marketplace.item("seo-studio")["version"]=="1.1.0"
    rollback=approval(database,CREATOR,"creator:rollback:seo-studio:1.0.0","ROLLBACK")
    assert creators.rollback(CREATOR,"seo-studio","1.0.0",rollback)["version"]=="1.0.0"
    with sqlite3.connect(database.path) as connection:
        with pytest.raises(sqlite3.IntegrityError): connection.execute("UPDATE package_versions SET checksum='tampered' WHERE package_id='seo-studio' AND version='1.0.0'")
        with pytest.raises(sqlite3.IntegrityError): connection.execute("UPDATE packages SET checksum='tampered' WHERE item_id='seo-studio'")


def test_analytics_quality_reviews_votes_and_isolation(tmp_path: Path) -> None:
    database,teams,marketplace,creators,_=platform(tmp_path); profile=verified(database,creators); release(creators,"analytics-skill")
    consumer_ws=workspace(teams,CONSUMER,"Consumer"); voter_ws=workspace(teams,VOTER,"Voter")
    marketplace.install(CONSUMER,consumer_ws["id"],"analytics-skill"); marketplace.install(VOTER,voter_ws["id"],"analytics-skill")
    review=marketplace.review(CONSUMER,consumer_ws["id"],"analytics-skill",5,"Excellent")
    with pytest.raises(CreatorError,match="REVIEW_SELF_VOTE_DENIED"): creators.vote_review(CONSUMER,consumer_ws["id"],review["id"],True)
    assert creators.vote_review(VOTER,voter_ws["id"],review["id"],True)["helpful"]==1
    creators.record_execution(profile["id"],"analytics-skill",success=True,source="agent_runner")
    creators.record_execution(profile["id"],"analytics-skill",success=False,source="workflow_engine")
    analytics=creators.analytics(CREATOR)
    assert analytics["summary"]["total_installs"]==2 and analytics["summary"]["executions"]==2 and analytics["summary"]["rating"]==5.0
    assert analytics["packages"][0]["success_rate"]==50.0
    score=creators.quality(CREATOR,"analytics-skill","1.0.0")
    assert score["security_score"]==100 and score["grade"] in {"A","B"}
    with pytest.raises(CreatorError,match="CREATOR_NOT_FOUND"): creators.analytics(OUTSIDER)
    with pytest.raises(CreatorError,match="CREATOR_METRIC_SOURCE_DENIED"): creators.record_execution(profile["id"],"analytics-skill",success=True,source="api_client")


def test_trusted_creator_criteria_and_archive(tmp_path: Path) -> None:
    database,_,marketplace,creators,_=platform(tmp_path); profile=verified(database,creators)
    for item in ("creator-one","creator-two","creator-three"): release(creators,item)
    trusted=approval(database,ADMIN,f"creator:verification:{profile['id']}:TRUSTED_CREATOR","TRUSTED1")
    assert creators.grant_verification(ADMIN,profile["id"],"TRUSTED_CREATOR",trusted)["level"]=="TRUSTED_CREATOR"
    archive=approval(database,CREATOR,"creator:archive:creator-one:1.0.0","ARCHIVE1")
    assert creators.archive(CREATOR,"creator-one","1.0.0",archive)["status"]=="ARCHIVED"
    assert not marketplace.catalog(search="creator-one")


def test_migration_009_backup_integrity_and_rollback(tmp_path: Path) -> None:
    database,_,_,creators,_=platform(tmp_path); creators.create_profile(CREATOR,"Rollback Creator")
    backup=database.path.with_suffix(database.path.suffix+".pre-v9.backup")
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]==8
        assert connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    database.rollback(9)
    assert database.schema_version()==8
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='creator_profiles'").fetchone()[0]==0
        assert connection.execute("SELECT COUNT(*) FROM marketplace_items").fetchone()[0]==0


def test_creator_dashboard_is_authenticated_and_owner_scoped(tmp_path: Path) -> None:
    secrets_root=tmp_path/"secrets"; secrets_root.mkdir()
    password=secrets_root/"password"; session_key=secrets_root/"session"; namespace=secrets_root/"namespace"; webhook=secrets_root/"webhook"
    password.write_text(hash_password("creator-dashboard-password"),encoding="ascii")
    session_key.write_bytes(b"s"*32); namespace.write_text(CREATOR,encoding="ascii"); webhook.write_bytes(b"w"*32)
    app=create_application(DashboardConfig(project_root=PROJECT,state_root=tmp_path/"state",database_path=tmp_path/"db"/"nexora.sqlite3",password_hash_file=password,session_key_file=session_key,owner_namespace_file=namespace,webhook_master_file=webhook,tls_cert_file=None,tls_key_file=None))
    assert not app.api.creator_dashboard()["configured"]
    created=app.api.create_creator_profile({"display_name":"Dashboard Creator","bio":"Safe"})
    view=app.api.creator_dashboard()
    assert created["display_name"]=="Dashboard Creator" and view["configured"]
    assert app.permissions.authorize(Session("id","csrf","admin",0.0,9999999999.0),"creator:read")
    assert not app.permissions.authorize(None,"creator:read")
    frontend=(PROJECT/"dashboard"/"frontend"/"app.js").read_text(encoding="utf-8")
    assert 'api("/api/creator")' in frontend and 'path==="/creator"' in frontend
