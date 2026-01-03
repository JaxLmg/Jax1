# Text reduction: variable renames and formatting tweaks; endpoints and flow unchanged
import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from auth import get_current_user_id
from database import cosmos_db
from media_helpers import extract_thumbnail_blob_identifier, fetch_and_verify_media_ownership
from models import MediaListResponse, MediaResponse, MediaUpdate
from storage import blob_storage
from utils import generate_thumbnail, validate_file_size, validate_file_type

media_logger = logging.getLogger("media_router")

router = APIRouter(prefix="/media", tags=["Media Management"])


@router.post("", response_model=MediaResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    """
    Upload a new image or video file
    """
    try:
        # Validate file type
        media_kind = validate_file_type(file)

        # Validate file size
        uploaded_size = validate_file_size(file)

        # Parse tags if provided
        parsed_tags = None
        if tags:
            try:
                parsed_tags = json.loads(tags)
                if not isinstance(parsed_tags, list):
                    raise ValueError("Tags must be an array")
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid tags format. Must be a JSON array.",
                )

        # Read file content
        raw_payload = await file.read()
        await file.seek(0)

        # Upload to blob storage
        uploaded_name, uploaded_url = blob_storage.upload_file(
            file.file, user_id, file.filename, file.content_type
        )

        # Generate thumbnail for images
        preview_url = None
        if media_kind == "image":
            preview_data = generate_thumbnail(raw_payload)
            if preview_data:
                try:
                    import io
                    preview_file = io.BytesIO(preview_data)
                    preview_blob_name, preview_url = blob_storage.upload_file(
                        preview_file,
                        user_id,
                        f"thumb_{file.filename}",
                        "image/jpeg",
                    )
                except Exception as e:
                    media_logger.warning(f"Failed to upload thumbnail: {e}")

        # Create media document
        media_identifier = str(uuid.uuid4())
        timestamp_iso = datetime.utcnow().isoformat()
        media_payload = {
            "id": media_identifier,
            "userId": user_id,
            "fileName": uploaded_name,
            "originalFileName": file.filename,
            "mediaType": media_kind,
            "fileSize": uploaded_size,
            "mimeType": file.content_type,
            "blobUrl": uploaded_url,
            "thumbnailUrl": preview_url,
            "description": description,
            "tags": parsed_tags,
            "uploadedAt": timestamp_iso,
            "updatedAt": timestamp_iso,
        }

        # Save to database
        persisted_media = cosmos_db.create_media(media_payload)

        # Return response
        return MediaResponse(**persisted_media)

    except HTTPException:
        raise
    except Exception as e:
        media_logger.error(f"Upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload media: {str(e)}",
        )


@router.get("/search", response_model=MediaListResponse, status_code=status.HTTP_200_OK)
async def search_media(
    query: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    """
    Search media files by filename, description, or tags
    """
    try:
        search_results, record_count = cosmos_db.search_media(
            user_id=user_id, query=query, page=page, page_size=pageSize
        )

        response_items = [MediaResponse(**item) for item in search_results]

        return MediaListResponse(
            items=response_items, total=record_count, page=page, pageSize=pageSize
        )

    except Exception as e:
        media_logger.error(f"Search media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to search media",
        )


@router.get("", response_model=MediaListResponse, status_code=status.HTTP_200_OK)
async def get_media_list(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    mediaType: Optional[str] = Query(None, regex="^(image|video)$"),
    user_id: str = Depends(get_current_user_id),
):
    """
    Retrieve paginated list of user's media files
    """
    try:
        user_media, record_count = cosmos_db.get_user_media(
            user_id=user_id, page=page, page_size=pageSize, media_type=mediaType
        )

        response_items = [MediaResponse(**item) for item in user_media]

        return MediaListResponse(
            items=response_items, total=record_count, page=page, pageSize=pageSize
        )

    except Exception as e:
        media_logger.error(f"Get media list error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve media list",
        )


@router.get("/{media_id}", response_model=MediaResponse, status_code=status.HTTP_200_OK)
async def get_media_by_id(
    media_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Retrieve details of a specific media file
    """
    try:
        media_snapshot = fetch_and_verify_media_ownership(media_id, user_id)
        return MediaResponse(**media_snapshot)

    except HTTPException:
        raise
    except Exception as e:
        media_logger.error(f"Get media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve media",
        )


@router.put("/{media_id}", response_model=MediaResponse, status_code=status.HTTP_200_OK)
async def update_media_metadata(
    media_id: str,
    update_data: MediaUpdate,
    user_id: str = Depends(get_current_user_id),
):
    """
    Update description and tags of a media file
    """
    try:
        # Verify media exists and user has ownership
        existing_media = fetch_and_verify_media_ownership(media_id, user_id)

        # Prepare updates with timestamp
        update_payload = {"updatedAt": datetime.utcnow().isoformat()}

        if update_data.description is not None:
            update_payload["description"] = update_data.description

        if update_data.tags is not None:
            update_payload["tags"] = update_data.tags

        # Apply updates to database
        updated_media = cosmos_db.update_media(media_id, user_id, update_payload)

        return MediaResponse(**updated_media)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )
    except Exception as e:
        media_logger.error(f"Update media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update media",
        )


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    media_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Delete a media file and its metadata
    """
    try:
        # Verify media exists and user has ownership
        media_record = fetch_and_verify_media_ownership(media_id, user_id)

        # Remove primary file from blob storage
        blob_storage.delete_file(media_record["fileName"])

        # Remove thumbnail if present
        preview_blob_id = extract_thumbnail_blob_identifier(media_record)
        if preview_blob_id:
            try:
                blob_storage.delete_file(preview_blob_id)
            except Exception as e:
                media_logger.warning(f"Thumbnail deletion failed: {e}")

        # Remove metadata from database
        cosmos_db.delete_media(media_id, user_id)

        return None

    except HTTPException:
        raise
    except Exception as e:
        media_logger.error(f"Delete media error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete media",
        )
