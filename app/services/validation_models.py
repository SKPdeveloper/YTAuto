"""
Pydantic models for GLAZE-VAL v2.0 Image Validation Response

These models parse the JSON output from the GLAZE CITY IMAGE VALIDATOR.
Used by ImageValidator to process validation results.

JSON Schema matches: config/VAL_IMG.txt output format
"""

from typing import Optional, List, Dict, Literal
from pydantic import BaseModel, Field


# ============================================================================
# PHASE 1: GLITCH DETECTION
# ============================================================================

class GlitchResult(BaseModel):
    """Result for a single image in glitch detection phase"""
    image: str = Field(..., description="Image identifier (IMG_1, IMG_2, etc.)")
    status: Literal["PASS", "REJECT"] = Field(..., description="Pass or reject status")
    glitches: List[str] = Field(default_factory=list, description="List of detected glitches with descriptions")


class Phase1GlitchDetection(BaseModel):
    """Phase 1: Glitch detection results"""
    summary: str = Field(..., description="Summary like '3/4 images passed'")
    results: List[GlitchResult] = Field(..., description="Results for each image")


# ============================================================================
# PHASE 2: QUALITY SCORING
# ============================================================================

class ScoreDetail(BaseModel):
    """Individual criterion score with note"""
    score: int | str = Field(..., description="Score 0-10 or 'N/A'")
    note: str = Field(..., description="Explanation for the score")


class ImageScores(BaseModel):
    """Complete scores for a single image"""
    prompt_adherence: ScoreDetail = Field(..., description="How well image matches prompt")
    photorealism: ScoreDetail = Field(..., description="How realistic the image looks")
    food_texture: ScoreDetail = Field(..., description="Quality of food textures")
    composition: ScoreDetail = Field(..., description="Composition and framing")
    lighting: ScoreDetail = Field(..., description="Lighting and mood")
    viral_potential: ScoreDetail = Field(..., description="Scroll-stopping power")
    brand_consistency: ScoreDetail = Field(..., description="Glaze City brand fit")
    easter_egg: ScoreDetail = Field(..., description="Easter egg compliance (N/A if not required)")
    total: int = Field(..., description="Total score")
    max_possible: int = Field(..., description="Maximum possible score (70 or 80)")
    percentage: int = Field(..., description="Percentage score")
    grade: str = Field(..., description="Letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F)")


class Phase2QualityScoring(BaseModel):
    """Phase 2: Quality scoring results"""
    scored_images: List[str] = Field(..., description="List of images that passed Phase 1")
    scores: Dict[str, ImageScores] = Field(..., description="Scores for each valid image")


# ============================================================================
# PHASE 3: DECISION
# ============================================================================

class Phase3Decision(BaseModel):
    """Phase 3: Final selection decision"""
    validation_status: Literal["PASSED", "FAILED"] = Field(..., description="Overall validation result")
    selected_image: str = Field(..., description="Selected image ID or 'NONE'")
    selected_score: Optional[int] = Field(None, description="Score of selected image")
    selected_max: Optional[int] = Field(None, description="Max possible score")
    selected_percentage: Optional[int] = Field(None, description="Percentage of selected image")
    selected_grade: Optional[str] = Field(None, description="Grade of selected image")
    reasoning: str = Field(..., description="Explanation for the decision")


# ============================================================================
# ISSUES & RETRY
# ============================================================================

class Issues(BaseModel):
    """Issues found during validation"""
    has_issues: bool = Field(..., description="Whether any issues were found")
    concerns: List[str] = Field(default_factory=list, description="List of concerns")


class RetryPrompts(BaseModel):
    """Retry prompts for failed validation"""
    prompt_additions: List[str] = Field(default_factory=list, description="Phrases to add to prompt")
    prompt_removals: List[str] = Field(default_factory=list, description="Phrases to remove")
    full_retry_prompt: str = Field(..., description="Complete retry prompt")
    recommended_action: str = Field(..., description="Recommended action")
    max_retries_recommended: int = Field(default=2, description="Max retries suggested")


