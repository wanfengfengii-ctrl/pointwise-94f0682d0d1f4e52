from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ConversionProfile:
    name: str
    unit_factors: Mapping[str, int]
    quality_codes: Mapping[str, str]


V1_PROFILE = ConversionProfile(
    'v1',
    MappingProxyType({'uV': 1, 'mV': 1000}),
    MappingProxyType({'OK': '合格', 'RECHECK': '复检', 'BAD': '无效'}),
)


def get_profile(name: str) -> ConversionProfile:
    if name != V1_PROFILE.name:
        raise ValueError(f'unsupported conversion profile {name!r}')
    return V1_PROFILE
