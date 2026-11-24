"""Repository for the single local user profile."""
from __future__ import annotations

from ..database import UserProfile
from .base import BaseRepository


class ProfileRepository(BaseRepository):
    """Owns persistence operations for the user profile domain."""

    def get_or_create(self) -> UserProfile:
        profile = self.db.query(UserProfile).filter(UserProfile.id == 1).first()
        if profile is None:
            profile = UserProfile(id=1, display_name="کاربر", username="user", email="")
            self.db.add(profile)
            self.db.commit()
            self.db.refresh(profile)
        return profile

    def save(self, profile: UserProfile) -> UserProfile:
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(profile)
        return profile
