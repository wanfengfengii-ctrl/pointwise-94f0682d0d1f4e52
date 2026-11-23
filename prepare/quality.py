from prepare.profile import ConversionProfile


def normalize_quality(status: str, profile: ConversionProfile) -> str:
    try:
        return profile.quality_codes[status]
    except KeyError:
        raise ValueError(f'unsupported device status {status!r}') from None
