"""Detector registry: import every detector, expose ordered REGISTRY."""

from __future__ import annotations

from codereview.analyzers.base import Detector
from codereview.analyzers.detectors.excessive_nesting import ExcessiveNesting
from codereview.analyzers.detectors.nested_function import NestedFunction
from codereview.analyzers.detectors.prefer_any_all import PreferAnyAll
from codereview.analyzers.detectors.prefer_dataclass import PreferDataclass
from codereview.analyzers.detectors.prefer_defaultdict import PreferDefaultdict
from codereview.analyzers.detectors.prefer_dict_get import PreferDictGet
from codereview.analyzers.detectors.prefer_enumerate import PreferEnumerate
from codereview.analyzers.detectors.prefer_f_string import PreferFString
from codereview.analyzers.detectors.prefer_identity import PreferIdentity
from codereview.analyzers.detectors.prefer_key_sorted import PreferKeySorted
from codereview.analyzers.detectors.prefer_list_comp import PreferListComprehension
from codereview.analyzers.detectors.prefer_next_gen import PreferNextGen
from codereview.analyzers.detectors.prefer_pathlib import PreferPathlib
from codereview.analyzers.detectors.prefer_removeprefix import PreferRemovePrefix
from codereview.analyzers.detectors.prefer_str_join import PreferStrJoin
from codereview.analyzers.detectors.prefer_top_level_imports import PreferTopLevelImports
from codereview.analyzers.detectors.prefer_with_open import PreferWithOpen
from codereview.analyzers.detectors.prefer_zip import PreferZip

REGISTRY: list[Detector] = [
    PreferListComprehension(),
    PreferEnumerate(),
    PreferIdentity(),
    PreferDefaultdict(),
    PreferFString(),
    PreferWithOpen(),
    PreferZip(),
    PreferDictGet(),
    PreferAnyAll(),
    PreferStrJoin(),
    PreferPathlib(),
    PreferDataclass(),
    PreferKeySorted(),
    PreferNextGen(),
    PreferRemovePrefix(),
    ExcessiveNesting(),
    NestedFunction(),
    PreferTopLevelImports(),
]

__all__ = ["REGISTRY"]