# ============================================================================
# VALIDATION METADATA
# ============================================================================

class ValidationMetadata(BaseModel):
    """Metadata about the validation request"""
    scene: str = Field(..., description="Scene identifier")
    images_received: int = Field(..., description="Number of images received")
    timestamp: str = Field(..., description="ISO timestamp")


# ============================================================================
# COMPLETE VALIDATION RESPONSE
# ============================================================================

class ValidationResponse(BaseModel):
    """
    Complete validation response from GLAZE-VAL v2.0

    This is the main model for parsing validator output.

    Example usage:
        response = ValidationResponse.model_validate(json_data)
        if response.phase3_decision.validation_status == "PASSED":
            selected = response.phase3_decision.selected_image
    """
    validation: ValidationMetadata = Field(..., description="Validation metadata")
    phase1_glitch_detection: Phase1GlitchDetection = Field(..., description="Glitch detection results")
    phase2_quality_scoring: Phase2QualityScoring = Field(..., description="Quality scores")
    phase3_decision: Phase3Decision = Field(..., description="Final decision")
    issues: Issues = Field(..., description="Issues found")
    retry_prompts: Optional[RetryPrompts] = Field(None, description="Retry prompts if failed")

    @property
    def passed(self) -> bool:
        """Quick check if validation passed"""
        return self.phase3_decision.validation_status == "PASSED"

    @property
    def selected_image_id(self) -> Optional[str]:
        """Get selected image ID or None if failed"""
        if self.passed:
            return self.phase3_decision.selected_image
        return None

    @property
    def selected_image_index(self) -> Optional[int]:
        """Get 0-based index of selected image (IMG_1 -> 0, etc.)"""
        if self.passed and self.phase3_decision.selected_image != "NONE":
            # Extract number from IMG_1, IMG_2, etc.
            img_id = self.phase3_decision.selected_image
            if img_id.startswith("IMG_"):
                try:
                    return int(img_id.split("_")[1]) - 1
                except (IndexError, ValueError):
                    pass
        return None


# ============================================================================
# GEN1 VALIDATION RESPONSE MODELS (VAL_GEN1)
# ============================================================================

class Gen1ValidationMetadata(BaseModel):
    """Metadata for GEN1 validation"""
    stage: Literal["VAL_GEN1"] = "VAL_GEN1"
    version: str = Field(default="1.0", description="Validator version")
    timestamp: str = Field(..., description="ISO timestamp")


class Gen1Phase1Structural(BaseModel):
    """Phase 1: Structural validation for GEN1"""
    status: Literal["PASS", "FAIL"] = Field(..., description="Pass or fail status")
    errors: List[str] = Field(default_factory=list, description="List of structural errors")
    warnings: List[str] = Field(default_factory=list, description="List of warnings")


class Gen1QualityScore(BaseModel):
    """Single quality score with note"""
    score: int = Field(..., ge=0, le=10, description="Score 0-10")
    note: str = Field(..., description="Explanation for the score")


class Gen1Phase2Quality(BaseModel):
    """Phase 2: Quality scoring for GEN1"""
    scores: Dict[str, Gen1QualityScore] = Field(..., description="Quality scores by criterion")
    total: int = Field(..., description="Total score")
    max_possible: int = Field(default=60, description="Maximum possible score")
    percentage: int = Field(..., ge=0, le=100, description="Percentage score")
    grade: str = Field(..., description="Letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F)")


class Gen1Decision(BaseModel):
    """Decision for GEN1 validation"""
    status: Literal["PASSED", "FAILED"] = Field(..., description="Overall validation result")
    reasoning: str = Field(..., description="Explanation for the decision")
    proceed_to: Optional[Literal["GEN2"]] = Field(None, description="Next stage if passed")


class Gen1Issues(BaseModel):
    """Issues found during GEN1 validation"""
    has_issues: bool = Field(..., description="Whether any issues were found")
    concerns: List[str] = Field(default_factory=list, description="List of concerns")


