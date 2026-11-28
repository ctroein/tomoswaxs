"""Volume locations: keep HTTP URLs intact and local paths as paths."""
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit, unquote


def is_http_url(value):
    return isinstance(value,str) and value.strip().lower().startswith(('http:','https:'))


def http_url(value):
    value=str(value).strip()
    try:
        parts=urlsplit(value)
        if parts.scheme.lower() not in ('http','https') or not parts.hostname or parts.fragment:
            raise ValueError()
        parts.port  # Validate a supplied port too.
    except ValueError:
        raise ValueError('Enter an HTTP or HTTPS URL for the OME-Zarr image root.') from None
    return urlunsplit((parts.scheme.lower(),parts.netloc,parts.path,parts.query,''))


def source_location(value):
    if is_http_url(value):return http_url(value)
    if isinstance(value,str) and '://' in value:
        raise ValueError('Supported volume URLs use HTTP or HTTPS.')
    return Path(value).expanduser().resolve()


def source_name(value):
    if is_http_url(value):
        parts=urlsplit(value)
        return unquote(PurePosixPath(parts.path.rstrip('/')).name) or parts.hostname
    return Path(value).name


def source_stem(value):
    return PurePosixPath(source_name(value)).stem
