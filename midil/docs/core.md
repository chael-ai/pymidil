
# Core Module

The **Core** module provides the foundational utilities and logic that power the CLI. 
It contains helper classes, configuration parsers, validation routines, and I/O operations 
that other modules (like `commands`) depend on.

---

## Overview

The `core` folder includes the following key components:

- **Config Loader:** Handles reading and parsing of configuration files (e.g., `.json`, `.yaml`).
- **Logger Utility:** Provides standardized logging for both command-line and programmatic operations.
- **Error Handler:** Centralized exception management for consistent output and debugging.
- **File System Utils:** Handles path validation, directory creation, and safe file writes.
- **Environment Manager:** Reads and manages environment variables and runtime flags.

---

## 1. Config Loader

This component ensures configuration files are properly parsed and validated before use.  
It supports `.json`, `.yaml`, and `.env` file formats.

```js
// Example usage
import { loadConfig } from '../core/config';

const config = loadConfig('config.yaml');
console.log(config.server.port);
```

### Key Features

- Auto-detects file type based on extension.
- Validates required fields using schema definitions.
- Supports environment variable interpolation (`${VAR_NAME}` syntax).

---

## 2. Logger Utility

A unified logging interface that supports multiple output levels (info, warning, error, debug).

```js
import logger from '../core/logger';

logger.info('Starting process...');
logger.error('Invalid configuration detected');
```

### Features

- Timestamps and color-coded output.
- Optional file logging via configuration.
- Silencer mode for tests or silent runs.

---

## 3. Error Handler

Ensures that all runtime errors are handled gracefully and consistently.

```js
import { handleError } from '../core/errors';

try {
  performAction();
} catch (err) {
  handleError(err);
}
```

### Capabilities

- Maps known errors to user-friendly messages.
- Provides optional stack trace visibility for debugging.
- Can output machine-readable JSON for integration.

---

## 4. File System Utils

Responsible for safe and atomic file operations.

```js
import { ensureDir, writeFile } from '../core/fs';

ensureDir('./output');
writeFile('./output/result.json', data);
```

### Highlights

- Prevents overwriting existing data unless explicitly allowed.
- Recursively creates missing directories.
- Normalizes paths across operating systems.

---

## 5. Environment Manager

Loads and validates environment variables for runtime configuration.

```js
import { loadEnv } from '../core/env';

const env = loadEnv(['API_KEY', 'DB_HOST']);
console.log(env.API_KEY);
```

### Features

- Supports default values.
- Warns if required variables are missing.
- Provides type coercion (e.g., strings to booleans/numbers).

---

## 6. Core Constants and Types

Defines common constants and TypeScript interfaces used across modules.

```ts
export interface CLIOptions {
  verbose?: boolean;
  configPath?: string;
}

export const DEFAULT_CONFIG = 'cli.config.json';
```

---

## 7. Summary

The `core` module is the backbone of the CLI system. It abstracts repetitive logic and 
ensures every command has consistent access to logging, configuration, and error management.

For developers extending this package:
- Start with the `core` utilities.
- Reuse provided helpers for consistency.
- Avoid duplicating functionality already in core.