class Gen1RetryGuidance(BaseModel):
    """Retry guidance for failed GEN1 validation"""
    fixes_needed: List[str] = Field(..., description="Specific fixes needed")
    regenerate: bool = Field(default=True, description="Whether regeneration is needed")


class Gen1ValidationResponse(BaseModel):
    """
    Complete validation response from VAL_GEN1

    Example usage:
        response = Gen1ValidationResponse.model_validate(json_data)
        if response.decision.status == "PASSED":
            proceed_to_gen2()
    """
    validation: Gen1ValidationMetadata = Field(..., description="Validation metadata")
    phase1_structural: Gen1Phase1Structural = Field(..., description="Structural validation")
    phase2_quality: Optional[Gen1Phase2Quality] = Field(None, description="Quality scores (null if phase1 failed)")
    decision: Gen1Decision = Field(..., description="Final decision")
    issues: Gen1Issues = Field(..., description="Issues found")
    retry_guidance: Optional[Gen1RetryGuidance] = Field(None, description="Retry guidance if failed")

    @property
    def passed(self) -> bool:
        """Quick check if validation passed"""
        return self.decision.status == "PASSED"

    @property
    def can_proceed(self) -> bool:
        """Check if pipeline can proceed to GEN2"""
        return self.passed and self.decision.proceed_to == "GEN2"


# ============================================================================
# GEN2 VALIDATION RESPONSE MODELS (VAL_GEN2)
# ============================================================================

class Gen2ValidationMetadata(BaseModel):
    """Metadata for GEN2 validation"""
    stage: Literal["VAL_GEN2"] = "VAL_GEN2"
    version: str = Field(default="1.0", description="Validator version")
    timestamp: str = Field(..., description="ISO timestamp")


class Gen2SceneCheck(BaseModel):
    """Scene check result for GEN2"""
    scene: int = Field(..., ge=1, le=10, description="Scene number")
    image_prompt: Literal["PASS", "FAIL", "WARNING"] = Field(..., description="Image prompt check")
    video_prompt: Literal["PASS", "FAIL", "WARNING"] = Field(..., description="Video prompt check")
    motion_elements: Literal["PASS", "FAIL", "WARNING"] = Field(..., description="Motion elements check")


class Gen2Phase1Structural(BaseModel):
    """Phase 1: Structural validation for GEN2"""
    status: Literal["PASS", "FAIL"] = Field(..., description="Pass or fail status")
    scene_checks: List[Gen2SceneCheck] = Field(..., description="Per-scene validation results")
    errors: List[str] = Field(default_factory=list, description="List of structural errors")
    warnings: List[str] = Field(default_factory=list, description="List of warnings")


class Gen2QualityScore(BaseModel):
    """Single quality score with note"""
    score: int = Field(..., ge=0, le=10, description="Score 0-10")
    note: str = Field(..., description="Explanation for the score")


class Gen2Phase2Quality(BaseModel):
    """Phase 2: Quality scoring for GEN2"""
    scores: Dict[str, Gen2QualityScore] = Field(..., description="Quality scores by criterion")
    total: int = Field(..., description="Total score")
    max_possible: int = Field(default=60, description="Maximum possible score")
    percentage: int = Field(..., ge=0, le=100, description="Percentage score")
    grade: str = Field(..., description="Letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F)")


class Gen2Decision(BaseModel):
    """Decision for GEN2 validation"""
    status: Literal["PASSED", "FAILED"] = Field(..., description="Overall validation result")
    reasoning: str = Field(..., description="Explanation for the decision")
    proceed_to: Optional[Literal["IMG_GEN"]] = Field(None, description="Next stage if passed")


class Gen2Issues(BaseModel):
    """Issues found during GEN2 validation"""
    has_issues: bool = Field(..., description="Whether any issues were found")
    concerns: List[str] = Field(default_factory=list, description="List of concerns")


class Gen2RetryGuidance(BaseModel):
    """Retry guidance for failed GEN2 validation"""
    fixes_needed: List[str] = Field(..., description="Specific fixes needed")
    regenerate: bool = Field(default=True, description="Whether regeneration is needed")


