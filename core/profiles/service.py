"""Application service for the local user profile and avatar lifecycle."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from core.repositories import ProfileRepository


class ProfileServiceError(ValueError):
    """A profile validation or availability error with an HTTP-neutral status."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProfileService:
    """Owns profile validation, serialization, and avatar normalization."""

    def __init__(self, db) -> None:
        self.repository = ProfileRepository(db)

    def _profile(self):
        return self.repository.get_or_create()

    def serialize(self) -> dict[str, object]:
        profile = self._profile()
        configured = bool(profile.avatar_data)
        return {
            "display_name": profile.display_name,
            "username": profile.username,
            "email": profile.email,
            "avatar_url": "/api/profile/avatar" if configured else "",
            "avatar_configured": configured,
        }

    def update(self, display_name: str, username: str, email: str) -> dict[str, object]:
        display_name = display_name.strip()
        username = username.strip()
        email = email.strip()
        if not display_name or not username:
            raise ProfileServiceError("نام نمایشی و نام کاربری نمی‌توانند خالی باشند")
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            raise ProfileServiceError("فرمت ایمیل معتبر نیست")
        profile = self._profile()
        profile.display_name = display_name
        profile.username = username
        profile.email = email
        self.repository.save(profile)
        return self.serialize()

    def set_avatar(self, image_bytes: bytes) -> dict[str, object]:
        if not image_bytes:
            raise ProfileServiceError("فایلی دریافت نشد", 400)
        if len(image_bytes) > 2 * 1024 * 1024:
            raise ProfileServiceError("حجم تصویر نباید بیشتر از ۲ مگابایت باشد", 413)
        try:
            with Image.open(BytesIO(image_bytes)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ProfileServiceError("فقط فرمت‌های PNG، JPG و WebP مجاز هستند", 415)
                if source.width > 4096 or source.height > 4096:
                    raise ProfileServiceError("ابعاد تصویر نباید از ۴۰۹۶×۴۰۹۶ پیکسل بیشتر باشد")
                source.load()
                normalized = ImageOps.fit(source.convert("RGB"), (256, 256))
                output = BytesIO()
                normalized.save(output, format="WEBP", quality=85, method=6)
        except ProfileServiceError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ProfileServiceError("فایل تصویر معتبر نیست") from exc

        profile = self._profile()
        profile.avatar_data = output.getvalue()
        profile.avatar_mime = "image/webp"
        self.repository.save(profile)
        return self.serialize()

    def get_avatar(self) -> tuple[bytes, str]:
        profile = self._profile()
        if not profile.avatar_data:
            raise ProfileServiceError("تصویر پروفایل ثبت نشده است", 404)
        return profile.avatar_data, profile.avatar_mime or "image/webp"

    def delete_avatar(self) -> dict[str, object]:
        profile = self._profile()
        profile.avatar_data = None
        profile.avatar_mime = None
        self.repository.save(profile)
        return self.serialize()
