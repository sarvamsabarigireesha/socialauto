# SocialAuto QA smoke report

Date: 2026-08-29
Local target tested: `http://127.0.0.1:8000`
Expected app version after this round: `1.5.0`

## Scope covered
- Auth register/login/me
- Forgot-password + reset-password flow
- Old password rejection after reset
- Create account
- Duplicate account protection
- Invalid `post_type` validation
- Create scheduled post
- Bulk CSV scheduling
- Analytics summary endpoint
- Frontend marker checks for redesigned UI

## Results
- Total checks: 19
- Passed: 19
- Failed: 0

## Highlights
- Register works
- Login works with the new password after reset
- Old password is rejected after password reset
- Duplicate connected account is blocked with `409`
- Invalid `post_type` is blocked with `400`
- CSV bulk creation works
- Redesigned UI markers were present:
  - `auth-card-split`
  - `heroSummary`
  - `heroStatsMini`
  - `calJump`
  - `calendarToolbarNote`
  - `analyticsHighlights`
  - `accountSummary`

## Notes
This was a smoke test, not exhaustive browser automation. It confirms the main API flows and that the updated UI structure is present in the served HTML.
