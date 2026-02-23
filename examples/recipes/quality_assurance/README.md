# Recipe: Quality Assurance (QA)

Testing new features or links before they go live to ensure nothing is broken.

## Why

Broken features kill trust. One bad deploy can undo months of goodwill with your users. This agent runs systematic checks before anything goes live — catching the broken links, form errors, and edge cases that would otherwise reach your customers first.

## What

- Run automated test suites before deploys
- Manually verify critical user flows (signup, checkout, core features)
- Check all links for 404s and broken redirects
- Test across browsers and device sizes
- Verify integrations are responding correctly

## Integrations

| Platform | Purpose |
|----------|---------|
| GitHub Actions / CircleCI | CI/CD pipeline integration |
| Playwright / Cypress / Selenium | Automated browser testing |
| BrowserStack / LambdaTest | Cross-browser testing |
| Checkly / Uptrends | Synthetic monitoring |
| Slack / PagerDuty | Test failure alerts |
| Linear / Jira | Bug ticket creation |

## Escalation Path

| Trigger | Action |
|---------|--------|
| Critical test fails (auth, checkout, data) | Block deploy, alert immediately with failure details |
| Flaky test (passes sometimes, fails others) | Flag for investigation but don't block |
| New feature breaks existing functionality | Alert with regression details and affected areas |
| Performance degradation detected | Flag with before/after metrics |
| Security scan finds vulnerability | Immediate escalation with severity and remediation |
| All tests pass but something "feels off" | Document observation and flag for human review |
