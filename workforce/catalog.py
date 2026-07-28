from __future__ import annotations

from typing import Any


CATEGORIES = (
    "business", "marketing", "development", "analytics", "support",
    "hr", "finance", "automation", "content",
)


def _employee(
    item_id: str,
    name: str,
    category: str,
    description: str,
    skills: list[str],
    integrations: list[str],
    workflow: list[str],
) -> dict[str, Any]:
    return {
        "manifest": {
            "id": item_id,
            "name": name,
            "type": "AGENT",
            "version": "1.0.0",
            "author": "Nexora",
            "description": description,
            "category": category,
            "package_kind": "SINGLE_AGENT",
            "permissions": {
                "filesystem": {"scope": "workspace"},
                "network": {"mode": "none"},
                "shell": False,
            },
            "risk_level": "LOW",
            "requirements": skills,
            "compatibility": {"minimum_nexora": "4.0.0"},
            "security": {"sandbox": True, "secret_access": False, "docker_access": False},
        },
        "metadata": {
            "listing_kind": "EMPLOYEE",
            "tags": [category, "ai-employee", "official"],
            "price_cents": 0,
            "currency": "USD",
            "changelog": "1.0.0 — first production-ready employee profile.",
            "compatibility": {"minimum_nexora": "4.0.0", "api": "v1"},
            "screenshots": [],
            "documentation": f"docs/ai-employees/{item_id}.md",
            "auto_update": False,
            "visibility": "PUBLIC",
        },
        "workforce": {
            "system_prompt": (
                f"You are the {name} inside Nexora. Work only within the authorized workspace. "
                "Follow Policy Engine decisions, require approval for irreversible actions, "
                "never reveal secrets, and return concise auditable results."
            ),
            "memory_profile": {"scope": "workspace", "retention": "bounded", "secret_storage": False},
            "workflow_pack": workflow,
            "recommended_skills": skills,
            "recommended_integrations": integrations,
            "settings": {"approval_mode": "policy", "external_actions": False, "language": "ru"},
        },
    }


OFFICIAL_EMPLOYEES = [
    _employee("sales-manager", "Sales Manager", "business", "Lead qualification, sales plans and safe CRM-ready summaries.", ["research-skill"], ["EMAIL", "WEBHOOK"], ["lead-processing"]),
    _employee("ceo-assistant", "CEO Assistant", "business", "Executive briefs, priorities, meeting preparation and decision support.", ["research-skill", "analytics-skill"], ["GOOGLE", "EMAIL"], ["executive-brief"]),
    _employee("marketing-manager", "Marketing Manager", "marketing", "Campaign planning, channel analysis and content coordination.", ["research-skill", "content-writing-skill", "analytics-skill"], ["GOOGLE", "SLACK"], ["content-pipeline"]),
    _employee("telegram-manager", "Telegram Manager", "marketing", "Telegram content planning, moderation drafts and audience reports.", ["content-writing-skill", "analytics-skill"], ["TELEGRAM"], ["telegram-content"]),
    _employee("content-writer", "Content Writer", "content", "Structured drafts, articles, posts and editorial variants.", ["research-skill"], [], ["content-pipeline"]),
    _employee("seo-specialist", "SEO Specialist", "marketing", "Search intent analysis, briefs and non-invasive SEO recommendations.", ["research-skill", "analytics-skill"], [], ["seo-review"]),
    _employee("support-operator", "Support Operator", "support", "Support triage, response drafts and escalation summaries.", ["research-skill"], ["EMAIL", "SLACK"], ["customer-support"]),
    _employee("developer", "Developer", "development", "Code analysis, implementation plans and workspace-scoped development.", ["github-analysis-skill"], ["GITHUB"], ["bug-triage", "release-pipeline"]),
    _employee("devops", "DevOps", "automation", "Infrastructure diagnostics and approval-gated operations planning.", ["analytics-skill"], ["GITHUB", "WEBHOOK"], ["release-pipeline"]),
    _employee("qa-engineer", "QA Engineer", "development", "Test design, regression analysis and release quality reports.", ["github-analysis-skill"], ["GITHUB"], ["bug-triage"]),
    _employee("research-analyst", "Research Analyst", "analytics", "Source analysis, evidence synthesis and structured research reports.", ["research-skill"], [], ["research-automation"]),
    _employee("financial-analyst", "Financial Analyst", "finance", "Financial model review, scenario analysis and risk summaries.", ["analytics-skill"], [], ["financial-review"]),
    _employee("hr-manager", "HR Manager", "hr", "Role descriptions, onboarding plans and policy-safe people operations.", ["content-writing-skill"], ["EMAIL"], ["employee-onboarding"]),
    _employee("project-manager", "Project Manager", "business", "Project decomposition, milestones, risks and progress coordination.", ["analytics-skill"], ["SLACK", "EMAIL"], ["project-delivery"]),
]


