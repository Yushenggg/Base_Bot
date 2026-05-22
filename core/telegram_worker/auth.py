from core.config import app_config


class RoleResolver:
    def __init__(self):
        self._authorized_id = app_config.authorized_user

    def is_authorized(self, user_id: int | None) -> bool:
        if self._authorized_id is None:
            return False
        return user_id == self._authorized_id
