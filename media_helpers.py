"""
Helper functions for media routes
Provides common validation and verification logic
"""

from fastapi import HTTPException, status
from database import cosmos_db
import logging

logger = logging.getLogger(__name__)


def fetch_and_verify_media_ownership(media_id: str, user_id: str) -> dict:
    """
    Fetch media by ID and verify user ownership

    Args:
        media_id: The ID of the media to fetch
        user_id: The ID of the requesting user

    Returns:
        dict: The media document if found and owned by user

    Raises:
        HTTPException: If media not found or user doesn't have permission
    """
    media_document = cosmos_db.get_media_by_id(media_id, user_id)

    if not media_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media resource not found"
        )

    if media_document["userId"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: insufficient permissions for this media"
        )

    return media_document


def validate_media_existence(media_id: str, user_id: str) -> dict:
    """
    Check if media exists and return it (without strict ownership verification)
    Used when ownership is already verified at a higher level

    Args:
        media_id: The ID of the media to check
        user_id: The ID of the user

    Returns:
        dict: The media document if found

    Raises:
        HTTPException: If media not found
    """
    media_document = cosmos_db.get_media_by_id(media_id, user_id)

    if not media_document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested media resource could not be located"
        )

    return media_document


def extract_thumbnail_blob_identifier(media_document: dict) -> str | None:
    """
    Extract thumbnail blob name from media document

    Args:
        media_document: The media document

    Returns:
        str | None: The thumbnail blob name or None if not applicable
    """
    if not media_document.get("thumbnailUrl"):
        return None

    try:
        original_filename = media_document["originalFileName"].split("/")[-1]
        thumbnail_identifier = media_document["fileName"].replace(
            original_filename,
            f"thumb_{original_filename}"
        )
        return thumbnail_identifier
    except Exception as e:
        logger.warning(f"Unable to extract thumbnail identifier: {e}")
        return None