OFFICIAL_WORKFLOWS = [
    ("lead-processing", "Lead Processing", "business", ["research", "sales-manager", "qa-engineer"]),
    ("content-pipeline", "Content Pipeline", "content", ["research-analyst", "content-writer", "qa-engineer"]),
    ("customer-support", "Customer Support", "support", ["support-operator", "research-analyst"]),
    ("bug-triage", "Bug Triage", "development", ["qa-engineer", "developer", "project-manager"]),
    ("research-automation", "Research Automation", "analytics", ["research-analyst", "financial-analyst", "qa-engineer"]),
    ("release-pipeline", "Release Pipeline", "automation", ["developer", "qa-engineer", "devops"]),
]


OFFICIAL_SKILLS = [
    ("research-skill", "Research", "analytics", "Workspace-safe research and source synthesis."),
    ("content-writing-skill", "Content Writer Skill", "content", "Structured draft and editorial content generation."),
    ("github-analysis-skill", "GitHub Assistant", "development", "Read-only repository and pull request analysis."),
    ("analytics-skill", "Analytics", "analytics", "Metric analysis and bounded reporting."),
]


def official_catalog() -> list[dict[str, Any]]:
    values = list(OFFICIAL_EMPLOYEES)
    for item_id, name, category, steps in OFFICIAL_WORKFLOWS:
        values.append({
            "manifest": {
                "id": item_id, "name": name, "type": "TEMPLATE", "version": "1.0.0",
                "author": "Nexora", "description": f"Official {name} workflow.",
                "category": category,
                "permissions": {"filesystem": {"scope": "workspace"}, "network": {"mode": "none"}, "shell": False},
                "risk_level": "LOW", "requirements": [], "compatibility": {"minimum_nexora": "4.0.0"},
                "security": {"sandbox": True, "secret_access": False, "docker_access": False},
            },
            "metadata": {
                "listing_kind": "WORKFLOW", "tags": [category, "workflow", "official"], "price_cents": 0,
                "currency": "USD", "changelog": "1.0.0 — official workflow.", "compatibility": {"minimum_nexora": "4.0.0"},
                "screenshots": [], "documentation": f"docs/workflows/{item_id}.md", "auto_update": False, "visibility": "PUBLIC",
            },
            "workforce": {"workflow_pack": steps, "settings": {"external_actions": False}},
        })
    for item_id, name, category, description in OFFICIAL_SKILLS:
        values.append({
            "manifest": {
                "id": item_id, "name": name, "type": "SKILL", "version": "1.0.0",
                "author": "Nexora", "description": description, "category": category,
                "permissions": {"filesystem": {"scope": "workspace"}, "network": {"mode": "none"}, "shell": False},
                "risk_level": "LOW", "requirements": [], "compatibility": {"minimum_nexora": "4.0.0"},
                "security": {"sandbox": True, "secret_access": False, "docker_access": False},
            },
            "metadata": {
                "listing_kind": "SKILL", "tags": [category, "skill", "official"], "price_cents": 0,
                "currency": "USD", "changelog": "1.0.0 — official skill.", "compatibility": {"minimum_nexora": "4.0.0"},
                "screenshots": [], "documentation": f"docs/skills/{item_id}.md", "auto_update": False, "visibility": "PUBLIC",
            },
            "workforce": {"settings": {"external_actions": False}},
        })
    return values
