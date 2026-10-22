"""Compatibility with the two JSON hash formats actually used upstream.

The authority digest is never changed. This adapter does not alter upstream
code or the compact hash used for new run/checkpoint contracts.
"""
from __future__ import annotations
import hashlib
import json
from next_common import require


def config_hash_audit(config, expected):
    require(isinstance(config, dict), 'Historical configuration must be a JSON object')
    # A JSON-loaded historical configuration has no NumPy/Path objects to clean.
    # Reject nonfinite JSON numbers instead of silently replacing them.
    payloads = {
        'legacy_sorted_json_default_spaces': json.dumps(config, sort_keys=True, allow_nan=False),
        'compact_sorted_json': json.dumps(config, sort_keys=True, separators=(',', ':'), allow_nan=False),
    }
    digests = {name: hashlib.sha256(value.encode('utf-8')).hexdigest()
               for name, value in payloads.items()}
    matches = [name for name, digest in digests.items() if digest == expected]
    return {'expected_sha256': expected, 'observed_sha256': digests,
            'matched_serializations': matches, 'matched': bool(matches),
            'configuration_values_exported': False}


def require_config_hash(config, expected, label):
    audit = config_hash_audit(config, expected)
    require(audit['matched'], label + ' configuration differs from the fixed authority digest; '
            'neither upstream JSON serialization matches')
    return audit