class Gen2ValidationResponse(BaseModel):
    """
    Complete validation response from VAL_GEN2

    Example usage:
        response = Gen2ValidationResponse.model_validate(json_data)
        if response.decision.status == "PASSED":
            proceed_to_img_gen()
    """
    validation: Gen2ValidationMetadata = Field(..., description="Validation metadata")
    phase1_structural: Gen2Phase1Structural = Field(..., description="Structural validation")
    phase2_quality: Optional[Gen2Phase2Quality] = Field(None, description="Quality scores (null if phase1 failed)")
    decision: Gen2Decision = Field(..., description="Final decision")
    issues: Gen2Issues = Field(..., description="Issues found")
    retry_guidance: Optional[Gen2RetryGuidance] = Field(None, description="Retry guidance if failed")

    @property
    def passed(self) -> bool:
        """Quick check if validation passed"""
        return self.decision.status == "PASSED"

    @property
    def can_proceed(self) -> bool:
        """Check if pipeline can proceed to IMG_GEN"""
        return self.passed and self.decision.proceed_to == "IMG_GEN"

    def get_failed_scenes(self) -> List[int]:
        """Get list of scene numbers that failed validation"""
        failed = []
        for check in self.phase1_structural.scene_checks:
            if check.image_prompt == "FAIL" or check.video_prompt == "FAIL" or check.motion_elements == "FAIL":
                failed.append(check.scene)
        return failed


# ============================================================================
# GEN3a VALIDATION RESPONSE MODELS (VAL_GEN3a)
# ============================================================================

class Gen3aValidationMetadata(BaseModel):
    """Metadata for GEN3a validation"""
    stage: Literal["VAL_GEN3a"] = "VAL_GEN3a"
    version: str = Field(default="1.0", description="Validator version")
    timestamp: str = Field(..., description="ISO timestamp")
    videos_analyzed: int = Field(..., description="Number of videos analyzed")


class Gen3aSceneValidation(BaseModel):
    """Validation result for a single scene in GEN3a"""
    scene_number: int = Field(..., ge=1, le=10, description="Scene number")
    glitches_detected: int = Field(default=0, description="Number of glitches detected")
    glitch_detection: Literal["PASS", "FAIL"] = Field(..., description="Glitch detection quality")
    speed_map: Literal["PASS", "FAIL"] = Field(..., description="Speed map validity")
    action_peaks: Literal["PASS", "FAIL"] = Field(..., description="Action peaks identified")
    visual_classification: Literal["PASS", "FAIL"] = Field(..., description="Visual classification accuracy")
    easter_egg_check: Optional[Literal["PASS", "FAIL", "N/A"]] = Field(None, description="Easter egg verification if required")
    notes: List[str] = Field(default_factory=list, description="Notes for this scene")


class Gen3aPhase1Structural(BaseModel):
    """Phase 1: Structural validation for GEN3a"""
    status: Literal["PASS", "FAIL"] = Field(..., description="Pass or fail status")
    scene_validations: List[Gen3aSceneValidation] = Field(..., description="Per-scene validation results")
    errors: List[str] = Field(default_factory=list, description="List of structural errors")
    warnings: List[str] = Field(default_factory=list, description="List of warnings")


class Gen3aQualityScore(BaseModel):
    """Single quality score with note for GEN3a"""
    score: int = Field(..., ge=0, le=10, description="Score 0-10")
    note: str = Field(..., description="Explanation for the score")


class Gen3aPhase2Quality(BaseModel):
    """Phase 2: Quality scoring for GEN3a"""
    scores: Dict[str, Gen3aQualityScore] = Field(..., description="Quality scores by criterion")
    total: int = Field(..., description="Total score")
    max_possible: int = Field(default=70, description="Maximum possible score")
    percentage: int = Field(..., ge=0, le=100, description="Percentage score")
    grade: str = Field(..., description="Letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F)")


