# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.1.1 (2026-06-22)

### Bug Fixes

- Fixed a bug where the wrong method was called on ArnParser; now correctly using the parse_arn method.

## v0.1.0 (2026-06-21)

### Features

- Auth: Cognito client credentials flow and JWT verification with a pluggable interface
- Event: Transport-agnostic event bus with SQS, Redis, and webhook producers/consumers
- HTTP: Async HTTP client with configurable retry and backoff strategies
- MidilAPI: FastAPI wrapper enforcing JSONAPI-compliant responses, pagination, and middleware
- JSONAPI: Document and resource serialization/deserialization spec
- Logger: Structured logging with configurable handlers
- CLI: `midil init`, `midil launch`, and `midil version` commands for project scaffolding and service management
- Settings: Environment-variable-driven configuration system
