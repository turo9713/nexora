from __future__ import annotations


class ContentPublicationDenied(PermissionError):
    pass


class ContentIntegration:
    """Prepare drafts and approval metadata; no external publisher is embedded."""

    route = ("research", "content", "qa", "approval")

    def prepare(self, title: str) -> dict[str, object]:
        clean = " ".join(str(title).replace("\x00", "").split())[:200]
        if not clean:
            raise ValueError("content title required")
        return {"title": clean, "route": list(self.route), "status": "DRAFT", "auto_publish": False}

    def authorize_publication(self, approval_granted: bool) -> dict[str, str]:
        if not approval_granted:
            raise ContentPublicationDenied("publication approval required")
        return {"status": "APPROVED", "execution": "EXTERNAL_PUBLISHER_NOT_CONFIGURED"}
