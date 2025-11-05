# MIDIL CLI

A lightweight command-line interface for creating and managing **midil-kit** projects. Designed for speed, simplicity, and developer productivity.

---

## Quick Start

Get started with a new project in seconds:

```bash
# Install midil-kit
pip install midil-kit

# Create a new MIDIL API service
midil init my-api --type midil

# Move into your project folder
cd services/my-api

# Launch the service
midil launch --reload
```

**Available project types:** `midil`, `lambda`

---

## Core Overview

The **Core** module provides the essential tools and utilities that power every CLI command. It ensures consistency, logging, and reliable configuration management across all commands.

### Key Components

- **Config Loader** — Reads and validates `.json`, `.yaml`, or `.env` configuration files.
- **Logger Utility** — Unified logs with color-coded levels and optional file output.
- **Error Handler** — Gracefully manages exceptions and displays user-friendly messages.
- **File System Utils** — Handles safe writes, directory creation, and path normalization.
- **Environment Manager** — Loads and verifies environment variables at runtime.

Each of these utilities supports a consistent experience for any CLI command you execute.

---

## Init Command

The `init` command scaffolds new **midil-kit** projects using predefined templates.

### Usage

```bash
midil init [NAME] [--type TYPE]
```

| Option | Description | Default |
|---------|--------------|----------|
| `NAME` | Project name | `midil-project` |
| `--type` | Project type (`midil` or `lambda`) | `midil` |

### Example

```bash
# Default MIDIL API project
midil init

# Named MIDIL API project
midil init user-service --type midil

# Lambda function project
midil init my-lambda --type lambda
```

The CLI automatically sets up a structured project with configuration files, dependencies, and boilerplate code.

---

## Workflow Example

A typical workflow after initialization:

```bash
# 1. Navigate to your new project
cd services/my-api

# 2. Install dependencies
poetry install

# 3. Start development server
midil launch --reload

# 4. Run tests
midil test --coverage
```

After generation, you can modify dependencies, edit your `main.py`, or add environment variables as needed.

---

## Troubleshooting

If you encounter issues:

```bash
# Check installation
pip show midil-kit

# Install missing dependencies
pip install cookiecutter

# Enable debug output
midil init my-api --verbose
```

Common causes of errors include missing permissions, invalid templates, or outdated dependencies.

---

## Summary

The **MIDIL CLI** provides a fast, structured way to start and manage projects.

It abstracts repetitive setup work so you can focus on development:

- Clean project scaffolding with `init`
- Built-in logging, error handling, and configuration support
- Consistent developer workflow from creation to deployment

---

*Crafted with simplicity and clarity — inspired by Ocean.io documentation.*
