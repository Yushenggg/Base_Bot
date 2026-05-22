from core.config import app_config


class RoleResolver:
    def __init__(self):
        ids: set[int] = set(app_config.admin_users) | set(app_config.allowed_users)
        self._authorized_ids = ids

    def is_authorized(self, user_id: int | None) -> bool:
        if not self._authorized_ids:
            return False
        return user_id in self._authorized_ids
