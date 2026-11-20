"""Text-to-artifact mapping (seq -> artifact_id, T-003) and the per-figure
view binding / grouping / ArtifactMap assembly (T-007)."""

from archaeopairs.mapping.text_map import build_text_mapping
from archaeopairs.mapping.views import (
    bind_labels_to_views,
    build_artifact_map,
    group_views,
    normalize_seq_label,
)
from archaeopairs.models import (
    ArtifactMap,
    ArtifactUnit,
    ViewBinding,
    ViewGroup,
)

__all__ = [
    "build_text_mapping",
    "bind_labels_to_views",
    "group_views",
    "build_artifact_map",
    "normalize_seq_label",
    "ArtifactMap",
    "ArtifactUnit",
    "ViewBinding",
    "ViewGroup",
]