class Gen3aDecision(BaseModel):
    """Decision for GEN3a validation"""
    status: Literal["PASSED", "FAILED"] = Field(..., description="Overall validation result")
    reasoning: str = Field(..., description="Explanation for the decision")
    proceed_to: Optional[Literal["GEN3b"]] = Field(None, description="Next stage if passed")


class Gen3aIssues(BaseModel):
    """Issues found during GEN3a validation"""
    has_issues: bool = Field(..., description="Whether any issues were found")
    concerns: List[str] = Field(default_factory=list, description="List of concerns")
    reanalysis_needed: List[int] = Field(default_factory=list, description="Scene numbers needing reanalysis")


class Gen3aRetryGuidance(BaseModel):
    """Retry guidance for failed GEN3a validation"""
    fixes_needed: List[str] = Field(..., description="Specific fixes needed")
    reanalyze_scenes: List[int] = Field(default_factory=list, description="Scenes to reanalyze")
    regenerate: bool = Field(default=False, description="Whether full regeneration is needed")


class Gen3aValidationResponse(BaseModel):
    """
    Complete validation response from VAL_GEN3a

    Validates video analysis output including:
    - Glitch detection accuracy
    - Speed map recommendations
    - Action peaks identification
    - Visual classification correctness
    - Easter egg verification (if required)

    Example usage:
        response = Gen3aValidationResponse.model_validate(json_data)
        if response.decision.status == "PASSED":
            proceed_to_gen3b()
    """
    validation: Gen3aValidationMetadata = Field(..., description="Validation metadata")
    phase1_structural: Gen3aPhase1Structural = Field(..., description="Structural validation")
    phase2_quality: Optional[Gen3aPhase2Quality] = Field(None, description="Quality scores (null if phase1 failed)")
    decision: Gen3aDecision = Field(..., description="Final decision")
    issues: Gen3aIssues = Field(..., description="Issues found")
    retry_guidance: Optional[Gen3aRetryGuidance] = Field(None, description="Retry guidance if failed")

    @property
    def passed(self) -> bool:
        """Quick check if validation passed"""
        return self.decision.status == "PASSED"

    @property
    def can_proceed(self) -> bool:
        """Check if pipeline can proceed to GEN3b"""
        return self.passed and self.decision.proceed_to == "GEN3b"

    def get_failed_scenes(self) -> List[int]:
        """Get list of scene numbers that failed validation"""
        failed = []
        for sv in self.phase1_structural.scene_validations:
            if (sv.glitch_detection == "FAIL" or sv.speed_map == "FAIL" or
                sv.action_peaks == "FAIL" or sv.visual_classification == "FAIL"):
                failed.append(sv.scene_number)
        return failed


# ============================================================================
# GEN3b VALIDATION RESPONSE MODELS (VAL_GEN3b)
# ============================================================================

class Gen3bValidationMetadata(BaseModel):
    """Metadata for GEN3b validation"""
    stage: Literal["VAL_GEN3b"] = "VAL_GEN3b"
    version: str = Field(default="1.0", description="Validator version")
    timestamp: str = Field(..., description="ISO timestamp")
    manifest_version: str = Field(..., description="Manifest version validated")


class Gen3bHookValidation(BaseModel):
    """Hook section validation"""
    style_valid: bool = Field(..., description="Hook style is valid")
    duration_valid: bool = Field(..., description="Duration within range (0.2-0.5s)")
    effects_valid: bool = Field(..., description="Effects are applicable")
    sfx_specified: bool = Field(..., description="SFX is specified")
    notes: List[str] = Field(default_factory=list, description="Notes about hook")


class Gen3bSceneValidation(BaseModel):
    """Scene validation in manifest"""
    scene_number: int = Field(..., ge=1, le=10, description="Scene number")
    timeline_valid: bool = Field(..., description="Timeline start/end valid")
    speed_segments_valid: bool = Field(..., description="Speed segments valid")
    effects_valid: bool = Field(..., description="Effects applicable")
    cuts_valid: bool = Field(..., description="Cut points valid")
    notes: List[str] = Field(default_factory=list, description="Notes for scene")


