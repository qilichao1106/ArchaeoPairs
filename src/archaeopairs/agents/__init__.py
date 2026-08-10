# -*- coding: utf-8 -*-
"""Agent 注册表（DAG 节点编排由 orchestration/graph.py 驱动）。"""
from .a0_preprocess import A0Preprocess, BookIndexer, BookIndex, FigureRecord, BodyPara
from .a1a_note import A1aNoteParse
from .a1b_body import A1bBodyNLP, build_artifact_records
from .a1c_aggregate import A1cTextAggregate
from .a2_classify import A2FigureClassify
from .a3_ocr import A3ImageParse
from .a4_fuse import A4FuseArbitrate
from .a5_segment import A5VisionSegment
from .a6_plate import A6PlateParse
from .a7_assemble import A7Assemble
from .a8_qc import A8QualityCheck

AGENTS = {
    a.name: a for a in [
        A0Preprocess(), A1aNoteParse(), A1bBodyNLP(), A1cTextAggregate(),
        A2FigureClassify(), A3ImageParse(), A4FuseArbitrate(), A5VisionSegment(),
        A6PlateParse(), A7Assemble(), A8QualityCheck(),
    ]
}

__all__ = ["AGENTS", "BookIndexer", "BookIndex", "FigureRecord", "BodyPara",
           "build_artifact_records"]
