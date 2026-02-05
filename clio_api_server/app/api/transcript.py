from typing import List

from fastapi import APIRouter, Depends

from clio_api_server.app.models.transcript import (
    UnconsolidatedTranscript,
    ConsolidatedTranscript,
    Question,
)
from clio_api_server.app.services.pipeline import Pipeline, get_pipeline


router = APIRouter(prefix="/v1/transcript", tags=["transcript"])


@router.get("/unconsolidated", response_model=UnconsolidatedTranscript)
async def get_unconsolidated_transcript(
    pipeline: Pipeline = Depends(get_pipeline),
) -> UnconsolidatedTranscript:
    return pipeline.aggregator.get_unconsolidated()


@router.get("/consolidated", response_model=ConsolidatedTranscript)
async def get_consolidated_transcript(
    pipeline: Pipeline = Depends(get_pipeline),
) -> ConsolidatedTranscript:
    return pipeline.aggregator.get_consolidated()


@router.get("/questions", response_model=List[Question])
async def get_questions(
    pipeline: Pipeline = Depends(get_pipeline),
) -> List[Question]:
    return pipeline.aggregator.get_questions()