class Gen3bAudioValidation(BaseModel):
    """Audio layers validation"""
    layers_complete: bool = Field(..., description="All 5 layers defined")
    bed_configured: bool = Field(default=False, description="BED layer configured")
    music_configured: bool = Field(default=False, description="MUSIC layer configured")
    vo_configured: bool = Field(default=False, description="VO layer configured")
    sfx_events_valid: bool = Field(default=True, description="SFX events valid")
    foley_events_valid: bool = Field(default=True, description="FOLEY events valid")
    ducking_configured: bool = Field(default=False, description="Audio ducking set up")
    notes: List[str] = Field(default_factory=list, description="Notes about audio")


class Gen3bSubtitleValidation(BaseModel):
    """Subtitle validation"""
    count: int = Field(default=0, description="Number of subtitles")
    safe_zone_compliant: bool = Field(..., description="All subtitles in safe zone (not bottom 20%)")
    timing_valid: bool = Field(..., description="Timing within video duration")
    styles_valid: bool = Field(..., description="Styles are valid")
    notes: List[str] = Field(default_factory=list, description="Notes about subtitles")


class Gen3bPhase1Structural(BaseModel):
    """Phase 1: Structural validation for GEN3b"""
    status: Literal["PASS", "FAIL"] = Field(..., description="Pass or fail status")
    hook_validation: Gen3bHookValidation = Field(..., description="Hook section validation")
    scene_validations: List[Gen3bSceneValidation] = Field(..., description="Per-scene validation")
    audio_validation: Gen3bAudioValidation = Field(..., description="Audio layers validation")
    subtitle_validation: Gen3bSubtitleValidation = Field(..., description="Subtitle validation")
    errors: List[str] = Field(default_factory=list, description="List of structural errors")
    warnings: List[str] = Field(default_factory=list, description="List of warnings")


class Gen3bQualityScore(BaseModel):
    """Single quality score with note for GEN3b"""
    score: int = Field(..., ge=0, le=10, description="Score 0-10")
    note: str = Field(..., description="Explanation for the score")


class Gen3bPhase2Quality(BaseModel):
    """Phase 2: Quality scoring for GEN3b"""
    scores: Dict[str, Gen3bQualityScore] = Field(..., description="Quality scores by criterion")
    total: int = Field(..., description="Total score")
    max_possible: int = Field(default=80, description="Maximum possible score")
    percentage: int = Field(..., ge=0, le=100, description="Percentage score")
    grade: str = Field(..., description="Letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D+, D, D-, F)")


class Gen3bDecision(BaseModel):
    """Decision for GEN3b validation"""
    status: Literal["PASSED", "FAILED"] = Field(..., description="Overall validation result")
    reasoning: str = Field(..., description="Explanation for the decision")
    proceed_to: Optional[Literal["RENDER"]] = Field(None, description="Next stage if passed")


class Gen3bIssues(BaseModel):
    """Issues found during GEN3b validation"""
    has_issues: bool = Field(..., description="Whether any issues were found")
    concerns: List[str] = Field(default_factory=list, description="List of concerns")
    blocking_issues: List[str] = Field(default_factory=list, description="Issues that block rendering")


class Gen3bRetryGuidance(BaseModel):
    """Retry guidance for failed GEN3b validation"""
    fixes_needed: List[str] = Field(..., description="Specific fixes needed")
    regenerate_manifest: bool = Field(default=False, description="Whether to regenerate manifest")
    manual_fixes: List[str] = Field(default_factory=list, description="Fixes that can be applied manually")


