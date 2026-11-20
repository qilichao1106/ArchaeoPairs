"""Text-to-artifact mapping (seq -> artifact_id, T-003), the per-figure
view binding / grouping / ArtifactMap assembly (T-007) and three-tier scale
bar binding (T-008)."""

from archaeopairs.mapping.scales import apply_scale_bindings, bind_scales
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
    ScaleBinding,
    ViewBinding,
    ViewGroup,
)

__all__ = [
    "build_text_mapping",
    "bind_labels_to_views",
    "group_views",
    "build_artifact_map",
    "normalize_seq_label",
    "bind_scales",
    "apply_scale_bindings",
    "ArtifactMap",
    "ArtifactUnit",
    "ScaleBinding",
    "ViewBinding",
    "ViewGroup",
]