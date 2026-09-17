"""
Cloudinary Service for Veritas — Media Asset Optimization & CDN Management.
Handles user avatar uploads with automatic face-detection cropping and student handwritten
work uploads with automatic format/quality optimization.
"""
import os
import io
import time
import base64
from typing import Optional, Union

from dotenv import load_dotenv
load_dotenv()

try:
    import cloudinary
    import cloudinary.uploader
    CLOUDINARY_AVAILABLE = True
except ImportError:
    CLOUDINARY_AVAILABLE = False


class CloudinaryService:
    def __init__(self):
        self._configured = False
        self._init_client()

    def _init_client(self):
        if not CLOUDINARY_AVAILABLE:
            return

        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
        api_key = os.getenv("CLOUDINARY_API_KEY")
        api_secret = os.getenv("CLOUDINARY_API_SECRET")
        cloudinary_url = os.getenv("CLOUDINARY_URL")

        if cloud_name and api_key and api_secret:
            try:
                cloudinary.config(
                    cloud_name=cloud_name,
                    api_key=api_key,
                    api_secret=api_secret,
                    secure=True,
                )
                self._configured = True
                print("[INFO] CloudinaryService: Configured successfully.")
            except Exception as e:
                print(f"[WARN] CloudinaryService: Configuration failed: {e}")
                self._configured = False
        elif cloudinary_url:
            try:
                cloudinary.config(cloudinary_url=cloudinary_url, secure=True)
                self._configured = True
                print("[INFO] CloudinaryService: Configured successfully from URL.")
            except Exception as e:
                print(f"[WARN] CloudinaryService: Configuration failed: {e}")
                self._configured = False
        else:
            self._configured = False

    @property
    def is_available(self) -> bool:
        return self._configured and CLOUDINARY_AVAILABLE

    def upload_avatar(self, file_content: Union[bytes, str], user_id: str) -> Optional[str]:
        """
        Uploads an avatar photo to Cloudinary.
        Applies face-centered cropping to 256x256 and WebP/AVIF auto compression.
        Returns the secure HTTPS CDN URL, or None on failure.
        """
        if not self.is_available:
            return None

        try:
            # Handle data:image base64 URI or raw bytes
            payload = file_content
            clean_id = user_id.replace(" ", "_")
            res = cloudinary.uploader.upload(
                payload,
                folder="veritas/avatars",
                public_id=f"avatar_{clean_id}",
                overwrite=True,
                transformation=[
                    {"width": 256, "height": 256, "crop": "fill", "gravity": "face"},
                    {"quality": "auto", "fetch_format": "auto"},
                ],
            )
            return res.get("secure_url")
        except Exception as e:
            print(f"[WARN] CloudinaryService: Avatar upload failed for user {user_id}: {e}")
            return None

    def upload_student_work(
        self,
        file_bytes: bytes,
        session_id: str,
        student_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Uploads student handwritten math work to Cloudinary CDN.
        Preserves image details for OCR inspection while optimizing bandwidth.
        Returns secure HTTPS CDN URL, or None on failure.
        """
        if not self.is_available:
            return None

        try:
            owner = (student_id or "anonymous").replace(" ", "_")
            timestamp = int(time.time())
            folder = f"veritas/work/{owner}"
            res = cloudinary.uploader.upload(
                file_bytes,
                folder=folder,
                public_id=f"{session_id[:8]}_{timestamp}",
                overwrite=True,
                transformation=[
                    {"quality": "auto:good", "fetch_format": "auto"},
                ],
            )
            return res.get("secure_url")
        except Exception as e:
            print(f"[WARN] CloudinaryService: Student work upload failed for session {session_id}: {e}")
            return None


# Singleton instance
cloudinary_service = CloudinaryService()