class Gen3bValidationResponse(BaseModel):
    """
    Complete validation response from VAL_GEN3b

    Validates FFmpeg manifest including:
    - Hook section (style, duration, effects)
    - Scene processing (timeline, speed, cuts)
    - Audio layers (5-layer system)
    - Subtitles (safe zone, timing, styles)
    - Global effects

    Example usage:
        response = Gen3bValidationResponse.model_validate(json_data)
        if response.decision.status == "PASSED":
            proceed_to_render()
    """
    validation: Gen3bValidationMetadata = Field(..., description="Validation metadata")
    phase1_structural: Gen3bPhase1Structural = Field(..., description="Structural validation")
    phase2_quality: Optional[Gen3bPhase2Quality] = Field(None, description="Quality scores (null if phase1 failed)")
    decision: Gen3bDecision = Field(..., description="Final decision")
    issues: Gen3bIssues = Field(..., description="Issues found")
    retry_guidance: Optional[Gen3bRetryGuidance] = Field(None, description="Retry guidance if failed")

    @property
    def passed(self) -> bool:
        """Quick check if validation passed"""
        return self.decision.status == "PASSED"

    @property
    def can_proceed(self) -> bool:
        """Check if pipeline can proceed to RENDER"""
        return self.passed and self.decision.proceed_to == "RENDER"

    @property
    def ready_for_ffmpeg(self) -> bool:
        """Check if manifest is ready for FFmpeg rendering"""
        return self.passed and not self.issues.blocking_issues


# ============================================================================
# SIMPLE VALIDATION RESULT (for ContentBrain.validate_image)
# ============================================================================

class SimpleValidationResult(BaseModel):
    """
    Simple validation result for image validation via Gemini Vision.

    Used by ContentBrain.validate_image() for basic pass/fail decisions.
    For full 3-phase validation, use ValidationResponse instead.
    """
    approved: bool = Field(..., description="Whether image is approved")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    feedback: str = Field(..., description="Detailed feedback")
    issues: List[str] = Field(default_factory=list, description="List of issues found")
    strengths: List[str] = Field(default_factory=list, description="List of strengths")
    suggestions: List[str] = Field(default_factory=list, description="Improvement suggestions")
    matches_prompt: bool = Field(..., description="Whether image matches the prompt")
    quality_score: float = Field(..., ge=0.0, le=10.0, description="Quality score 0-10")


# ============================================================================
# EXPORT
# ============================================================================

__all__ = [
    # Image validation (VAL_IMG)
    "GlitchResult",
    "Phase1GlitchDetection",
    "ScoreDetail",
    "ImageScores",
    "Phase2QualityScoring",
    "Phase3Decision",
    "Issues",
    "RetryPrompts",
    "ValidationMetadata",
    "ValidationResponse",
    # GEN1 validation (VAL_GEN1)
    "Gen1ValidationMetadata",
    "Gen1Phase1Structural",
    "Gen1QualityScore",
    "Gen1Phase2Quality",
    "Gen1Decision",
    "Gen1Issues",
    "Gen1RetryGuidance",
    "Gen1ValidationResponse",
    # GEN2 validation (VAL_GEN2)
    "Gen2ValidationMetadata",
    "Gen2SceneCheck",
    "Gen2Phase1Structural",
    "Gen2QualityScore",
    "Gen2Phase2Quality",
    "Gen2Decision",
    "Gen2Issues",
    "Gen2RetryGuidance",
    "Gen2ValidationResponse",
    # GEN3a validation (VAL_GEN3a)
    "Gen3aValidationMetadata",
    "Gen3aSceneValidation",
    "Gen3aPhase1Structural",
    "Gen3aQualityScore",
    "Gen3aPhase2Quality",
    "Gen3aDecision",
    "Gen3aIssues",
    "Gen3aRetryGuidance",
    "Gen3aValidationResponse",
    # GEN3b validation (VAL_GEN3b)
    "Gen3bValidationMetadata",
    "Gen3bHookValidation",
    "Gen3bSceneValidation",
    "Gen3bAudioValidation",
    "Gen3bSubtitleValidation",
    "Gen3bPhase1Structural",
    "Gen3bQualityScore",
    "Gen3bPhase2Quality",
    "Gen3bDecision",
    "Gen3bIssues",
    "Gen3bRetryGuidance",
    "Gen3bValidationResponse",
    # Simple validation
    "SimpleValidationResult",
]
