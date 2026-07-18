#!/usr/bin/env python3
"""Structured API errors for the C1-B internal API.

Status-code separation (per C1-A-R2 contract):
  401 missing / invalid / expired identity
  403 valid identity but not authorized (role, cross-store, actor spoof)
  404 authenticated but resource not found
  409 idempotency conflict
  503 dependency / provider not ready (fail-closed)

No secrets, provider names, phone numbers, tokens, or schema detail ever enter a
response body or its error code. Cross-store denials never disclose existence.
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = ''):
        super().__init__(f'{status} {code}')
        self.status = status
        self.code = code
        # message is intentionally terse and free of internal detail
        self.message = message

    def to_body(self) -> dict:
        body = {'error_code': self.code}
        if self.message:
            body['message'] = self.message
        return body


def unauthorized(code: str = 'E-UNAUTHENTICATED', message: str = 'invalid or missing identity') -> ApiError:
    return ApiError(401, code, message)


def forbidden(code: str = 'E-FORBIDDEN', message: str = 'not authorized') -> ApiError:
    return ApiError(403, code, message)


def not_found(code: str = 'E-NOT-FOUND', message: str = 'resource not found') -> ApiError:
    return ApiError(404, code, message)


def unavailable(code: str = 'E-DEPENDENCY', message: str = 'dependency not ready') -> ApiError:
    return ApiError(503, code, message)
