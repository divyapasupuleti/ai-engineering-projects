---
source: troubleshooting-guide
doc_type: troubleshooting
updated: 2026-08-15
access: internal
---
# Troubleshooting Guide

## ERR-4012 token expired
Error ERR-4012 means the session token has expired. Ask the user to sign out and sign in again. If ERR-4012 repeats, clear browser cookies for the app domain.

## ERR-5003 upstream timeout
Error ERR-5003 is returned when an upstream integration does not respond within 30 seconds. Check the integration status page and retry with exponential backoff.

## Sync stuck at 99 percent
When file sync stalls at 99 percent, pause sync, wait one minute, and resume. Large files over 2 GB sync in the background and may take several minutes.

## Login loop on SSO
A login loop on SSO is usually caused by a mismatched SAML entity ID. Ask the workspace admin to compare the entity ID in the identity provider with the value shown on the SSO settings page.
