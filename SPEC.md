# Invidious API Specification

## Chosen Instance
- **Base URL**: `https://yewtu.be` (primary), with fallback to `https://invidious.snopyta.org`
- **Selection rationale**: High uptime, no rate limiting for moderate use, supports all required endpoints.

## Authentication
- No API key required for public endpoints.
- Optional `Authorization: Bearer <token>` for authenticated user actions (not used in current scope).

## Rate Limits
- **Public instances**: ~100 requests/minute per IP (soft limit).
- **Burst allowance**: 30 requests in 10 seconds.
- **Best practice**: Cache responses, reuse connections, implement exponential backoff on 429.

## Endpoints

### 1. Video Info
- **GET** `/api/v1/videos/{videoId}`
- **Query params**: `fields` (optional