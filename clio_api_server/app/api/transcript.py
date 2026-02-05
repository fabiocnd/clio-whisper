from typing import List, Generator
from fastapi import APIRouter, Depends, Request

from clio_api_server.app.models.transcript import (
    UnconsolidatedTranscript,
    ConsolidatedTranscript,
    Question,
)


router = APIRouter(prefix="/v1/transcript", tags=["transcript"])


def get_pipeline(request: Request):
    return request.app.state.pipeline


@router.get("/unconsolidated", response_model=UnconsolidatedTranscript)
async def get_unconsolidated_transcript(
    pipeline=Depends(get_pipeline),
) -> UnconsolidatedTranscript:
    """
    Get the unconsolidated transcript with all individual segments.

    Returns all transcription segments in their raw form, including partial,
    final, and committed segments with timing information.
    """
    return pipeline.aggregator.get_unconsolidated()


@router.get("/consolidated", response_model=ConsolidatedTranscript)
async def get_consolidated_transcript(
    pipeline=Depends(get_pipeline),
) -> ConsolidatedTranscript:
    """
    Get the consolidated transcript as a single paragraph.

    Returns deduplicated, aggregated text from all committed segments.
    """
    return pipeline.aggregator.get_consolidated()


@router.get("/questions", response_model=List[Question])
async def get_questions(
    pipeline=Depends(get_pipeline),
) -> List[Question]:
    """
    Get extracted questions from the transcript.

    Returns a list of detected questions, both explicit (with ?) and
    implicit (imperative prompts like 'Imagine...').
    """
    return pipeline.aggregator.get_questions()
